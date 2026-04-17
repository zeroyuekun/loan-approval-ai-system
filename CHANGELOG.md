# Changelog

## v1.9.6 — Workstream B (partial): Throttle & Version Fixes (2026-04-18)

### Security

- Scoped throttle on `ComplaintViewSet.create` — `ComplaintFilingThrottle` (`complaint_filing` scope, 10/hour per user). Complaint filing was previously governed only by the default 60/min user throttle, which left the endpoint open to spam and potentially abusive complaint floods. List/retrieve paths are unaffected.
- Scoped throttle on `CustomerDataExportView` — `DataExportThrottle` (`data_export` scope, 10/hour per user). Privacy Act APP-12 self-service export is inherently low-frequency; the view also performs a heavy `prefetch_related` across loans, decisions, emails, agent runs, bias reports, and marketing emails, so a tight cap is a modest hardening against accidental or deliberate resource exhaustion.
- Three new tests in `backend/tests/test_security_throttles.py` assert 10 successful calls then 429 on the 11th, and that the filing cap does not affect complaint list access.

### Housekeeping

- Bumped `APP_VERSION` in `backend/config/settings/base.py` from `1.8.1` → `1.9.6` (was stale since v1.8.2). Surfaces in `/api/v1/health/` output.

Deferred to future sweeps: CSP `REPORT_ONLY` → enforce (needs prod-report review first), `CustomerDataExportView` field allowlist (current reflective `_meta.get_fields()` is APP-12-safe but fragile).

## v1.9.5 — Workstream D: Dead-Code Cleanup (2026-04-18)

### Housekeeping

