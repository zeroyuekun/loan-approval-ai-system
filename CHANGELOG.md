# Changelog

## v1.10.0 — XGBoost AU Lender Parity (2026-04-18)

Bundle of 8 deliverables bringing the unified champion XGBoost model to APRA / AU-big-4 production parity, plus a regression-gate JSON file so CI can catch silent metric decay after promotion. Target audit surfaces: APRA CPS 220 model validation, SR 11-7 MRM dossier, APS 112 credit policy overlay, APS 220 referral trail, AFCA 2023 hardship guidance, ASIC RG 209 responsible-lending capture, NCCP Act s.128 unsuitability screen.

### ML / Risk

- **D1 — XGBoost monotone constraints.** `ModelTrainer.build_model()` now sets a `monotone_constraints` tuple aligned to feature index order: `credit_score`, `annual_income`, `employment_length`, `years_in_residence` constrained `+1` (higher input → lower predicted default probability); `debt_to_income`, `num_late_payments`, `num_delinquencies`, `credit_utilization`, `num_hardship_flags`, `loan_amount`, `loan_to_income` constrained `-1` (higher input → higher PD). Remaining features left at `0` (free). Justification table lives in the MRM dossier §4.
- **D2 — Segmented training.** `ModelTrainer` learned to fit per-segment bundles (`home_owner_occupier`, `home_investor`, `personal`, `unified`) against the generator's `purpose`-based product split, with a shared validation split and `SegmentedBundle` accessor so the predictor can route by application intent at inference. Unified remains the live champion while segment-specific challengers accumulate hold-out evidence; promotion gates run per-segment.
- **D3 — Hard credit policy overlay (shadow-mode default).** New `backend/apps/ml_engine/services/credit_policy.py` codifies 12 underwriter rules: P01 `has_bankruptcy`, P02 `has_default_last_2y`, P03 `credit_score<550`, P04 `loan_amount<2000`, P05 `loan_amount>500000`, P06 `age<18`, P07 `debt_to_income>0.8` (hard-fails); P08 `loan_to_income>9x`, P09 `postcode_default_rate>0.10`, P10 `self_employed AND employment_length<1y`, P11 `num_hardship_flags>=1`, P12 TMD-mismatch (refers). Overlay mode is controlled by `CREDIT_POLICY_MODE` env (`off`/`shadow`/`enforce`, default **shadow**) so the first deploy only logs decisions to audit; flip to `enforce` after a shadow-period review.
- **D4 — Risk-based pricing tiers.** New `pricing_engine.py` maps (PD, segment) → `PricingTier` (tier A–D, rate_min/rate_max, rationale) using NAB-aligned bands: personal 7.0–24.0%, home 6.0–9.0%. Segment normalisation handles `home_owner_occupier` / `home_investor` / `owner_occupier` / `investor` / `investment` → `home`; `personal` / `auto` / `education` / `unified` → `personal`. Rejection returns tier `D` with midpoint-safe rationale instead of raising.
- **D5 — KS / PSI / Brier + champion-challenger promotion gate.** `ModelEvaluator.compute_metrics()` now returns KS-statistic, Brier score + Murphy (1973) decomposition (reliability, resolution, uncertainty), PSI against the prior champion's validation bins, and ECE. `model_selector.promote_if_better()` enforces the four-gate contract: AUC regression tolerance 0.02pp, KS tolerance 0.015pp, PSI ≤ 0.25, ECE ≤ 0.05. All metrics persisted on `ModelVersion` for audit.
- **D6 — Referral audit records (bias-queue-safe).** New `LoanApplication.ReferralStatus` choices (`none` / `referred` / `cleared` / `escalated`) + `referral_codes` (JSONList) + `referral_rationale` (JSONDict) fields, populated by `predictor.py` when a policy run returns `refers`. New admin-only `GET /api/loans/referrals/` endpoint supports `?code=P09,P11`, `?status=referred`, `?limit=100` filters. **The bias human-review queue stays bias-only** — referral evidence is a separate admin surface with no customer-facing UI.
- **D7 — MRM dossier auto-generation.** New `mrm_dossier.py` produces the 11-section APRA/SR 11-7 model-risk-management dossier as pure Markdown (`generate_dossier_markdown(mv) -> str`, `write_dossier(mv, dir) -> str`) with graceful-degradation text when PSI / fairness / calibration data is missing. A `post_save` signal on `ModelVersion` enqueues `generate_mrm_dossier_task.delay(id)` (Celery, 300s time limit, 1 retry), gated by `MRM_DOSSIER_AUTO_GENERATE` env (default `true`). Broker outage is non-fatal. `python manage.py generate_mrm_dossier <id>` offers an offline regen path. Dossier writes to `<ML_MODELS_DIR>/<id>/mrm.md`.
- **D8 — `predictor.py` cleanup.** Refactored `predict_loan_outcome()` into composed steps (policy overlay resolution → PD inference → segment-aware pricing → referral-audit capture → rationale assembly) and pushed Claude / SHAP / policy-code rendering into a single structured-logging surface. Reduces cyclomatic complexity on the critical inference path and tightens the contract around `PolicyResult.rationale_by_code`.

