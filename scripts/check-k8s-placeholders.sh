#!/usr/bin/env bash
# check-k8s-placeholders.sh
#
# Fail if the manifests that `kubectl apply -k` would actually ship contain a
# placeholder credential: CHANGE_ME / change-me in plain text, or its base64
# form "Q0hBTkdFX01F" (= echo -n 'CHANGE_ME' | base64).
#
# It scans the rendered kustomize output, not the directory, so templates
# that are deliberately outside the kustomization (k8s/secrets.env.example)
# do not trip it, and anything a future edit adds to the kustomization does.
# Runs in CI (.github/workflows/validate-infra.yml) and before any deploy.
#
# Usage: ./scripts/check-k8s-placeholders.sh [k8s-dir]
# Needs `kubectl` (kustomize is built in) or a standalone `kustomize`.
#
# Exit codes:
#   0 — rendered output has no placeholder credentials
#   1 — placeholders found, or the kustomization failed to render

set -euo pipefail

K8S_DIR="${1:-k8s}"
PATTERN='Q0hBTkdFX01F|CHANGE_ME|change-me'

if command -v kustomize >/dev/null 2>&1; then
  RENDERED=$(kustomize build "${K8S_DIR}")
else
  RENDERED=$(kubectl kustomize "${K8S_DIR}")
fi

echo "Scanning rendered ${K8S_DIR}/ kustomization for placeholder credentials..."

# grep exits 1 on no match; || true so set -e does not abort on the happy path.
MATCHES=$(printf '%s\n' "${RENDERED}" | grep -nE "${PATTERN}" || true)

if [ -n "${MATCHES}" ]; then
  echo ""
  echo "ERROR: the rendered manifests contain placeholder credentials:"
  echo "${MATCHES}"
  echo ""
  echo "Secrets must be created out of band (see k8s/secrets.env.example),"
  echo "not rendered from the repo."
  exit 1
fi

echo "OK — no placeholder credentials in the rendered ${K8S_DIR}/ kustomization."
exit 0
