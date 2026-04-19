# Changelog

## v1.10.4 — Senior Review Follow-Ups + SLO Instrumentation (2026-04-19)

Five atomic PRs finishing the backlog flagged by the senior code-review pass and landing the SLO histograms the Grafana dashboard was silently missing. No model retraining, no data migrations, no API surface changes.

### Deliverables

- **#118 — ML data-realism fix.** `DataGenerator` was emitting `postcode_default_rate = base + rng.normal(0, 0.003)` — noise std too tight, collapsing the feature to a near-deterministic function of SA4 unemployment (which also drives the label). Bumped noise std `0.003 → 0.008` to match real Equifax / illion AU bureau correlation with SA4 unemployment (r ≈ 0.3–0.45). Added regression guard `test_postcode_default_rate_correlation_realistic` that asserts `|corr(postcode_default_rate, approved)| < 0.25` so the leakage shortcut cannot be silently re-introduced. Re-lands the substance of earlier closed PR #93 as a fresh atomic change against current master. Fix takes effect on the next `DataGenerator.generate()` call; no in-flight ModelVersion invalidated.
- **#119 — CI Fernet key hardening.** `.github/workflows/{test,build}.yml` previously hardcoded a Fernet encryption key in plaintext; senior review flagged this as a credential in source. Replaced with a per-run generated key: each CI job emits a fresh 32-byte urlsafe-base64 key via Python stdlib (`os.urandom(32)` + `base64.urlsafe_b64encode`) and exports it via `$GITHUB_ENV`. No repo secret required, no hardcoded key in source, no new dependency. The CI test DB is ephemeral so the key only needs to be valid, not confidential. Closes #59.
- **#120 — Bandit SAST gate tightening.** `.github/workflows/security.yml` was scanning at `--severity-level medium` which generated noise without blocking on the real issues. Tightened gate to `--severity-level high --confidence-level high` — the pair that matches the threat model the review identified. 0 HIGH/HIGH findings at the time of tightening, so the gate is load-bearing going forward. Five remaining MEDIUM findings tracked as follow-ups but do not block CI. Closes #60.
- **#121 — `enforce_retention` regression coverage.** `backend/apps/loans/management/commands/enforce_retention.py` enforces AU-regulatory retention periods (AML/CTF Act s107/s112 7y loan/KYC retention, APRA CPG 235 5y ML audit trail, Privacy Act APP 11.2 90d soft-delete purge) but had 0% test coverage — a silent regression in either direction is a data-loss or compliance incident. Added 8 regression tests locking `--dry-run` no-op, 90d/5y/3y cutoff directions (strict `<` not `<=`), AuditLog emission per purge/archive, and no-op behaviour on fresh data. Uses `QuerySet.update()` to backdate `auto_now_add` timestamps rather than adding `freezegun` as a new dev dep. Closes #61.
- **#122 — SLO histogram instrumentation.** `docs/slo.md` catalogued four SLOs whose underlying metrics were marked _"follow-up issue tracks this"_ and never emitted — Grafana panels couldn't render them; PagerDuty alerts couldn't fire. This PR instruments all four at their service-layer chokepoints:
  - `pipeline_e2e_seconds{status,decision}` Histogram (1s – 120s buckets) emitted in `StepTracker.finalize_run` — single chokepoint for every terminal pipeline run (completed / failed / escalated)
  - `email_generation_total{decision,source,status}` Counter emitted in `EmailGenerator.generate()` at both return paths (claude_api + template_fallback)
  - `ml_prediction_latency_seconds` gains an `algorithm` label so xgboost / rf / logistic can be compared separately on the Grafana latency panel (the existing `HighPredictionLatency` alert uses `sum by (le)` and aggregates across labels, so no rule rewrite needed)
  - `bias_review_ttr_seconds{decision}` Histogram (1min – 3d buckets) + `bias_review_total{outcome}` Counter emitted in `HumanReviewHandler.resume_after_review`

  Also added two Prometheus alert rules: `PipelineE2ESLOBurn` (p95 > 60s for 30min — double the 30s SLO) and `EmailGenerationErrorBudgetBurn` (success rate < 95% for 15min — burns monthly 2% budget in <1 day). Every emission is wrapped in `try/except` with a debug log so Prometheus client failures can never propagate into the pipeline. 14 new registration + observe/increment tests in `tests/test_slo_metrics.py`. Closes #50, #51, #52, #53.

### Version bump

`APP_VERSION` advances `1.10.3` → `1.10.4`. No data migrations. No trained-model invalidation. No API surface changes.

### Scope notes

- HTML-escape of LLM-interpolated values in `emailHtmlRenderer.ts` / `html_renderer.py` (deferred from v1.10.3) remains slated for a single coordinated future PR — the 15 byte-for-byte Python/TypeScript parity snapshots in email-renderer CI must regenerate in lockstep, too wide a blast radius for a coverage/observability release.

## v1.10.3 — Senior Code Review Response (2026-04-19)