- Removed 8 unused frontend components (608 lines) confirmed orphaned via `knip` + manual import grep. None were referenced by pages, tests, or docs.
  - `components/agents/PipelineSummaryBar.tsx`, `components/agents/StepLatencyChart.tsx` (superseded by PR #75 agents-UI removal).
  - `components/applications/CustomerDenialExplanation.tsx` (replaced by `components/loans/DenialExplanation.tsx`).
  - `components/dashboard/ApprovalTrendChart.tsx`, `components/dashboard/PipelineStats.tsx` (dashboard redesign left them stranded).
  - `components/layout/ComplianceFooter.tsx` (compliance moved into page-level disclosures).
  - `components/metrics/DriftFeatureTable.tsx`, `components/metrics/ModelComparison.tsx` (model-metrics page re-implemented inline).
- Dropped `@types/dompurify` from `frontend/package.json` — `dompurify` 3.x ships its own type definitions at `dist/purify.cjs.d.ts`, so the external types package is a no-op.
- Minor lint fix in `loadtests/locustfile.py`: removed unused `resp = ` assignment in `ApplicantUser.create_application`.

No behaviour change; `npm run build`, `tsc --noEmit`, and backend pytest suite remain green.

## v1.9.4 — Security & Reliability Follow-ups (2026-04-18)

### Security

- Validate complaint ownership on create. `ComplaintSerializer` now rejects (400) a complaint whose `loan_application` belongs to another customer; staff (`admin`/`officer`) may still file on behalf of customers, which is recorded as `details.on_behalf_of_id` on the new `complaint_filed` audit entry. Addresses Codex adversarial review finding #3 (second pass).

### Reliability

- Hard-cap batch orchestration default path at 100 applications (was unbounded). The `recheck=true` path already had the cap; the default `POST /api/v1/agents/orchestrate-all/` now applies the same limit, orders oldest-first, and reports `skipped` + a drain-hint `detail` when the backlog exceeds the cap. The `batch_pipeline_triggered` audit entry gains a `skipped_count` field. Addresses Codex adversarial review finding #2 (second pass).

## v1.9.3 — Security & Reliability Hardening (2026-04-18)

### Security

- Enforce Django CSRF validation on cookie-based JWT authentication. Mutating requests authenticated via the `access_token` HttpOnly cookie now require a matching `X-CSRFToken` header. Bearer-header auth is unchanged. Addresses Codex adversarial review finding #1.
- Gate `/metrics` and deep-health behind auth. `/metrics` now requires staff session or `X-Health-Token` header (previously unauthenticated). Removed `/metrics` from the public Kubernetes ingress — still reachable on the internal network for Prometheus. `deep_health_check` refuses to respond (503) in non-DEBUG environments when `HEALTH_CHECK_TOKEN` is unset, so production won't silently leak diagnostics. Prometheus scrape config carries the token via `http_headers`. Addresses Codex adversarial review finding #2.

### Reliability

- Orchestrate endpoint is now idempotent by default. The non-force path short-circuits when a completed `AgentRun` exists and returns the existing run ID instead of dispatching. `force=true` requires `admin`/`officer` role AND a non-empty `reason` query/body param; writes an `AuditLog(action="pipeline_force_rerun")` entry before dispatch so every force rerun is traceable to a named user and a reason. Frontend drops the unconditional `?force=true` from `orchestrate()` and exposes a separate `useForceRerun` hook wired into the staff-only human-review page behind a reason-collecting dialog. Addresses Codex adversarial review finding #3.
- Submission-path durability: loan `perform_create` now dispatches `orchestrate_pipeline_task` under `transaction.on_commit`, and a broker outage no longer swallows submissions. Failed dispatches land in a new `PipelineDispatchOutbox` table and the loan transitions to `status=queue_failed`. A Celery beat task `retry_failed_dispatches` drains the outbox every 60s with a 5-attempt cap; exhausted rows surface in the admin. Addresses Codex adversarial review finding #4.

## 1.9.2 — 2026-04-18

Email aesthetic v2 redesign — 6-PR stack (#69–#74) rebuilt approval, denial, and marketing emails as Gmail-safe HTML with proper visual hierarchy, while preserving the plain-text-first pipeline and existing compliant content (Sarah Mitchell tone, Banking Code alignment, apology-free denial wording).

- **PR #69** — Shared `html_renderer.py` with design tokens (brand colors, type scale, spacing), inline CSS, 600px max-width, `<table role="presentation">` skeleton. Pure-Python renderer drives both the dashboard preview and the Gmail recipient view.
- **PR #70** — TypeScript port at `frontend/src/lib/emailHtmlRenderer.ts` with mirrored tokens. Byte-for-byte parity between Python and TypeScript snapshots enforced by a new CI gate (`.github/workflows/email-parity.yml`), so the preview cannot drift from what Gmail renders.
- **PR #71** — Approval-specific blocks: success hero with loan-type line, loan-details card with `SUCCESS`-colored left border, next-steps pill rows, CTA button, attachments chips, signature block.
- **PR #72** — Denial-specific blocks: caution hero, assessment-factors card (plain-English factor list), what-you-can-do card, free credit report card, dual CTA (call Sarah + email). No apology language.
- **PR #73** — Marketing offer cards with `MARKETING`-colored left border, 11px uppercase label, 17px title, bulleted benefits, italic "why it fits" line. Mandatory unsubscribe footer (Spam Act 2003), conditional FCS disclaimer when body mentions term deposits, conditional bonus-rate disclaimer.
- **PR #74** — Playwright visual regression via `page.setContent()` on the shared HTML snapshots (no backend/dashboard dependency), plus 7 Gmail-safe lint tests (`<td>` margin ban, https/tel/mailto only, zero `<img>`, CTA contrast, no `javascript:` URLs, no Outlook conditional comments, `role="presentation"` on all tables). Pixel screenshots are opt-in via `PLAYWRIGHT_SCREENSHOTS=1`; CI runs cross-platform content assertions.

Design tokens and snapshots are the source of truth — drifting either renderer breaks CI. Unicode icons (✓ ✦ Ⓘ 📎) replace images so Gmail's default image-blocking doesn't degrade the brand.

Post-merge manual Gmail smoke: approval + denial + marketing sent to the dev inbox — all three render with intended hero blocks, cards, and CTAs on Gmail web.

## 1.9.1 — 2026-04-17

Portfolio-polish pass responding to external Claude review (same day, 9.2/10 baseline). Four atomic PRs landed on `master`.

- **A — DataGenerator post-outcome leak regression test** (#63). Extracted `POST_OUTCOME_FEATURES` frozenset in `apps/ml_engine/services/data_generator.py` and added `test_training_features_exclude_post_outcome_columns` + `test_post_outcome_features_constant_is_not_empty` to fail CI if any post-outcome field joins the training feature set, or if the constant is emptied to vacuously pass.
- **B — Backend test collection + coverage gate bump; frontend multi-metric threshold** (#64). `testpaths = ["tests", "apps"]` in `backend/pyproject.toml` picked up 20 previously-uncollected tests (counterfactual engine, orchestrator CF, CF integration, serializer CF). Coverage 61.35% → 63.98%; `--cov-fail-under` 60 → 63. Frontend vitest now enforces `lines: 65, statements: 65, functions: 75, branches: 75` (previously `lines: 60` only), anchored at the measured floor.
- **C — Stale `feat/*` PR triage** (#1, #3, #4, #5 closed with rationale). Four stale `feat/*` PRs from an older Claude Code session audited; #1 closed ("too large to review as one PR"), #3/#4 closed (base diverged, force-push policy blocked clean rebase), #5 closed (half-finished placeholder per user preference).
- **D — 431-line `ci.yml` split into lint/test/security/build** (#65). Four focused workflows matching concern boundaries. Deploy's `needs:` shrinks to `[docker-build, dast-scan]` — cross-workflow `needs:` unsupported by GitHub Actions — with branch-protection rules enforcing upstream green. Nine required-status-check job names preserved verbatim; no admin UI action needed.

Response document: `docs/reviews/2026-04-17-v1.9.1-review-response.md`.

Tracked follow-up (not this pass): Coverage phase 2 — targeted tests for `counterfactual_engine` (11%), `marketing_agent` (11%), `next_best_offer` (13%) to push toward the external review's 75% target.

## 1.9.0 — 2026-04-17

Portfolio production-polish pass: 18 tasks across two tiers — governance/operability documentation (Tier A) and latent-bug fixes with regression tests (Tier B). 20 PRs shipped (#15–#48).

**Tier A — portfolio signal & operability**

- P0 cumulative code review published (`docs/reviews/2026-04-17-p0-baseline.md`) with 12 findings triaged into fold-ins, follow-ups, and parking lot.
- Pre-commit hook stack (ruff, bandit, pip-audit, gitleaks) matches the CI gates so contributor laptops and CI can't diverge.
- `pyproject.toml` split from `requirements.txt` — ruff/bandit/pytest config centralised, dev-only deps isolated, Dependabot watches both.
- CODEOWNERS + PR/issue templates enforce review attribution.
- ADR scaffold (`docs/adr/*`) with four initial decisions: Gaussian-copula synthetic data, XGBoost-with-monotonic-constraints over LR, Celery multi-queue topology, Redis-fallback budget guard.
- `README.md` rewritten to surface production signals first (decision latency, fairness-gate budget, bias-detection flow).
- Operational runbooks (`docs/runbooks/*`) for the six most-likely incidents (Redis down, Claude outage, budget exhausted, model drift, pipeline stuck, DAST ZAP alarm).
- SLI/SLO catalogue (`docs/slo.md`) with four production SLOs (pipeline-e2e P95, email-gen error-rate, ml-prediction latency, bias-review TTR) — 4 custom-metric instrumentation gaps self-disclosed as follow-ups.
- Australian compliance doc (`docs/compliance/australia.md`) — NCCP, Privacy Act APP, ASIC RG 209, APRA CPG 235 mapped to controls in code.
- Engineering journal + interview talking-points (`docs/engineering-journal.md`, `docs/interview-talking-points.md`) for hirer walk-throughs.

**Tier B — latent fixes with regression tests**

- **F-01/F-02/F-03** — every `.update(status=...)` bypass of the state machine in `apps/agents/services/*` replaced with `transition_to()` inside the existing atomic block, each with a `details.source` audit tag. Static-guard test fails if the raw pattern reappears.
- **F-04** — `api_budget` Redis-fallback counter is now lock-guarded (`threading.Lock`), and resets on Redis recovery so a transient outage no longer permanently bricks the worker. Regression test hits 1,000 concurrent increments across 16 threads and asserts exact count.
- **F-05** — Celery integration tests now assert the expected exception type per task instead of `result is not None`, so a task stuck in serialisation would actually fail. Uncovered and fixed a latent Postgres locking bug in `human_review_handler.py` (`select_for_update` against a nullable OneToOne LEFT JOIN).
- **B1** — DiCE counterfactual timeout raised from 30s to 120s to match the slow-end search frontier; matches what the notebook-validated experiment actually needs.
- **B2** — Celery `prefetch_multiplier=1` + `acks_late=True` for IO workers — long-running Claude calls no longer starve peer tasks.
- **B2.5** — frontend exit-code 243 fixed (Node heap cap + healthcheck window) — dev-server crash loop on low-memory laptops resolved.

Post-merge follow-ups tracked as GitHub issues: 4 SLO custom-metric instrumentation gaps; F-06 (`dice-ml>=0.11`), F-07 (`on_time_payment_pct` validator), F-08 (`celery.py` settings default), F-09 (Grafana default password); F-10 (email availability probe), F-11 (CI Fernet key), F-12 (bandit severity gate); regression test for `enforce_retention`.

## 1.8.1 — 2026-04-02

Security hardening from code review: restrict ML views to admin/officer, bind monitoring ports to localhost, timing-safe health check tokens, pin Trivy action to commit SHA after supply-chain advisory.

Fixes: Optuna `fit_params` kwarg, LVR interaction magnitude error (`/100`), reject inference clobbering train imputation values, watchdog connection leak, frontend `setTimeout` cleanup.

## 1.8.0 — 2026-04-02

- Optuna Bayesian hyperparameter optimisation replacing RandomizedSearchCV
- 4 new feature interactions (LVR x property growth, deposit x income stability, DTI x rate sensitivity, credit x employment)
- Self-healing watchdog container (stuck task detection, idle DB connection cleanup)
- Trivy container image scanning in CI

## 1.7.0 / 1.7.1 — 2026-04-01

Application state machine, fairness gate (EEOC 80% rule), repayment estimator component, NCCP/AFCA/Privacy disclosures. Sentry error tracking. SA3-level property data. RBA and AIHW benchmark integration.

## 1.6.0 — 2026-03-31

Big data generator overhaul: 65+ features, Gaussian copula correlations, 6 borrower sub-populations, state-specific profiles, macro features (RBA cash rate, unemployment), CDR/Open Banking features, CCR. CalibrationValidator for APRA benchmark comparison.

## 1.5.0 — 2026-03-27

Pipeline auto-completion, champion/challenger model scoring, conformal prediction intervals, stress testing (4 scenarios), counterfactual explanations, PSI drift detection, monotonic constraints.

## 1.4.0 — 2026-03-27

k6 load tests, ModelValidationReport for SR 11-7, data retention lifecycle, `validate_model` management command.

## 1.3.0 — 2026-03-27

TOTP 2FA, soft deletes, Fernet encryption on address/phone/employer, retraining policy field, weekly fairness alerting, Schemathesis contract tests.

## 1.2.0 — 2026-03-26

Docker resource limits, PII masking log filter, model governance fields, credit score disclosure in denial emails.

## 1.1.0 — 2026-03-24

Fraud detection, decision waterfall, conditional approvals, model card generator, field-level encryption with key rotation.

## 1.0.0 — 2026-03-24

Production deployment config (multi-stage Docker, gunicorn), monitoring stack (Prometheus/Grafana/AlertManager), OWASP ZAP DAST in CI, Playwright E2E tests.

## 0.1.0 - 0.5.0 — 2026-03-19 to 2026-03-24

Initial build: XGBoost pipeline with SHAP, synthetic data generator (Gaussian copula), Claude email generation with 10 guardrails, bias detection (regex + LLM), NBO engine, orchestrator, JWT auth with roles, Celery queues, Docker Compose, CI/CD pipeline.
