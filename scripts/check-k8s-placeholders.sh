#!/usr/bin/env bash
# check-k8s-placeholders.sh
#
# Fail CI if any k8s manifest still contains the base64 placeholder
# "Q0hBTkdFX01F" (= echo -n 'CHANGE_ME' | base64).
#
# Run before deploying or in CI on every PR targeting master.
# Usage: ./scripts/check-k8s-placeholders.sh [k8s-dir]
#
# Exit codes:
#   0 — no placeholders found; safe to deploy
#   1 — one or more files still contain CHANGE_ME placeholder values

set -euo pipefail

K8S_DIR="${1:-k8s}"
PLACEHOLDER="Q0hBTkdFX01F"

echo "Scanning ${K8S_DIR}/ for CHANGE_ME placeholders (base64: ${PLACEHOLDER})..."

# grep -rl returns file list; || true so grep non-match doesn't fail the set -e
MATCHES=$(grep -rl "${PLACEHOLDER}" "${K8S_DIR}" || true)

if [ -n "${MATCHES}" ]; then
  echo ""
  echo "ERROR: The following k8s manifests still contain placeholder secrets:"
  echo "${MATCHES}"
  echo ""
  echo "Replace all CHANGE_ME values with real secrets before deploying."
  echo "See k8s/secrets.yaml for instructions."
  exit 1
fi

echo "OK — no CHANGE_ME placeholders found in ${K8S_DIR}/."
exit 0
