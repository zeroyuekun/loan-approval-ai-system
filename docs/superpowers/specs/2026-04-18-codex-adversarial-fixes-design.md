# Codex Adversarial Review — v1.9.3 Security & Reliability Hardening

**Date:** 2026-04-18
**Status:** Approved design, pending implementation plan
**Scope:** Four high-severity findings from the 2026-04-18 Codex adversarial review

## Context

A Codex adversarial review of the whole project surfaced four high-severity, production-blocking issues. This spec turns each into an approved fix with a defined test surface and ships them as four atomic PRs stacked on master under a new `v1.9.3 — Security & Reliability Hardening` CHANGELOG section.

Packaging rationale: four atomic PRs mirror the v1.9.1 review-response pattern. Each fix has a distinct test surface and failure mode; bundling them would muddy revert boundaries if one regresses.

## Findings at a glance

| # | Finding | File(s) | Severity |
|---|---|---|---|
| 1 | Cookie JWT auth skips CSRF | `backend/apps/accounts/authentication.py` | high |
| 2 | `/metrics` + deep health publicly reachable | `k8s/ingress.yaml`, `backend/config/urls.py` | high |
| 3 | Frontend always calls orchestrate with `force=true` | `frontend/src/lib/api.ts`, `backend/apps/agents/views.py` | high |
| 4 | Loan submission succeeds when Celery dispatch fails | `backend/apps/loans/views.py` | high |

## Finding 1 — CSRF enforcement on cookie auth

**Problem.** `CookieJWTAuthentication.authenticate()` accepts a JWT directly from an `HttpOnly` cookie and returns a user without performing any CSRF validation. The frontend sends `X-CSRFToken`, but the backend never verifies it. Any site that can induce a cross-site request from a victim browser can hit mutating endpoints with the victim's loan/session context.

**Chosen approach.** Enforce Django's CSRF check on the cookie path only; leave the header fallback untouched so programmatic clients (tests, CLI) continue to use explicit `Authorization: Bearer ...` without CSRF.

**Design.**
- Add a private helper on `CookieJWTAuthentication`:
  ```python
  def _enforce_csrf(self, request):
      check = CsrfViewMiddleware(lambda r: None)
      check.process_request(request)
      reason = check.process_view(request, None, (), {})
      if reason:
          raise exceptions.PermissionDenied("CSRF Failed: " + str(reason))
  ```
- Call `_enforce_csrf(request)` *only* when the cookie path returns a token. Header-fallback path is unchanged.
- No frontend changes — `X-CSRFToken` is already sent for `post|put|patch|delete` (`api.ts:77-86`).

**Alternative considered.** Rip out cookie-based JWT auth and use bearer headers only. Rejected — frontend refactor cost, no security gain vs Approach 1, and cookies remain the right pattern for browser-based SPAs using HttpOnly storage.

**Tests.**
- `backend/tests/test_auth_security.py`:
  - cookie auth + no `X-CSRFToken` → 403 with reason containing "CSRF Failed"
  - cookie auth + valid `X-CSRFToken` → 200
  - `Authorization: Bearer ...` (no cookie) → 200 with or without CSRF header

## Finding 2 — Ops endpoints hardening

**Problem.** `django_prometheus` URLs are mounted at project root with no auth (`backend/config/urls.py:209`). `deep_health_check` only enforces `HEALTH_CHECK_TOKEN` when set, defaulting to open. The Kubernetes ingress publishes `/metrics` on the public application host (`k8s/ingress.yaml:31-37`). Any external caller can enumerate queue depth, budget usage, model versions, and dependency health.

**Chosen approach.** Remove `/metrics` from public ingress (keep in-cluster access for Prometheus scraping), and require an auth signal on all deep-health responses regardless of environment. Gate `django_prometheus` URLs behind a staff-or-token decorator.

