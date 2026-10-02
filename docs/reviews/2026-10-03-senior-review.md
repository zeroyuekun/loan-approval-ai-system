# Senior review, 2026-10-03

Scope: the whole repository, on top of the open review stack with two-factor authentication removed. Five read-only audits ran in parallel: backend correctness (two areas), frontend, security, and architecture. An independent verifier then tried to disprove each Critical, High and Medium finding against the code. Only findings that survived were fixed. Every fix started with a test that failed on the old code.

Spec and plan: `docs/superpowers/specs/2026-10-03-remove-2fa-and-senior-review-design.md`, `docs/superpowers/plans/2026-10-03-remove-2fa-and-senior-review.md`.

## What was fixed

| PR | Area | Findings |
|---|---|---|
| #280 | Integration | Merges the open review stack (all leaves except #271) into one base |
| #281 | 2FA removal | TOTP, the login code step, the enrolment gate, the OTP admin login and django-otp removed; TOTP tables dropped; the legacy `2fa` overturn mode maps to `second_approver` |
| #283 | Frontend | Profile saves wiped stored ID numbers; admin edits invented $0 income; masked credit band shown as "Excellent"; "$NaN" amounts; Run Pipeline stuck after a first run; 404 toasts; `queue_failed` unhandled |
| #284 | Auth | Lockout that never expired; login timing oracle; login CSRF; Sentry receiving request bodies and frame locals; 8-character staff passwords |
| #285 | Architecture | Next-best-offer used a drifted copy of the HEM and shading rules; "active model" resolved five ways; about 1,870 lines of dead modules; stale workflow SOPs and a diverged standalone trainer |
| #287 | Pipeline | Duplicate decision email after a late failure; unscreened decision emails from Generate and overturns; overturn email sent inside the request; double letters from concurrent Generate; customer re-runs of reviewed applications; recheck of claimed reviews; stale restores; `queue_failed` retry; pricing and policy declines recorded as model declines; quoted rate below the risk tier |
| #288 | Governance | Staff could resolve reviews of their own applications; the four-eyes check missed human-review denials; deleting a user broke the audit hash chain (`AuditLog.user` is now `PROTECT`); audit rows recorded the proxy IP (19 sites now use `client_ip()`); the customer activity view double-escaped subjects and dropped bias fields; the human-review state machine moved out of the view |

Accepted risk from the 2FA removal: staff accounts rely on passwords alone. #284 makes the 12-character minimum apply to everyone, gives lockouts a time limit, and makes every login branch take the same time. High-value overturns stay behind the `second_approver` gate.

## Not fixed: Low severity, ranked

