#!/usr/bin/env bash
# End-to-end smoke verification for the loan approval pipeline.
#
# Up the docker stack, register a customer, submit an application,
# wait for the orchestrator pipeline to produce a decision + email,
# then write a machine-readable result file.
#
# Usage:
#   tools/smoke_e2e.sh              # full cycle + teardown
#   tools/smoke_e2e.sh --keep-up    # leave stack running for manual inspection

set -euo pipefail

KEEP_UP=false
if [[ "${1:-}" == "--keep-up" ]]; then
  KEEP_UP=true
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="${REPO_ROOT}/tools/smoke_fixtures/smoke_applicant.json"
RESULT_FILE="${REPO_ROOT}/.tmp/smoke_result.json"
API_BASE="http://localhost:8000/api/v1"

mkdir -p "${REPO_ROOT}/.tmp"

started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
start_ms=$(date +%s%3N)

cleanup() {
  if [[ "${KEEP_UP}" == "false" ]]; then
    echo "[smoke] Tearing down docker compose stack..."
    (cd "${REPO_ROOT}" && docker compose down) || true
  else
    echo "[smoke] --keep-up specified; leaving stack running."
  fi
}
trap cleanup EXIT

write_result() {
  local status="$1"
  local reason="$2"
  local model_version="${3:-}"
  local email_hash="${4:-}"
  local end_ms
  end_ms=$(date +%s%3N)
  local duration=$((end_ms - start_ms))

  cat > "${RESULT_FILE}" <<JSON
{
  "started_at": "${started_at}",
  "finished_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "duration_ms": ${duration},
  "status": "${status}",
  "reason": "${reason}",
  "model_version_id": "${model_version}",
  "email_subject_hash": "${email_hash}"
}
JSON

  echo "[smoke] Result written to ${RESULT_FILE}"
  cat "${RESULT_FILE}"
}

echo "[smoke] Starting docker compose..."
(cd "${REPO_ROOT}" && docker compose up -d)

echo "[smoke] Waiting for /api/v1/health/ to return 200..."
for i in {1..60}; do
  if curl -fsS "${API_BASE}/health/" > /dev/null 2>&1; then
    echo "[smoke] Backend healthy after ${i}s."
    break
  fi
  if [[ "${i}" == "60" ]]; then
    write_result "failure" "backend-healthcheck-timeout"
    exit 1
  fi
  sleep 1
done

random=$(tr -dc 'a-z0-9' < /dev/urandom | head -c 8 || echo "smoke$(date +%s)")
username=$(jq -r ".user.username" "${FIXTURE}" | sed "s/{{RANDOM}}/${random}/")
email=$(jq -r ".user.email" "${FIXTURE}" | sed "s/{{RANDOM}}/${random}/")
password=$(jq -r ".user.password" "${FIXTURE}")
first_name=$(jq -r ".user.first_name" "${FIXTURE}")
last_name=$(jq -r ".user.last_name" "${FIXTURE}")

COOKIE_JAR="${REPO_ROOT}/.tmp/smoke_cookies_${random}.txt"
trap 'rm -f "${COOKIE_JAR}"; cleanup' EXIT

csrf_header() {
  local token
  token=$(awk '/csrftoken/ {print $NF}' "${COOKIE_JAR}" | tail -n 1)
  echo "X-CSRFToken: ${token}"
}

echo "[smoke] Registering customer ${email} (username=${username})..."
curl -fsS -X POST "${API_BASE}/auth/register/" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${username}\",\"email\":\"${email}\",\"password\":\"${password}\",\"password2\":\"${password}\",\"first_name\":\"${first_name}\",\"last_name\":\"${last_name}\"}" \
  > /dev/null || { write_result "failure" "register-failed"; exit 1; }

echo "[smoke] Logging in (cookie auth)..."
curl -fsS -c "${COOKIE_JAR}" -X POST "${API_BASE}/auth/login/" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${username}\",\"password\":\"${password}\"}" \
  > /dev/null || { write_result "failure" "login-failed"; exit 1; }

if ! grep -q "csrftoken" "${COOKIE_JAR}"; then
  write_result "failure" "no-csrf-cookie"
  exit 1
fi

echo "[smoke] Populating customer profile..."
profile_payload=$(jq -c ".profile" "${FIXTURE}")
curl -fsS -b "${COOKIE_JAR}" -X PATCH "${API_BASE}/auth/me/profile/" \
  -H "Content-Type: application/json" \
  -H "$(csrf_header)" \
  -H "Referer: http://localhost:8000/" \
  -d "${profile_payload}" \
  > /dev/null || { write_result "failure" "profile-patch-failed"; exit 1; }

echo "[smoke] Submitting loan application..."
application_payload=$(jq -c ".application" "${FIXTURE}")
application_response=$(curl -fsS -b "${COOKIE_JAR}" -X POST "${API_BASE}/loans/" \
  -H "Content-Type: application/json" \
  -H "$(csrf_header)" \
  -H "Referer: http://localhost:8000/" \
  -d "${application_payload}" \
  || { write_result "failure" "application-submit-failed"; exit 1; })
application_id=$(echo "${application_response}" | jq -r ".id // .uuid // empty")
if [[ -z "${application_id}" ]]; then
  write_result "failure" "no-application-id-returned"
  exit 1
fi
echo "[smoke] Application ${application_id} submitted."

echo "[smoke] Triggering orchestrator..."
curl -fsS -b "${COOKIE_JAR}" -X POST "${API_BASE}/agents/orchestrate/${application_id}/" \
  -H "$(csrf_header)" \
  -H "Referer: http://localhost:8000/" \
  > /dev/null \
  || { write_result "failure" "orchestrate-trigger-failed"; exit 1; }

echo "[smoke] Polling for terminal decision (120s ceiling)..."
decision=""
app_detail=""
for i in {1..120}; do
  app_detail=$(curl -fsS -b "${COOKIE_JAR}" "${API_BASE}/loans/${application_id}/")
  decision=$(echo "${app_detail}" | jq -r ".status // empty")
  if [[ "${decision}" == "approved" || "${decision}" == "declined" || "${decision}" == "referred" ]]; then
    echo "[smoke] Terminal decision reached after ${i}s: ${decision}"
    break
  fi
  sleep 1
done

if [[ "${decision}" != "approved" && "${decision}" != "declined" && "${decision}" != "referred" ]]; then
  write_result "failure" "no-terminal-decision-in-120s"
  exit 1
fi

model_version=$(echo "${app_detail}" | jq -r ".model_version_id // .ml_prediction.model_version // .prediction.model_version_id // empty")

echo "[smoke] Polling for generated email (30s ceiling)..."
email_subject=""
for i in {1..30}; do
  email_detail=$(curl -fsS -b "${COOKIE_JAR}" "${API_BASE}/emails/${application_id}/" 2>/dev/null || echo "{}")
  email_subject=$(echo "${email_detail}" | jq -r ".subject // empty")
  if [[ -n "${email_subject}" ]]; then
    break
  fi
  sleep 1
done

email_hash=""
if [[ -n "${email_subject}" ]]; then
  email_hash=$(printf "%s" "${email_subject}" | sha256sum | cut -c1-16)
fi

if [[ -z "${email_hash}" ]]; then
  write_result "failure" "no-email-generated"
  exit 1
fi

write_result "success" "ok" "${model_version}" "${email_hash}"
echo "[smoke] SUCCESS."