**Design.**
- `k8s/ingress.yaml`: delete the `/metrics` path rule. Metrics remain reachable at `backend:8000/metrics` via cluster Service DNS for Prometheus sidecars.
- `backend/config/urls.py`:
  - Replace `path("", include("django_prometheus.urls"))` with a direct `path("metrics", require_ops_auth(ExportToDjangoView))`, where `ExportToDjangoView` is imported from `django_prometheus.exports` and `require_ops_auth` is a new decorator that accepts either a staff session OR `X-Health-Token` matching `HEALTH_CHECK_TOKEN`. If neither present → 403.
  - In `deep_health_check`, stop treating empty token as "open." If `HEALTH_CHECK_TOKEN` is unset and `DEBUG=False`, return 503 with `"deep health not configured"`. Keep open access when `DEBUG=True` for local development.
- Update `backend/docs/RUNBOOK.md` row for `/metrics` to reflect auth requirement.
- `apps/agents/management/commands/watchdog.py` already sends the token; no change.
- Prometheus scrape configs (docker-compose + future k8s ServiceMonitor) must set the token header; update `infra/prometheus/prometheus.yml` scrape job with `authorization:` or `Authorization` header.

**Alternative considered.** Separate internal-only listener (second bind). Rejected — adds Gunicorn/Docker/k8s plumbing disproportionate to the codebase.

**Tests.**
- `backend/tests/test_ops_endpoints.py` (new):
  - `GET /metrics` unauthenticated → 403
  - `GET /metrics` with valid `X-Health-Token` → 200 + prometheus text
  - `GET /metrics` with staff session cookie → 200
  - `GET /api/v1/health/deep/` in prod settings with no token configured → 503 "deep health not configured"
  - `GET /api/v1/health/deep/` with token configured but wrong header → 403

## Finding 3 — Orchestration `force` guard

**Problem.** `frontend/src/lib/api.ts:193` always calls `POST /agents/orchestrate/<loan_id>/?force=true`. The backend's `orchestrate_pipeline_task(..., force=True)` bypasses the completed-run short-circuit, producing duplicate `AgentRun` rows, fresh predictions, regenerated offers and marketing artifacts, and potentially re-sent emails on every user click.

**Chosen approach.** Default UI to the idempotent path; treat force as a staff-only, audit-logged operation with a required reason.

**Design.**
- `frontend/src/lib/api.ts`:
  - `agentsApi.orchestrate(loanId)` → drop `?force=true` (non-force path).
  - Add `agentsApi.forceRerun(loanId, reason)` → `POST /agents/orchestrate/<loan_id>/?force=true&reason=<reason>`.
- `backend/apps/agents/views.py` — the `orchestrate_loan` view:
  - If `force=true` and `request.user.role not in ("admin", "officer")` → 403 `{"detail": "force rerun requires staff role"}`.
  - If `force=true` and `reason` missing/empty → 400 `{"detail": "reason is required for force rerun"}`.
  - Before dispatching force, write `AuditLog(action="pipeline_force_rerun", user=request.user, resource_type="LoanApplication", resource_id=loan_id, details={"reason": reason})`.
  - Non-force path unchanged — completed runs short-circuit in `orchestrate_pipeline_task` as today.
- `frontend`: wire `forceRerun` into the admin Review panel (`BiasReviewQueue` or equivalent staff-only UI) with a reason textarea. No customer-facing UI calls it.

**Alternative considered.** Remove `force` entirely. Rejected — admins legitimately need to re-run after bias-flag resolution or model retraining; removing the endpoint pushes the operation to `manage.py` / Django admin and loses the structured audit entry.

**Tests.**
- `backend/tests/test_orchestration_force.py` (new):
  - customer POST with `?force=true` → 403
  - staff POST with `?force=true` and no reason → 400
  - staff POST with `?force=true&reason=bias+fix` → 202, new `AgentRun`, AuditLog row with reason
  - customer POST without force on already-completed loan → 200 + existing AgentRun, no duplicate created
- Frontend: type check passes; Review panel renders force button + reason input; customer dashboard shows regenerate button that calls non-force path.

## Finding 4 — Durable submission via on_commit + outbox

**Problem.** `LoanApplicationViewSet.perform_create` commits the loan + audit log inside a transaction, then calls `orchestrate_pipeline_task.delay(...)` *outside* the transaction wrapped in a bare `try/except` that downgrades any exception to `logger.warning` and still returns 201. If the broker is unreachable the application sits in `pending` indefinitely with no pipeline run and no recovery signal.

