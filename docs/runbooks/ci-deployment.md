# CI gate and image deployment

How pull requests are gated and how images reach GHCR. Workflow files: `.github/workflows/`.

## Symptoms

- A PR cannot merge because the required check `ci-gate` failed or is still pending.
- Images for a master commit were not pushed to GHCR.
- A PR shows a required check stuck as "Expected — Waiting for status to be reported".

## How it fits together

`ci.yml` is the only workflow triggered by `push` and `pull_request` for the main checks. It calls reusable workflows (`on: workflow_call`), so every job sits in one `needs:` graph:

| Caller job | Workflow | Jobs |
|---|---|---|
| `test` | `test.yml` | Backend Tests, Frontend Tests |
| `lint` | `lint.yml` | Backend Lint, Frontend Lint & Type Check, ml_engine quality bar, Backend mypy |
| `security` | `security.yml` | Security Scan (bandit), Dependency Audit, secret-scan (gitleaks) |
| `build` | `build.yml` | Docker Build + Trivy, OWASP ZAP DAST, k6 Load Test (master only) |
| `infra` | `validate-infra.yml` | kubeconform + k8s policy + placeholder scan, terraform fmt/validate, promtool/amtool, compose config |

`ci-gate` needs all five and fails unless every one of them concluded `success`, including failures, cancellations and unexpected skips. `deploy` ("Build & Push Images") needs `ci-gate` and runs only on pushes to `master`, so an image is published only for a commit whose tests, lint, security scans and infra validation all passed.

Path-filtered workflows (`email-parity.yml`, `email-preview-e2e.yml`) and the post-merge `smoke-e2e.yml` run separately and are not part of the gate: a path-filtered check cannot be required, because it never reports on PRs that do not touch its paths.

## Required status check

Branch protection on `master` must require exactly one check: **`ci-gate`**. Do not list the individual jobs. Their check names are prefixed by the caller job (e.g. `test / Backend Tests`) and change when a job is renamed. A required name that no job reports stays "Expected" forever, which forces admin merges that skip every check.

Verify against a live PR, not the settings page:

```bash
gh pr checks <pr-number> --required     # must list ci-gate
gh api repos/<owner>/<repo>/branches/master/protection --jq '.required_status_checks.contexts'
```

## Repository variable

`deploy` bakes the frontend's API origin into the image, because `NEXT_PUBLIC_*` values are compiled into the bundle:

- **`PUBLIC_API_URL`** (Settings → Secrets and variables → Actions → Variables), e.g. `https://app.example.com/api/v1`.
- If unset, the build uses `/api/v1`, the same-origin path the k8s Ingress routes to the backend.

## Diagnose

1. Open the failed `ci-gate` run. Its log lists each caller job with its result.
2. Open the failing caller job (`test`, `lint`, ...) to find the inner job and step.
3. If `ci-gate` itself is missing from a PR, check that `ci.yml` is on the PR's base branch and that its `on.pull_request.branches` includes the target branch.

## Remediate

- Fix the failing job and push; `ci-gate` re-runs with the workflow.
- To re-run after a flaky failure: re-run the failed jobs from the `CI` workflow run (this re-evaluates `ci-gate`).
- When adding a new check, add it to a reusable workflow already in `ci-gate`'s `needs`, or add a new caller job to `ci.yml` and to `ci-gate.needs`. Do not add `push`/`pull_request` triggers to the reusable workflows.

## Escalate

Branch protection changes need a repository admin. Attach the `gh pr checks --required` output and the failing run URL.