### CI / Audit

- **Regression-gate baseline (`backend/ml_models/golden_metrics.json`).** Captures the champion v1.9.9 floor: AUC 0.87, KS 0.45, Brier 0.10, ECE 0.03, Gini 0.74. Tolerances: AUC drop ≤ 0.02pp, KS drop ≤ 0.015pp, Brier rise ≤ 0.02pp, ECE rise ≤ 0.015pp. Refresh only on new-champion promotion.
- **Regression-gate service (`backend/apps/ml_engine/services/regression_gate.py`).** Pure-functional `check_regression(metrics, golden) -> List[str]` (empty list = pass) + `load_golden()` + `active_model_metrics()` (returns `None` when no active model, so a fresh clone CI stays green). Complements the runtime champion-challenger gate in `model_selector.py` — the runtime gate blocks promotion; this static file catches drift on the *currently-active* model from a nightly CI cron.
- **Regression-gate tests (`backend/apps/ml_engine/tests/test_regression_gate.py`).** 16 tests covering golden-file shape, required baselines + tolerances, higher-is-better drops, lower-is-better rises, compound breaches, missing-metric / non-numeric graceful skipping, and a `@pytest.mark.django_db` integration test that skips-if-no-active-model.

### Migration note

No data migration beyond additive fields on `LoanApplication` (0023). Existing trained models continue to score. To pick up the monotone / segmented / calibrated champion, retrain via Admin → *Train New Model* or `python manage.py train_ml_model`; the promotion gate will block a silently-regressed bundle from becoming active.

### Target

`v1.10.0` lands the XGBoost-parity arm of the Arm A / Arm B / Arm C portfolio-polish push. Arm B (stress-test / soak / fairness uplift) and Arm C (ml_engine code-review sweep) follow as separate specs.

## v1.9.9 — Expose HEM + LMI policy variables as model features (2026-04-18)

### ML

- Promoted four underwriter-internal variables to first-class model features so the scorecard can learn the same HEM-floor and LMI-capitalisation policies the underwriter enforces at decision time, instead of implicitly re-deriving them from raw inputs:
  - `hem_benchmark` — Household Expenditure Measure lookup for the applicant's family structure / income tier (matches the underwriter's `get_hem()` call used when computing `effective_expenses`).
  - `hem_gap` — declared `monthly_expenses` minus `hem_benchmark`. Positive values = applicant's declared spend already clears the HEM floor; negative values = HEM floor bites in serviceability.
  - `lmi_premium` — capitalised Lenders Mortgage Insurance premium (0 for non-home loans, tiered 1%/2%/3% at LVR 80/85/90% thresholds, matching AU market rate cards).
  - `effective_loan_amount` — `loan_amount + lmi_premium` (mirrors `UnderwritingEngine._compute_effective_loan_amount`).
- `ModelTrainer.NUMERIC_COLS` extended in `backend/apps/ml_engine/services/trainer.py`. `feature_engineering.DEFAULT_IMPUTATION_VALUES` gains safe defaults so historical rows fit cleanly. `ModelPredictor` now derives these at inference by calling `UnderwritingEngine.get_hem()` (with a 2950.0 fallback) and applying the LVR-tier LMI schedule — same logic as the generator.
- New `TestUnderwriterPolicyFeatures` test class in `backend/tests/test_data_generator.py` locks the realism contract: HEM increases with dependants, HEM gap = expenses − benchmark, LMI is zero for personal/car/business loans and for LVR ≤ 80%, LMI is charged on >85% LVR home loans, `effective_loan_amount = loan_amount + lmi_premium`.
- `test_feature_consistency.TestFeatureAlignment.test_trainer_features_in_generated_data` now covers the four new columns against the generated dataframe automatically.

### Migration note

Existing trained models are unaffected (feature set stored inside the bundle). To pick up the new signal, run **Train New Model** in Admin so a fresh bundle is fit with the expanded `NUMERIC_COLS`.

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