**Chosen approach.** Hybrid: dispatch via `transaction.on_commit` in the happy path, persist to a small outbox table + flag the loan status on failure, and drain the outbox on a beat schedule.

**Design.**
- New model `apps.loans.models.PipelineDispatchOutbox`:
  ```
  id (pk), application (FK LoanApplication, unique), attempts (int, default 0),
  last_error (text, nullable), last_attempt_at (datetime, nullable),
  created_at (datetime, auto_now_add)
  ```
- New `LoanApplication.Status.QUEUE_FAILED = "queue_failed"` sentinel (additive — no removals).
- In `perform_create`, move dispatch under `transaction.on_commit`:
  ```python
  def _dispatch():
      try:
          orchestrate_pipeline_task.delay(str(instance.pk))
      except Exception as exc:
          PipelineDispatchOutbox.objects.create(application=instance, last_error=str(exc))
          LoanApplication.objects.filter(pk=instance.pk).update(status=LoanApplication.Status.QUEUE_FAILED)
          logger.error("Queue dispatch failed for %s: %s", instance.pk, exc)
  transaction.on_commit(_dispatch)
  ```
- New Celery beat task `apps.loans.tasks.retry_failed_dispatches` (every 60s):
  - Loads outbox rows with `attempts < MAX_DISPATCH_ATTEMPTS` (const = 5) ordered by `created_at`.
  - Per row: increment `attempts` first, then call `orchestrate_pipeline_task.delay(...)`. On success → delete outbox row + set status back to `pending`. On failure → persist `last_error` + `last_attempt_at` (attempts already incremented).
  - Rows that reach `attempts == MAX_DISPATCH_ATTEMPTS` are skipped by the beat task on subsequent runs; they stay in the outbox for operator visibility and increment a Prometheus counter `pipeline_dispatch_outbox_exhausted_total` once at the transition.
- API response still returns 201 on submission success. `status="queue_failed"` surfaces in dashboard filters (already supported generically via status filter).
- Admin can observe outbox via a small `OutboxAdmin` registration for operational visibility.

**Alternative considered.** Raise on dispatch failure and return 503. Rejected — users already spent effort completing the form; losing submission data on a transient broker outage is worse UX than a retry queue.

**Alternative considered.** Pure outbox for all dispatches (no direct `.delay`). Rejected — adds latency to the 99.9% happy path for a rare failure mode.

**Tests.**
- `backend/tests/test_submission_outbox.py` (new):
  - mock `orchestrate_pipeline_task.delay` to raise → loan saved, 201 returned, outbox row exists, status is `queue_failed`
  - direct call to `retry_failed_dispatches` with a pending outbox row and a mock that succeeds → row deleted, status back to `pending`, task dispatched
  - retry task with `attempts == 5` (max) → row skipped, no dispatch call, no increment (sticky until operator intervenes)
  - happy path unchanged: successful submission → no outbox row, status `pending`, `.delay` called once

## Cross-cutting

**PR sequence (stacked on master, independent):**
1. `fix/csrf-on-cookie-auth` — auth module + one test file
2. `fix/ops-endpoints-hardening` — `urls.py` + `ingress.yaml` + new test file + Prometheus config + RUNBOOK doc
3. `fix/orchestration-force-guard` — `agents/views.py` + `frontend/src/lib/api.ts` + Review panel UI + new test file
4. `fix/submission-outbox` — migration + model + view change + beat task + new test file

No inter-dependencies: each PR is independently mergeable and revertable.

**CHANGELOG.** New section `## v1.9.3 — Security & Reliability Hardening (2026-04-18)` with one bullet per PR.

**Docs.** Update `backend/docs/RUNBOOK.md` in PR 2 for the metrics auth requirement and the new `queue_failed` status in PR 4.

**Non-goals.** No changes to:
- ML pipeline behavior
- Email rendering or delivery
- Model training or bias evaluation logic
- Frontend styling or routing beyond the force button placement

## Open items

None. All four fixes have a single chosen approach and a defined test surface.