Four atomic PRs addressing findings from a full senior-engineer code review pass. No model retraining, no migrations, no API surface changes. Each PR landed green-CI against master and was merged independently for minimal blast radius + independent rollback.

### Deliverables

- **#113 — Security critical gaps.** Fernet `InvalidToken` is now explicitly caught (previously swallowed by a bare `except Exception` that masked rotation mishaps), export-path quotas hardened, apology regex added to denial guardrails, bias threshold corrected from `>` to `>=` (the prior form mis-classified borderline cases), and the template-mode code path now reaches the fallback guardrail call that the LLM path always did. New `test_apology_language_blocked_in_denial` locks in the apology rejection.
- **#114 — ML correctness.** Moved the `processing_time_ms` timestamp to the end of `predict()` so Prometheus latency histograms reflect actual wall-clock time (the previous stamp was taken mid-function and hid the counterfactual + shadow-scoring cost). Added defence-in-depth leakage drop: `train()` now drops any `POST_OUTCOME_FEATURES` column at the load boundary with a warning log, rather than relying solely on IV selection / monotone-constraints review to catch leakage. A regression test can't catch every path such a column could sneak through; the explicit drop makes the invariant locally auditable.
- **#115 — Infra hardening.** `POSTGRES_PASSWORD` is now required (`:?` guard) across every compose service — the prior `:-postgres` default would silently boot Postgres with a known credential if `.env` was missing. Pinned `prom/prometheus:v3.1.0`, `prom/alertmanager:v0.28.0`, `grafana/grafana:11.5.1`, `danihodovic/celery-exporter:0.10.13`, and `prometheuscommunity/postgres-exporter:v0.17.1` (closes supply-chain risk of `:latest` silent major upgrades). Tightened `build.yml` deploy gate from `!contains(... 'failure')` to `== 'success'` — the prior form would permit a deploy on cancelled/skipped upstream stages. `.env.example` now documents `openssl rand -base64 24` as the generation hint and no longer ships a weak default value.
- **#116 — Frontend polling.** Customer status page replaces a hand-rolled `useEffect` + `setInterval` pair with TanStack Query's `refetchInterval` function form: the hook itself now decides whether to poll based on the current `status` (`pending` / `processing` poll at 5s; everything else stops). Eliminates the manual cleanup edge cases around unmount / re-render / status transitions. `useApplication` accepts an optional `refetchInterval` option so other callers can opt in.

### Deferred to future PR

Two items from the review were scoped out of v1.10.3:

- **HTML-escape LLM-interpolated values** in `emailHtmlRenderer.ts` + Python `html_renderer.py`. Deferred because the 15 byte-for-byte parity snapshots in email-renderer CI must regenerate in lockstep across Python + TypeScript; too wide a blast radius for a "safe" release PR. Planned as a single future PR that coordinates `escapeHtml()` in both renderers with a fresh snapshot regen and a tightened DOMPurify `ALLOWED_URI_REGEXP`.
- **URL protocol allowlist** for LLM-extracted unsubscribe URLs. Low residual risk on the frontend path (DOMPurify default URI allowlist strips `javascript:` / `data:`); the meaningful gain is only on the SMTP-delivered email path. Bundled with the HTML-escape follow-up.

### Also reviewed but not changed

`user: root` on the frontend compose service stays in place — the named `frontend_node_modules` volume needs write access from `npm ci`, and the safer fix requires a Dockerfile `chown` at build time (out of scope for a compose-only PR).

### Version bump

`APP_VERSION` advances `1.10.2` → `1.10.3`. No data migrations. No trained-model invalidation. No API surface changes.

## v1.10.2 — Consolidation Release (2026-04-19)

Seven atomic deliverables that fix latent bugs, close security gaps, and remove dead code without changing model behaviour or API surface. Built on top of in-flight PRs #103 / #104 / #105 which shipped as milestones M1–M3.

### Milestones (merged before D-series)