Backend correctness
1. `apps/loans/serializers.py` / `models.py`: "one open review per application" is a check-then-insert with no constraint, and uphold does not re-check that the application is still denied. Fix: a partial `UniqueConstraint`; on uphold, require `status == "denied"`.
2. `apps/accounts/fields.py`: encrypted columns allow 500 plaintext characters, but the Fernet token for 304 bytes or more exceeds 500, so a long address returns a 500 error. Fix: cap the serializer at about 300 bytes, or widen the columns.
3. `apps/accounts/views.py` `CustomerDataExportView`: the APP 12 export leaves out soft-deleted applications, complaints and decision reviews.
4. `apps/loans/views.py` `perform_update` and the admin `save_model`: a full-row save can overwrite a status the pipeline wrote in the meantime. Fix: `update_fields`.
5. `apps/accounts/management/commands/rotate_encryption_key.py`: reads every row once, then writes them all back, so an edit made during the rotation is reverted.
6. `apps/loans/views.py`: N+1 query on `decision__model_version` in the staff list.
7. `apps/loans/tasks.py` `retry_failed_dispatches`: still dispatches before the guarded release. Since #288 the release is one audited method (`release_queue_failed`) shared with the orchestrator, and the orchestrator accepts `queue_failed`, so a lost race now only causes a redundant dispatch.
8. `apps/agents` orchestrator: an autoretry or redelivery with the same task id hits its own fresh claim and is reset. After #287, a delivered decision is no longer lost when this happens.
9. `apps/agents/services/human_review_handler.py`: a broad `except` after the bias score fails open in warn or off mode.
10. `apps/agents/services/marketing_pipeline.py`: marketing emails are not de-duplicated per application.
11. `apps/email_engine/services/pricing.py`, `template_fallback.py`: customer-facing dates use the server's UTC date. Use `timezone.localdate()` with `Australia/Sydney`.
12. `apps/agents/services/api_budget.py`: a call that spans midnight reserves against one day's budget and reconciles against the next.
13. `SendLatestEmailView` still sends the latest draft without bias screening (pre-existing; #287 screens the Generate and redelivery paths).

Security
14. Refresh tokens slide forever, and a password change does not revoke them. Add an `auth_time` claim with a maximum session age, and blacklist outstanding tokens on a password change.
15. The Django admin login has no lockout or throttle, and the bootstrap superuser password skips `validate_password`. It is not reachable through the shipped ingress, which routes only `/api`.
16. `PATCH /auth/me/` can set an email another account already uses.
17. Client source-IP preservation (`externalTrafficPolicy: Local` or proxy protocol) is not configured or documented for the ingress controller.
18. `?page=0` or a negative page returns a 500 on the email and agent-run lists.
19. Neither `.dockerignore` excludes `.env*`.
20. In `ci.yml`, the `docker/*` actions are pinned by tag in a job with `packages: write`, and the email workflows have no `permissions:` block.

Frontend
21. Training-status polling never stops on a lost task or `REVOKED`.
22. The human-review submit does not invalidate the application's detail, run or email queries.
23. The sidebar removes focus indicators. The human-review action buttons have no `aria-pressed`.

Architecture
24. The standalone `PredictView` / `run_prediction_task` (off by default) duplicates the orchestrator's decision writes. Delete it together with `mlApi.predict` and its Prometheus alert.
25. The file-size cap only covers `ml_engine/services`, and 13 backend files are over 500 lines. Add ratchet entries for every `backend/apps` package and a frontend equivalent.
26. The `EMAIL_LLM_*`, `GROQ_*` and `OLLAMA_*` settings are never read (the generator reads `os.environ`), and `OLLAMA_MODEL` does nothing. `enforce_retention` says "archived" when it deletes.
27. The frontend types are hand-written although drf-spectacular is installed. Generate them from `/api/schema/` in CI.

## Larger architecture refactors (proposed, not done)

- **App import cycles.** All five apps import each other (7 two-way edges). `AuditLog` lives in `loans` but is written from every app, and `ApiBudgetGuard` lives in `agents` but is shared. Proposal: move the audit chain and the API budget into a `platform` app, and enforce the layering with import-linter in CI. Benefit: apps can be tested alone and patch targets stop being fragile. Cost: one large mechanical PR plus migration care for `AuditLog` (a table rename, or `db_table` kept as-is).
- **ML scoring on the IO queue.** XGBoost and DiCE run inside the orchestrator on the `agents` queue (concurrency 4). At minimum, record this in ADR 007. The real fix is a dedicated pipeline worker with memory limits.

## Simplify pass

Four reviewers looked at each branch's diff from four angles: reuse, simplification, efficiency, and altitude (whether a fix sits at the right depth). Their findings were applied on the branches:

- **Real defects found during the pass and fixed with a test first:**
  - Offers subtracted HECS from surplus while underwriting does not.
  - The staff edit page sent `null` for a cleared NOT NULL field.
  - The review resume sent a replacement email that was still moderately flagged.
  - The email dedup lock could expire during a rate-limit retry.
  - Sentry still received query strings, cookies, auth headers, and PII in log, breadcrumb and exception messages.
  - The human-review service wrote status changes through an application row it had not locked.
- **Shared mechanisms instead of copies:**
  - one `screen_bias` and `bias_failure_mode()`;
  - one `task_dedup_lock`;
  - one "latest run" rule on `AgentRunQuerySet`;
  - one audited `release_queue_failed`;
  - one `AWAITING_PIPELINE_STATUSES`;
  - one `assert_independent_reviewer`;
  - shared `marginal_tax` and `apply_tenure_shading` for both lending engines;
  - one champion ordering;
  - one `redact_pii` for logs and Sentry.
- **Smaller code:**
  - `issue_decision_email` (no callers) and a pass-through wrapper deleted;
  - a separate `CustomerLoanApplication` type, so staff views keep numeric types;
  - a per-request `expectNotFound` flag instead of muting every GET 404;
  - `TEST_REQUEST_DEFAULT_FORMAT = "json"` instead of 33 per-call edits;
  - a lazy dummy password hash;
  - parametrised and shared test helpers.

Left for later (noted by the reviewers, larger than a cleanup):
- normalise blank profile values on the server instead of the frontend field lists;
- a custom `ModelBackend` subclass that would own lockout and the timing equaliser;
- a typed decline-codes field on `LoanDecision` and a `customer_reason` on `PolicyRuleSpec`;
- a `decided_by` FK on `LoanDecision`;
- one definition of "champion" for `validate_model` and the dashboards (they still differ on traffic-zero models).

## Merging this stack

The PRs form a tree rooted on #268, which itself sits on #267 (into `master`):

- #280 (integration of the open leaves) → #281 (2FA removal)
- On #281: #283 (frontend), #284 (auth), #285 (architecture), #287 (pipeline)
- On #287: #288 (governance)

Draft #286 merges all of them together and is the CI signal for the combined code. CI only runs on PRs into `master`, so the stacked PRs show no checks of their own. Close #286 once the stack lands.

One known textual conflict: #285 and #288 both edit the import block of `backend/apps/loans/views.py`. Keep both imports, `from apps.common.http import client_ip` and `from apps.ml_engine.services.model_selector import monitoring_model_version`. `ModelVersion` is no longer used there.

Migrations added: `accounts/0012_drop_otp_tables`, `accounts/0013_customuser_last_failed_login_at`, `loans/0027_auditlog_user_protect`.