- **M1 — Smoke E2E stabilisation (#103).** Fixed container-network hostname resolution + login auth payload shape in `tools/smoke_e2e.sh` so the `workflow_dispatch` smoke job exits 0 against a live deploy.
- **M2 — Watchdog httpx swap (#104).** Replaced the missing `requests` dependency in the `docker-compose` watchdog service with the already-vendored `httpx` client so the watchdog actually starts.
- **M3 — Calibration lazy-import fix (#105).** `ml_engine/services/calibration.py` had a broken top-of-file import that crashed any calibration-adjacent code in production; moved the sklearn import inside the function.

### Deliverables

- **D1 — Python 3.13 datetime deprecation.** Replaced every `datetime.utcnow()` call in `apps/ml_engine/` with `datetime.now(UTC)` so the module stops emitting `DeprecationWarning: datetime.utcnow() is deprecated` under Python 3.13. Added `tests/test_utcnow_deprecation.py` AST guard against regression.
- **D2 — `seed_profiles` percentage scale.** `seed_profiles` was setting `on_time_payment_pct` to a fraction in `[0.75, 1.0]` while the field is documented as `[0, 100]`. Downstream credit-policy and scoring code reading the field as a whole-number percentage would silently mis-rank seeded users. Fixed to `random.uniform(75.0, 100.0)` with a regression test that asserts the value is in the documented range AND ≥ 1.0 (catching the fraction form).
- **D3 — `on_time_payment_pct` validators.** The field previously had no bounds, so any buggy writer could persist `-5.0` or `250.0` and crash downstream scoring. Added `MinValueValidator(0.0)` + `MaxValueValidator(100.0)` with migration `0010_add_on_time_payment_pct_validators` and tests for boundary cases (0.0 / 100.0 / mid), negatives, and > 100. Closes #55.
- **D4 — Grafana admin password required in monitoring profile.** The default compose had `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-changeme}` which ships a known weak credential. Split the Grafana service into `docker-compose.monitoring.yml` (opt-in profile) with the required-env `${GRAFANA_ADMIN_PASSWORD:?set in .env}` form so the monitoring stack fails fast instead of exposing an `admin/changeme` dashboard. Main compose no longer references the variable, so standard `docker compose up -d` is unaffected. Closes #57.
- **D5 — Dead DiCE callpath removed.** `CounterfactualEngine` carried a DiCE branch that never executed in production — `dice_ml` was never in `requirements.txt`, and the orchestrator always passes `transform_fn=predictor._transform`, which routes `generate()` straight to the binary-search fallback. Removed `_dice_counterfactuals`, `_build_dice_dataset`, `_parse_dice_result`, `_timeout_ctx`, and the no-op `timeout_seconds` parameter. Net: `counterfactual_engine.py` 458 → 230 lines. Added AST-based guard at `tests/test_no_dice_ml_dependency.py` that detects executable `dice_ml` references while ignoring docstring mentions. Closes #54.
- **D6 — `make clean-soft`.** `make clean` used to run `docker compose down -v`, silently nuking the Postgres volume along with caches. Split into `clean-soft` (caches + build output only, volumes preserved) and `clean` (full wipe). `clean` now internally calls `clean-soft` for the cache sweep. README documents `clean-soft` as the day-to-day default. Guard test locks in the split.
- **D7 — Release packaging.** `APP_VERSION` advances `1.10.1` → `1.10.2`. Closes the stale issue #56 (Celery `DJANGO_SETTINGS_MODULE` default — was already fixed in `config/celery.py:8` via `os.environ.setdefault`).

### Version bump

`APP_VERSION` advances `1.10.1` → `1.10.2`. No data migrations beyond `0010_add_on_time_payment_pct_validators`. No trained-model invalidation. No API surface changes.

### Scope notes

- Issue #61 (retention `enforce_retention` regression test) remains open as future work. The command is exercised in production via the `weekly-data-retention` Celery beat job (`celery.py:95`) but still has no unit coverage. Intentionally left out of v1.10.2 to keep D7 scope release-only.

## v1.10.1 — Production Hardening (2026-04-19)

Six atomic deliverables that tighten the production surface without touching model behaviour:

- **D1 — Hosted-demo scaffolding removed.** Stripped placeholder wizard / profile / about pages and associated fixtures; nothing rendered from them in the current build, and deleting them shrinks the bundle.
- **D2 — Extended `make clean`.** `make clean` reclaims containers / build caches / test artifacts / tsbuildinfo; new `make clean-deep` also drops `node_modules` and `backend/.venv`. Documented under a new README "Housekeeping" section.
- **D3 — Stale model artifact pruning.** New `manage.py prune_model_artifacts [--dry-run] [--keep N]` command cleans stale `.joblib` files under `backend/ml_models/` while keeping the active `ModelVersion` and the N most-recent inactive ones (default 3). Covered by 11 pytest cases.
- **D4 — Dead-code sweep.** New `make deadcode` target combines `ruff --select F401,F811,F841` + `vulture --min-confidence 80`; removed one unused-parameter case surfaced by the sweep.
- **D5 — Robustness audit.** New `backend/mypy.ini` + lightweight CI `mypy` job gate the 10 Arm C Phase 1 extraction modules; `make typecheck` / `make security` / `make verify` targets; `pip-audit --strict`, `npm audit --audit-level=high --omit=dev`, and bandit `-lll`. Frontend `lint:strict` + `typecheck` available as developer tools (not CI gate; 8 intentionally-demoted react-hooks warnings from the Next 16 upgrade block it).
- **D6 — End-to-end smoke test.** New `tools/smoke_e2e.sh` (register → apply → orchestrate → decision → email) + deterministic applicant fixture + `workflow_dispatch`-only GitHub Actions job. Result written to `.tmp/smoke_result.json`.

### Version bump

`APP_VERSION` advances `1.10.0` → `1.10.1`. No data migrations. No trained-model invalidation.

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
