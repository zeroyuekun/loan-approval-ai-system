# Changelog

All notable changes to this project are documented here, in reverse chronological order. This log is intended to show the progression of the project — from initial scaffold to a production-grade system — for anyone reviewing the engineering work.

---

## 2026-04-02 — Optuna Bayesian Optimization, Self-Healing Watchdog, Security Hardening, and Code Review Fixes (v1.8.0)

**Goal:** Replace the brute-force hyperparameter search with Bayesian optimization, add a self-healing watchdog for production resilience, fix all findings from a 3-agent code review (security, frontend quality, ML pipeline), and add research-backed feature interactions.

### Why these changes were needed

The XGBoost hyperparameter search was using `RandomizedSearchCV` with 90 random combinations — a lottery approach that often misses optimal regions of the search space. Optuna's TPE (Tree-structured Parzen Estimator) sampler uses Bayesian optimization to intelligently explore the hyperparameter space, converging on good configurations 10x faster. This is the standard approach in production credit risk modeling (see: Probst et al., 2019; Shwartz-Ziv & Armon, 2022).

The system had no automated recovery from common production failures: stuck Celery tasks, unhealthy services, or idle database connections accumulating. A self-healing watchdog running as a Docker sidecar monitors health every 30 seconds and automatically remediates issues before they cascade.

A 3-agent code review (backend security, frontend quality, ML pipeline) found 24 issues — 6 critical, 18 high. The most impactful were: an unauthenticated deep health check leaking infrastructure details, 6 training features never provided at inference (causing systematic scoring bias), imputation values contaminated by test data before model serialization, and a regex bug causing non-deterministic rendering in the email preview.

### Backend changes

**Optuna Bayesian optimization (`trainer.py`)**
- Replaced `RandomizedSearchCV` with `optuna.create_study(direction="maximize", sampler=TPESampler(seed=42))`
- Configurable trial count via `settings.ML_OPTUNA_TRIALS` (default 50)
- Wider search space: `max_depth` 4–10, `learning_rate` 0.01–0.15 (log-uniform), `reg_lambda` 1–50 (log), plus `reg_alpha` and `gamma`
- AUC-ROC as objective function with 3-fold cross-validation
- Falls back to default XGBoost params if Optuna unavailable

**4 research-backed feature interactions (`feature_engineering.py`)**
- `lvr_x_property_growth`: LVR × property growth — captures negative equity risk when high LVR meets falling property values
- `deposit_x_income_stability`: deposit ratio × salary credit regularity — compounding risk signal
- `dti_x_rate_sensitivity`: DTI × (interest rate / 5.0) — rate exposure for highly leveraged borrowers
- `credit_x_employment`: credit score × employment length — profile strength interaction

**Self-healing watchdog (`management/commands/watchdog.py`)**
- Runs as Docker container polling every 30 seconds
- Health monitor: tracks consecutive failures in Redis, triggers alerts after 3 failures
- Celery healer: detects tasks stuck beyond 2× their time limit, revokes and resets stuck loan applications to "review" status
- DB watchdog: terminates idle connections >10 minutes, warns at 80% connection pool usage
- All actions logged with structured JSON output

**Security fixes (from code review)**
- `/health/deep/` now requires `X-Health-Token` header when `HEALTH_CHECK_TOKEN` env var is set
- Swagger UI restricted to `IsAdminUser` permission
- K8s ConfigMap no longer contains unauthenticated Redis URLs (moved to Secrets)
- `train_model_task` now has `autoretry_for`, `retry_backoff`, `max_retries`, and absolute path default
- `generate_email_task` catches non-retriable exceptions with audit logging
- `.env.example` updated with authenticated Redis URL pattern

**ML pipeline fixes (from code review)**
- Added 6 missing inference features: `hecs_debt_balance`, `existing_property_count`, `cash_advance_count_12m`, `monthly_rent`, `gambling_spend_ratio`, `help_repayment_monthly`
- Fixed imputation leakage: `_train_imputation` snapshot taken after `fit_preprocess`, restored after val/test `transform()` calls
- `MetricsService` moved to `__init__` (was allocating per prediction)
- Trainer/predictor `CATEGORICAL_COLS` synced (8 columns, `sa3_region` excluded due to OHE explosion)

### Frontend changes

**Code quality fixes (from code review)**
- Fixed global regex `g` flag bug in `EmailPreview.tsx` — was causing non-deterministic bold rendering on percentage figures
- Added `componentDidCatch` to `ErrorBoundary` — errors now reported to Sentry with component stack traces
- `WorkflowTimeline` uses `step.step_name` as React key instead of array index
- Replaced all `any` types with proper interfaces (`RegisterPayload`, `LoanPayload`) — zero TypeScript `any` escapes in public contracts
- Exported `RegisterPayload` and `LoanPayload` from `api.ts`

**README recruiter section**
- Added "What to look for" section highlighting key engineering decisions for reviewers

### Files changed
- `backend/apps/ml_engine/services/trainer.py` — Optuna integration, imputation fix
- `backend/apps/ml_engine/services/feature_engineering.py` — 4 feature interactions
- `backend/apps/agents/management/commands/watchdog.py` — new (338 lines)
- `backend/config/urls.py` — health check auth, Swagger restriction
- `backend/config/settings/base.py` — HEALTH_CHECK_TOKEN, ML_OPTUNA_TRIALS
- `backend/apps/ml_engine/services/predictor.py` — 6 missing features, MetricsService init
- `backend/apps/ml_engine/tasks.py` — retry logic, absolute path
- `backend/apps/email_engine/tasks.py` — error handling
- `backend/apps/agents/tasks.py` — noqa fix
- `k8s/configmap.yaml` — removed Redis URLs
- `docker-compose.yml` — watchdog service
- `frontend/src/components/emails/EmailPreview.tsx` — regex fix
- `frontend/src/components/ui/error-boundary.tsx` — componentDidCatch
- `frontend/src/components/agents/WorkflowTimeline.tsx` — React key fix
- `frontend/src/lib/auth.ts`, `api.ts`, `hooks/useApplications.ts` — TypeScript types
- `README.md` — recruiter section
- `CHANGELOG.md` — v1.8.0 entry

---

## 2026-04-02 — Sentry Observability, Data Source Expansion, Version Sync, and Test Fixes

**Goal:** Close the last observability gap by adding Sentry error tracking, expand the real-world data calibration with two new Australian government sources, sync all version strings, and fix the 4 remaining test failures so the entire suite runs green.

### Why these changes were needed

The system had structured JSON logging, Prometheus metrics, PII masking, and correlation ID tracing — but no centralised error tracking. In production lending, silent exceptions in background Celery tasks (model prediction failures, Claude API timeouts, bias detection errors) can go unnoticed for hours. Sentry captures these with full stack traces, breadcrumbs, and user context, surfacing issues before they affect loan decisions.

The `RealWorldBenchmarks` service was already fetching from 11 live sources (ABS income, APRA arrears, RBA lending rates, Equifax credit scores, etc.), but was missing two important benchmarks: RBA Table E2 household debt-to-income ratios (the standard measure of Australian household leverage) and AIHW delinquency benchmarks (an independent secondary source to cross-validate APRA's primary NPL data).

Version strings had drifted — `base.py` said 1.5.0, `package.json` said 1.4.0, commit messages referenced 1.7.0. The predictor was also missing two categorical columns (`sa3_region` and `industry_anzsic`) that the trainer had added, causing 4 test failures that had been masked by running tests selectively.

### Backend changes

**Sentry integration (`config/settings/base.py`)**
- Added `sentry-sdk[django,celery]==2.19.2` to requirements
- Sentry initialises only when `SENTRY_DSN` environment variable is set (no-op in local dev)
- `send_default_pii=False` — critical for a lending platform where request bodies contain income, credit scores, and identity documents
- Django and Celery integrations auto-instrument views, middleware, and background tasks
- 10% trace and profile sample rates (balances observability against Sentry quota)

**RBA Table E2 household debt ratios (`real_world_benchmarks.py`)**
- Added `get_rba_household_debt()` getter with `_fetch_rba_e2_csv()` parser
- Downloads CSV from `rba.gov.au/statistics/tables/csv/e2-data.csv`
- Parses column headers by keyword matching ("housing debt", "income", "assets") — robust against column reordering between quarterly releases
- RBA publishes ratios as percentages (e.g., 99.6 = 99.6%); parser normalises to decimal ratios (0.996) to match the fallback format
- Hardcoded fallback values from Dec Q 2025: housing debt-to-income 1.41, total debt-to-income 1.87, debt-to-assets 0.20
- Added to `get_calibration_snapshot()` so `--use-live-data` includes it automatically

**AIHW cross-validation (`calibration_validator.py`)**
- Added `_AIHW_DELINQUENCY_BENCHMARKS` with mortgage (1.2%) and personal loan (2.5%) delinquency rates from the AIHW Housing Data Dashboard
- Added `validate_against_aihw()` method with 1 percentage point tolerance (wider than APRA's 0.5pp because AIHW aggregates from multiple sources with different reporting dates)
- Integrated into `generate_calibration_report()` — AIHW flags appear in `all_recommendations` when the system's default rate deviates significantly

**Predictor/trainer alignment (`predictor.py`)**
- Added `sa3_region` and `industry_anzsic` to `ModelPredictor.CATEGORICAL_COLS` to match the trainer's 9-column list
- Without this fix, models trained with the new columns would fail validation in `_validate_bundle()` and fall back to the predictor's stale 7-column schema

**Version sync**
- `APP_VERSION` in `base.py`: 1.5.0 → 1.7.0
- `version` in `package.json`: 1.4.0 → 1.7.0

**Test fixes (`test_trainer_pipeline.py`)**
- Numeric column count assertion: 89 → 90 (added `help_repayment_monthly`)
- Categorical column count assertion: 7 → 9 (added `sa3_region`, `industry_anzsic`)
- Result: 993 passed, 0 failed, 36 skipped

### Frontend changes

**Sentry integration**
- Installed `@sentry/nextjs@10.47.0`
- Created `sentry.client.config.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts` — all guarded by `NEXT_PUBLIC_SENTRY_DSN` (no-op when empty)
- Wrapped `next.config.js` with `withSentryConfig()` conditionally — only when DSN is set, so local dev builds are unaffected
- Session replay disabled (cost), error replay at 10%

**Compliance footer removed**
- Removed `<ComplianceFooter />` from login, register, and apply pages
- Component file retained for potential re-use

**CHANGELOG updated**
- Added entries for v1.5.0, v1.6.0, v1.7.0, and v1.7.1 following Keep a Changelog format

### Files changed
- `backend/config/settings/base.py` — Sentry init, version sync
- `backend/requirements.in`, `backend/requirements.txt` — sentry-sdk dependency
- `backend/apps/ml_engine/services/real_world_benchmarks.py` — RBA E2 fetch/parse/fallback
- `backend/apps/ml_engine/services/calibration_validator.py` — AIHW benchmarks and cross-validation
- `backend/apps/ml_engine/services/predictor.py` — CATEGORICAL_COLS alignment
- `backend/tests/test_trainer_pipeline.py` — count assertion fixes
- `frontend/next.config.js` — Sentry wrapper
- `frontend/package.json` — @sentry/nextjs, version sync
- `frontend/sentry.client.config.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts` — new
- `frontend/src/app/(auth)/login/page.tsx`, `register/page.tsx`, `frontend/src/app/apply/layout.tsx` — footer removal
- `.env.example`, `frontend/.env.example` — Sentry DSN placeholders
- `CHANGELOG.md` — v1.5.0 through v1.7.1

---

## 2026-04-01 — State Machine, Fairness Gate, PII Masking, CI Pipeline, and AU Compliance

**Goal:** Enforce valid application lifecycle transitions with a state machine, add a fairness gate to catch demographic bias in model thresholds, mask PII in production logs, build a comprehensive CI/CD pipeline, and add Australian regulatory compliance disclosures.

### Why these changes were needed

Loan applications were transitioning between statuses without validation — an application could jump from "submitted" directly to "denied" without passing through "processing", or be re-processed after already being approved. In regulated lending, the audit trail must show a valid, linear progression. A state machine enforces this at the model level.

The ML predictor was using a single decision threshold (0.5) for all applicants. Under the EEOC's 80% rule (disparate impact theory), if the approval rate for any protected group falls below 80% of the highest group's rate, the model may be discriminatory. Adding group-specific thresholds on employment type (the strongest demographic proxy in the feature set) ensures the system self-corrects before bias compounds.

Production Django logs were capturing full request bodies and error contexts — including customer income, credit scores, and Tax File Numbers. Under the Privacy Act 1988 and APRA CPG 235, PII must not appear in application logs. A masking filter was needed at the logging layer.

The project had tests but no CI pipeline — code could be pushed without running linters, security scans, or tests. A GitHub Actions workflow with 10 parallel jobs provides the safety net.

### Backend changes

**Application state machine**
- Added `status` field with choices: `submitted`, `processing`, `approved`, `denied`, `withdrawn`
- Added `transition_to()` method with valid transition map — raises `ValidationError` on illegal transitions
- Orchestrator pipeline now calls `transition_to("processing")` before starting and `transition_to("approved"/"denied")` on completion

**Fairness gate (`predictor.py`)**
- Added `group_thresholds` dict stored in model bundle — maps employment type to adjusted decision thresholds
- If any group's approval rate falls below 80% of the highest group's rate during training, the threshold for that group is lowered to compensate
- Applied at prediction time: `effective_threshold = group_thresholds.get(employment_type, base_threshold)`

**PII masking (`config/logging_filters.py`)**
- Custom logging filter that redacts: TFN (regex `\d{3}\s?\d{3}\s?\d{3}`), Medicare numbers, email addresses, phone numbers, income/salary amounts, passport and driver licence numbers
- Applied to production logging config in `config/settings/production.py`
- Correlation ID middleware adds a unique request ID to every log entry for tracing

**Repayment estimator**
- Added monthly repayment calculation to prediction response using standard amortisation formula
- Factors in loan amount, interest rate (from RBA F6 live data), and loan term

**AU compliance**
- NCCP Act disclosure: responsible lending obligation notice
- AFCA membership reference with link
- Privacy Policy page stub

**CI pipeline (`.github/workflows/ci.yml`)**
- 10 parallel jobs: backend-test (pytest + 60% coverage), backend-lint (ruff), frontend-lint (eslint + tsc), frontend-test (vitest), security (bandit SAST), dependency-audit (pip-audit + npm audit), secret-scan (gitleaks), docker-build, dast-scan (OWASP ZAP, main only), load-test (k6, main only)
- Deploy job pushes Docker images to GitHub Container Registry

### Frontend changes

**WCAG accessibility**
- Focus ring styles on all interactive elements
- ARIA labels on form inputs, buttons, and navigation
- Skip navigation link for keyboard users

**Repayment estimator component**
- Displays estimated monthly repayment on application detail page
- Positioned above ML decision section for user context

### Files changed
- `backend/apps/loans/models.py` — state machine on LoanApplication
- `backend/apps/ml_engine/services/predictor.py` — fairness gate, group thresholds
- `backend/config/logging_filters.py` — PII masking filter (new)
- `backend/config/middleware.py` — correlation ID middleware
- `backend/config/settings/production.py` — structured JSON logging config
- `.github/workflows/ci.yml` — 10-job CI pipeline (new)
- `frontend/src/components/applications/RepaymentEstimator.tsx` — new
- `frontend/src/app/apply/layout.tsx` — compliance disclosures
- Various sidebar scroll and Docker env fixes

---

## 2026-03-31 — Real-World Australian Lending Calibration (v1.6.0)

**Goal:** Transform the synthetic data generator from a simple random number generator into a statistically credible simulation of Australian lending, calibrated against published government data from ABS, APRA, RBA, and Equifax.

### Why these changes were needed

The original data generator produced ~20 features with uniform or normal distributions and arbitrary ranges. An interviewer or auditor could immediately spot that the data didn't match real Australian lending patterns: income distributions were flat instead of log-normal, LVR (Loan-to-Value Ratio) values didn't cluster around the 80% threshold where LMI kicks in, and default rates were uncorrelated with credit scores.

For a portfolio project targeting Australian fintech roles, the synthetic data needs to be defensible. That means citing real sources (ABS Taxation Statistics, APRA Quarterly ADI Property Exposures, RBA Statistical Tables, Equifax published scorecards) and producing distributions that a lending professional would recognise.

### Backend changes

**Data generator overhaul (`data_generator.py`, ~1800 lines)**
- Expanded from ~20 to 65+ features across 10 feature groups:
  - Core demographics (age, income, employment — log-normal distributions calibrated to ABS/ATO)
  - Loan details (amount, term, purpose — multiplier-based on income per sub-population)
  - Property and home ownership (property value, deposit, existing properties)
  - Credit bureau data (credit score, enquiries, defaults, arrears — Equifax-calibrated)
  - Behavioural/existing customer data (savings, salary regularity, dishonours)
  - Fraud detection signals (2% flagged — income verification gap, document consistency)
  - Open Banking/CDR features (savings trends, discretionary spend, gambling flags)
  - CCR features (late payments, credit utilization, hardship flags)
  - BNPL-specific features (NCCP Act regulation alignment)
  - Macroeconomic context (36-month window: 2023Q3–2026Q2)

**Sub-population mixture model**
- 6 borrower segments with realistic weights: First Home Buyer (15%), Upgrader (20%), Refinancer (10%), Personal Borrower (35%), Business Borrower (12%), Investor (8%)
- Each segment has distinct income, credit score, LVR, and loan multiplier distributions
- Segments produce the bimodal distributions seen in real lending data

**Gaussian copula correlation matrix**
- 8 core features (age, income, credit score, expenses, tenure, CC limit, dependants, employment length) correlated via copula
- Preserves marginal distributions while introducing realistic joint patterns (e.g., income ↔ credit score r=0.30, age ↔ tenure r=0.55)

**State-specific profiles**
- 8 states/territories with calibrated median house prices (CoreLogic Dec 2025), income multipliers (ABS), and credit score adjustments
- NSW: $1.65M median, 1.08x income | TAS: $620K median, 0.88x income | ACT: $950K, 1.25x income

**RealWorldBenchmarks service (`real_world_benchmarks.py`)**
- Fetches distribution-level data from 11 public Australian sources
- ABS Data API (SDMX): income percentiles by state, lending indicators by purpose
- APRA Quarterly ADI Statistics: arrears rates, LVR/DTI band distributions (XLSX parsing)
- RBA Statistical Tables: lending rates (F5, F6 CSV), household debt ratios (E2)
- Equifax: credit score distributions by age bracket (hardcoded from published reports)
- Every method has hardcoded fallback values so generation never breaks if APIs are unreachable
- 7-day cache TTL (data updates quarterly)
- `get_calibration_snapshot()` assembles all benchmarks for `DataGenerator(benchmarks=snapshot)`

**CalibrationValidator (`calibration_validator.py`)**
- Three-way calibration: predicted vs actual default rate (internal), actual vs APRA benchmark (external), combined assessment
- State-level validation against APRA by-state benchmarks
- Portfolio composition check: LVR ≥ 80% share and DTI ≥ 6 share against APRA published figures
- Actionable recommendations with APRA quarter citations

**Measurement noise and missing data**
- Income noise: ±8% (self-reported vs verified)
- Expense under-reporting: 30–50% (known behavioural pattern)
- Credit score drift: ±40 points between bureau pulls
- Missing data: 5–12% across different feature groups
- Thin-file segment: 25% of applicants with < 36 months credit history

### Files changed
- `backend/apps/ml_engine/services/data_generator.py` — complete rewrite (~1800 lines)
- `backend/apps/ml_engine/services/real_world_benchmarks.py` — new (11 data sources)
- `backend/apps/ml_engine/services/calibration_validator.py` — new (APRA validation)
- `backend/apps/ml_engine/services/macro_data_service.py` — RBA cash rate, unemployment, property growth
- `backend/apps/ml_engine/services/feature_engineering.py` — 28 derived features
- `backend/apps/ml_engine/services/property_data_service.py` — SA3-level property data (~50 regions)

---

## 2026-03-27 — Pipeline Auto-Completion, Champion/Challenger, Conformal Prediction, and Testing (v1.4.0–v1.5.0)

**Goal:** Make the orchestrator pipeline run end-to-end in a single invocation (prediction → email → bias detection → NBO), add ML model governance features (champion/challenger scoring, conformal prediction intervals, stress testing, counterfactual explanations), and build a comprehensive test suite with load testing.

### Why these changes were needed

The orchestrator required manual step-by-step triggering — a loan officer had to click "Run Pipeline", then "Generate Email", then "Check Bias" separately. In production, the pipeline should complete autonomously once triggered, with each step feeding into the next.

For ML model governance (APRA CPG 235, SR 11-7), a production system needs more than just a prediction: it needs uncertainty quantification (how confident is the model?), stress testing (what happens under adverse conditions?), counterfactual explanations (what would the applicant need to change?), and challenger model comparison (is a newer model performing better?).

The project also lacked load testing — an interviewer might ask "how many concurrent applications can this handle?" Without benchmarks, there's no answer.

### Backend changes

**Pipeline auto-completion (`orchestrator.py`)**
- Single `orchestrate(application_id)` Celery task chains all steps: prediction → email generation → bias detection → NBO (if denied)
- Each step's output feeds into the next via the `AgentRun` record
- Failure in any step is logged but doesn't block subsequent independent steps

**Champion/challenger scoring (`predictor.py`)**
- Active model (champion) produces the decision
- If a challenger model exists (`ModelVersion` with `is_challenger=True`), it runs a shadow prediction in parallel
- Both scores are logged to `PredictionLog` for offline comparison
- No production impact — challenger score is stored but not used for decisions

**Conformal prediction intervals**
- Split conformal method: calibration set nonconformity scores stored in model bundle
- At inference, produces prediction intervals with guaranteed coverage (default 95%)
- Example: "Approval probability: 0.72, 95% CI: [0.65, 0.79]"

**Stress testing**
- 4 adverse scenarios applied to each prediction:
  1. Income shock: -15%
  2. Property value decline: -20%
  3. Credit score deterioration: -50 points
  4. Combined: all three simultaneously
- Returns probability under each scenario — shows model resilience

**Counterfactual explanations (denials only)**
- For each denied application, finds the top 3 features where the smallest change would flip the decision
- Example: "If annual_income increased from $52,000 to $61,400, the prediction would change to approved"
- Uses feature importance + gradient-based search

**PSI drift detection**
- Population Stability Index computed per feature at prediction time
- Compares incoming application's feature distribution against training data reference
- PSI > 0.1 triggers a warning; PSI > 0.25 triggers a `requires_human_review` flag

**Monotonic constraints**
- All XGBoost features have monotonic constraint direction defined
- Higher income → higher approval probability (positive constraint)
- Higher debt-to-income → lower approval probability (negative constraint)
- Prevents the model from learning spurious non-monotonic relationships

**Testing expansion**
- k6 load test suite with SLA assertions (P95 latency thresholds for health, login, list, pipeline endpoints)
- Schemathesis contract tests against OpenAPI spec
- Frontend component tests: BiasScoreBadge, DecisionSection, EmailPreview, ErrorBoundary, PipelineControls, Sidebar, WorkflowTimeline
- Frontend hook tests: useAgentStatus, useApplicationForm, useApplications, useAuth, useHumanReview, useMetrics, usePipelineOrchestration
- Coverage thresholds enforced: 60% backend, 40% frontend

### Files changed
- `backend/apps/agents/services/orchestrator.py` — pipeline auto-completion
- `backend/apps/ml_engine/services/predictor.py` — champion/challenger, conformal, stress test, counterfactuals, drift, monotonic
- `backend/apps/ml_engine/services/trainer.py` — monotonic constraint definitions, conformal calibration scores
- `.github/workflows/ci.yml` — k6 load test job, security scanning
- `backend/tests/` — expanded to 61 test files
- `frontend/src/__tests__/` — expanded to 31 test files
- `frontend/vitest.config.ts` — coverage thresholds

---

## 2026-03-20 — Customer Profile Flow, Edit Profile, and UI/UX Improvements

**Goal:** Fix the customer-facing loan application flow so customers see empty profile fields (not pre-filled fake data), can complete their own profile including identity documents, and get properly redirected to the loan application. Add a restricted "Edit Profile" page with fraud-prevention field locking, a customer account dropdown menu, Docker live reload, and various UI fixes.

### Why these changes were needed

The `seed_profiles` management command was populating ALL customer profile fields — personal details, identity documents, employment, income, assets — with random data. This meant customers logging in saw someone else's fake data pre-filled in their profile. Worse, the identity fields (DOB, residency, IDs) were marked read-only in the serializer, so customers could never submit their own identity documents through the API. The profile could never be completed by a customer.

The customer experience also had several broken paths: the "Complete Profile" button pointed to a non-existent dashboard route, numeric fields showing `0` appeared as empty due to JavaScript falsy-value bugs, and a stale React Query cache caused the profile to appear incomplete even after saving.

### Backend changes

**Serializer: identity fields made writable for customers**
- Removed `date_of_birth`, `residency_status`, `primary_id_type`, `primary_id_number`, `secondary_id_type`, `secondary_id_number`, `tax_file_number_provided`, and `is_politically_exposed` from `read_only_fields` in `CustomerProfileSerializer`
- These fields are required for the 100-point ID check under AML/CTF Act 2006 — customers must be able to submit them during initial profile completion
- Banking relationship fields (tenure, balances, products) remain read-only

**Seed command: reduced to bank-known data only**
- `seed_profiles` now only populates fields the bank would already have: `account_tenure_years`, `num_products`, `has_credit_card`, `has_mortgage`, `has_auto_loan`, `on_time_payment_pct`, `previous_loans_repaid`, `loyalty_tier`, `savings_balance`, `checking_balance`
- All customer-entered fields (personal, identity, employment, income, assets, liabilities, living situation) are left blank
- Existing seeded profiles were reset in the database

**Profile completeness check: fixed falsy-value bug**
- `is_profile_complete` and `missing_profile_fields` used Python truthiness checks (`all(getattr(self, f) for f in ...)`)
- `number_of_dependants = 0` was treated as "missing" because `0` is falsy
- Fixed to use explicit `val is None or val == ''` checks so `0` is correctly treated as a valid answer

### Frontend changes

**Customer dropdown menu**
- Replaced the bare logout icon in the customer header with a proper dropdown menu
- Shows avatar initial, full name, and email
- Contains "Edit Profile" link and "Sign Out" button
- Follows the same dropdown pattern used in the admin TopNav

**Edit Profile page (`/apply/profile/edit`)**
- New restricted profile editing page accessible from the customer dropdown
- **Locked fields (display only):** Name, email, date of birth, residency status, primary/secondary ID documents — with a notice explaining customers must visit a branch to change these (AML/CTF Act 2006 fraud prevention, consistent with CBA/ANZ/Westpac online banking)
- **Editable fields:** Phone, address, marital status, contact preference, employment, income, assets, liabilities, living situation — life-circumstance fields that Australian banks allow customers to update online
- ID document numbers are masked (show type + "****") in the locked section
- Redirects to `/apply` after saving

**Profile redirect fix**
- Changed the "Go to My Profile" link in `ApplicationForm` from `/dashboard/profile` (didn't exist) to `/apply/profile`

**Falsy-value fixes on profile page**
- Changed `form.number_of_dependants || ''` to `form.number_of_dependants ?? ''` across all numeric fields
- Applied to both the `useEffect` form initialisation and the input `value` props
- `0` now displays correctly instead of showing as empty

**Stale cache fix**
- Profile page now `await`s `queryClient.invalidateQueries` before redirecting to `/apply/new`
- `ApplicationForm` profile query uses `staleTime: 0` to always refetch on mount
- Prevents the race condition where `/apply/new` loaded stale cached profile data showing `is_profile_complete: false`

**Application status page**
- Removed "Back" button
- Added "Finished" button (bottom-right, blue) linking to `/apply`
- Added spacing between the last card and the button

**Incomplete profile warning**
- Removed "Go Back" button from the incomplete profile card in `ApplicationForm`
- Added "Finished" button (bottom-right) linking to `/apply`

**Apply page spacing**
- Added proper spacing between the "Apply Now" button row and application cards
- Removed the `+` icon from the "Apply Now" button

**Customers table**
- Added border between "All Customers" heading and the table

**Model metrics**
- Changed "Active" badge to green (`success` variant)
- Matched badge sizes between version and active badges

### Hydration error fixes

**Badge component (`badge.tsx`)**
- Changed from `<div>` to `<span>` to fix "div cannot be a descendant of p" hydration error

**CardDescription component (`card.tsx`)**
- Changed from `<p>` to `<div>` to fix "p cannot contain a nested div" hydration error
- `CardDescription` was being used with block-level children (badges, flex containers) in `ThresholdChart`

### Infrastructure

**Docker live reload for frontend**
- Added `command: npm run dev` override in `docker-compose.yml` for the frontend service
- Added `WATCHPACK_POLLING: "true"` for Windows Docker file system compatibility
- Mounted `./frontend/public:/app/public` volume
- Changes to `frontend/src/` now hot-reload without requiring container rebuilds

### Files changed
- `backend/apps/accounts/serializers.py` — identity fields writable
- `backend/apps/accounts/models.py` — fixed profile completeness check
- `backend/apps/accounts/management/commands/seed_profiles.py` — bank-known data only
- `frontend/src/app/apply/layout.tsx` — customer dropdown menu
- `frontend/src/app/apply/profile/edit/page.tsx` — new edit profile page
- `frontend/src/app/apply/profile/page.tsx` — falsy-value fixes, cache fix
- `frontend/src/app/apply/page.tsx` — spacing, button cleanup
- `frontend/src/app/apply/status/[id]/page.tsx` — finished button, removed back
- `frontend/src/components/applications/ApplicationForm.tsx` — redirect fix, cache fix, button changes
- `frontend/src/app/dashboard/customers/page.tsx` — table header border
- `frontend/src/app/dashboard/model-metrics/page.tsx` — green active badge, badge sizing
- `frontend/src/components/ui/badge.tsx` — div to span (hydration fix)
- `frontend/src/components/ui/card.tsx` — p to div (hydration fix)
- `docker-compose.yml` — frontend dev mode, live reload

---

## 2026-03-19 — Pipeline Integrity Fixes, Risk Analytics, Feature Interactions, and Self-Healing Validation

**Goal:** Fix 4 critical pipeline contradictions found during a team code review, add Basel III risk analytics (EL = PD x LGD x EAD, stress testing, conformal prediction), feature interaction engineering, credit-score-sensitive LGD, and implement self-healing validation with realistic Australian demo scenarios.

### Why these changes were needed

A 3-agent code review team (credit risk analyst, QA engineer, mortgage broker) audited the full ML pipeline and found that while the model architecture was sound, several components were silently contradicting each other. These weren't accuracy problems — they were correctness problems. The model was producing predictions based on inconsistent assumptions between training and inference.

The risk analytics additions transform the model output from a binary approve/deny into the kind of dollar-value risk assessment that APRA-regulated banks actually use for capital allocation and pricing.

### Critical bug fixes

**C1: Reject inference label removed from training output**
- **What:** The `_reject_inference_label` column (NaN for approved, 0/1 for denied) was persisting in the training CSV. It wasn't entering the model features by coincidence (not listed in `NUMERIC_COLS`), but it was one accidental inclusion away from catastrophic target leakage.
- **Why it matters:** This column is a near-perfect proxy for the target variable. If any automated feature selection tool or future developer included it, the model would achieve 99%+ AUC by cheating — learning "if this column exists, deny" rather than learning actual risk patterns.
- **Fix:** Column stored as instance attribute `self.reject_inference_labels`, dropped from DataFrame before return.

**C2: State field now written to database records**
- **What:** The generator produces state-aware data (8 Australian states with different income/credit/property profiles), and the model trains on it. But `generate_data.py` never passed `state` to `LoanApplication.objects.create()`, so all database records defaulted to NSW.
- **Why it matters:** 67% of production predictions were using the wrong state features. A QLD applicant was being predicted as if they lived in Sydney, with Sydney income expectations and credit score adjustments.
- **Fix:** Added `state=row['state']` to DB creation. Removed silent NSW default in predictor — missing state now raises an error rather than silently defaulting.

**C3: Missing value imputation aligned between trainer and predictor**
- **What:** The trainer imputed missing `monthly_expenses` with the training set median (~$2,500). The predictor imputed with 0 (via `float(application.monthly_expenses or 0)`).
- **Why it matters:** For the ~4% of applications with missing expenses, the predictor fed the model a value (0) that the scaler had never seen during training. The `expense_to_income` derived feature became 0.0, making the model think these applicants spend nothing — and approve them more readily.
- **Fix:** Imputation values stored in the model bundle during training. Predictor loads them and uses the same values.

**C4: WOE scorecard computed on raw data (not scaled)**
- **What:** The WOE/IV analysis was running on StandardScaler-transformed features. Bin edges were in z-score units (e.g., "credit_score between -1.2 and 0.4") instead of real units.
- **Why it matters:** A WOE scorecard must be interpretable — APRA requires that a credit officer can explain every decision. A scorecard with z-score bins fails this requirement. The AUC figure was also misleading because it was computed in-sample.
- **Fix:** WOE computed on raw data before scaling. Bins now in real units (e.g., credit_score 650-750). AUC reported on held-out test set.

### Monotonic constraint corrections

**H1: Removed LVR monotonic constraint**
- **What:** `lvr: -1` (higher LVR = lower approval) was forcing the model to treat all non-home loans (LVR=0.0) as "best possible LVR" — more approvable than any home loan with a deposit.
- **Why:** LVR=0.0 for a personal loan means "no property", not "zero risk". The monotonic constraint was inverting the intended behavior for 52% of the dataset.

**H2: Removed HECS monotonic constraint**
- **What:** `has_hecs: -1` forced HECS to always reduce approval probability. But the actual effect is income-mediated: a $200K earner with HECS repaying $583/month is barely affected; a $50K earner repaying $146/month is significantly affected.
- **Why:** The constraint prevented the model from learning this nuance. High-income HECS holders were being unfairly penalised.

### Risk analytics additions

**Expected Loss (EL = PD x LGD x EAD) — Basel III / APRA APS 113**
- Added LGD lookup table by loan purpose and LVR band (home 15-40%, personal 50-75%, business 80%)
- Credit-score-sensitive LGD: better credit reduces LGD by up to 20% (cooperative recovery), worse credit increases it. Credit score 900 → LGD 0.213 vs credit 600 → LGD 0.227 on same loan.
- EL computed for every prediction: the dollar amount the bank expects to lose
- This transforms the model from binary approve/deny into a dollar-value risk assessment

**Stress Testing — APRA APS 110**
- 4 adverse scenarios: interest rate +2%, income -15%, property value -20%, combined
- Re-runs the prediction under each scenario
- Shows how the approval probability degrades under stress

**Conformal Prediction — confidence intervals**
- Instead of just "72% probability", outputs "72% [65%, 79%] at 95% confidence"
- Uses split conformal prediction with nonconformity scores from calibration set

**Adversarial Validation**
- Trains a classifier to distinguish training from test data
- If AUC > 0.55, flags a distribution mismatch
- Sanity check that runs automatically during training

**Concentration Risk — APRA APS 221**
- HHI (Herfindahl-Hirschman Index) by state, purpose, employment type
- Flags if any segment exceeds 40% of portfolio

### Feature engineering improvements

**4 interaction features (standard in Big 4 scorecards)**
- `lvr_x_dti`: compounding leverage risk — high LVR + high DTI is much riskier than either alone (RBA FSR 2022 finding: borrowers with both high DTI and high LVR were ~4x more likely to report mortgage stress)
- `income_credit_interaction`: joint creditworthiness x capacity signal using log-scaled income x normalised credit score
- `serviceability_ratio`: monthly buffer after all commitments as a ratio — directly models the bank's serviceability assessment
- `employment_stability`: employment type quality (permanent=1.0, casual=0.4) weighted by log tenure — captures that a casual worker with 5 years is very different from a casual with 6 months

**Monotonic constraints updated for interaction features**
- `lvr_x_dti: -1` (compounding leverage always hurts)
- `income_credit_interaction: 1` (higher combined creditworthiness always helps)
- `serviceability_ratio: 1` (more buffer always helps)
- `employment_stability: 1` (more stability always helps)

**Discrete feature WOE binning fix**
- Features with <= 10 unique values (e.g., number_of_dependants with 5 values: 0-4) now bin by unique value instead of quantile
- Prevents degenerate bins where multiple quantile edges collapse to the same value
- Dependants now correctly produces 5 WOE bins (one per value) instead of 2-3 collapsed bins

### Self-healing pipeline validation

Added `validate_pipeline_consistency()` that runs after every training:
- Checks CATEGORICAL_COLS match between trainer and predictor
- Verifies all monotonic constraint features exist in the feature set
- Confirms imputation values are stored in the model bundle
- Detects target-leaking columns in training data
- Raises clear errors listing all failures

### Demo scenarios (6 named Australian applicants)

| # | Name | State | Scenario | Expected |
|---|------|-------|----------|----------|
| 1 | Sarah Chen | NSW | FHB couple, $152K, $680K home loan, HECS | Approved |
| 2 | Liam O'Connor | QLD | Regional upgrader, $185K, $520K loan | Approved |
| 3 | Marco Rossi | VIC | Self-employed tradie, $135K, $620K loan | Borderline |
| 4 | Chloe Martin | VIC | Casual 8mo, $52K, personal loan | Denied (tenure) |
| 5 | Raj Patel | NSW | Investor DTI 6.2, $210K, $1.3M loan | Denied (APRA DTI) |
| 6 | Tom Anderson | SA | Bankruptcy, $78K, personal loan | Denied (bankruptcy) |

### Files changed
- `backend/apps/ml_engine/services/data_generator.py` — drop leak column, copula validation, dead code removal
- `backend/apps/ml_engine/services/trainer.py` — imputation storage, raw WOE, constraints fix, fairness, self-healing
- `backend/apps/ml_engine/services/predictor.py` — state fix, imputation, EL calculation, stress testing, conformal prediction
- `backend/apps/ml_engine/services/metrics.py` — WOE test AUC, PSI epsilon, adversarial validation, concentration risk, EL computation
- `backend/apps/ml_engine/management/commands/generate_data.py` — state in DB, demo scenarios
- `backend/tests/conftest.py` — state in fixtures
- `README.md` — risk analytics documentation, limitations section
- `CHANGES.md` — this entry

---

## 2026-03-19 — WOE Scorecard, Monotonic Constraints, and Reject Inference

**Goal:** Add the three credit risk techniques that real APRA-regulated banks use but most ML projects miss — WOE/IV scorecards for regulatory interpretability, monotonic constraints for domain-consistent predictions, and reject inference to correct for selection bias.

### Why these techniques matter

A recruiter at a bank will look at a loan approval model and ask: "Where's the scorecard?" XGBoost is great for prediction but regulators require interpretability. A credit officer needs to explain to AFCA exactly why someone was denied — "the 247th tree said no" doesn't satisfy the Banking Code of Practice paragraph 81 requirement to provide reasons for denial.

### What changed

**Weight of Evidence (WOE) / Information Value (IV) scorecard**
- WOE transformation: bins each feature and computes log odds ratio per bin — the standard methodology under Basel III / APRA APS 113
- Information Value for automatic feature ranking: IV < 0.02 (drop), 0.02-0.10 (weak), 0.10-0.30 (medium), 0.30-0.50 (strong), > 0.50 (check for leakage)
- Full WOE logistic regression scorecard built alongside XGBoost — base score 600, PDO (Points to Double Odds) 20
- Scorecard can be printed on a single page — a key regulatory requirement for APRA model documentation
- Scorecard AUC ~0.78 (lower than XGBoost's ~0.93, but fully interpretable — this is the tradeoff banks actually make)

**Monotonic constraints on XGBoost**
- 11 domain-enforced monotonic relationships: credit_score (positive), income (positive), DTI (negative), employment_length (positive), bankruptcy (negative), etc.
- Prevents the model from learning spurious non-monotonic patterns from noise
- Regulatory expectation: APRA and ASIC expect that a model won't approve someone with a lower credit score over an identical applicant with a higher score

**Reject inference (parcelling method)**
- In real lending, outcomes are only observed for approved loans — denied applicants never get a chance to prove they'd repay
- The generator uses the parcelling method to estimate hypothetical outcomes for denied applicants
- ~50% of denied applicants estimated as "would have repaid" (consistent with banking literature)

### Files changed
- `backend/apps/ml_engine/services/metrics.py` — `compute_woe_iv`, `compute_all_woe_iv`, `build_woe_scorecard`
- `backend/apps/ml_engine/services/trainer.py` — `_build_monotonic_constraints`, WOE scorecard in training output
- `backend/apps/ml_engine/services/data_generator.py` — reject inference parcelling

---

## 2026-03-19 — Synthetic Data Calibration (Gaussian Copula + Mixture Model + Geographic Segmentation)

**Goal:** Make the synthetic training data statistically realistic by calibrating every distribution parameter against official Australian government and industry statistics, rather than using estimated values.

### Why this matters

Most ML portfolio projects generate synthetic data with guessed distributions, train a model, get 99% accuracy, and call it done. A recruiter who's worked at a bank knows those numbers mean the data was trivial. This project takes a different approach: every parameter is sourced from a published statistic, and the generator uses the same techniques (copula, mixture models) that credit risk teams at Moody's Analytics and the Big 4 banks use for synthetic data generation.

### What changed

**Gaussian copula for correlated feature generation**
- 7x7 correlation matrix calibrated from ATO/ABS/Equifax cross-tabulations
- Income <-> Credit Score: r=0.26, Income <-> Expenses: r=0.34, Age <-> Employment: r=0.19
- Without this, the model trains on artificially independent features — like assuming income has nothing to do with credit score

**Sub-population mixture model with 5 borrower archetypes**
- First home buyers (18%): young, high LVR, moderate income
- Upgraders (20%): mid-career, moderate LVR, excellent credit
- Refinancers (10%): established, low LVR, longest employment
- Personal borrowers (37%): auto/education/personal loans
- Business borrowers (15%): older, self-employed skew

**Geographic segmentation across all 8 Australian states/territories**
- State profiles with income multipliers (WA 1.12x mining, ACT 1.25x public service, TAS 0.88x)
- Equifax credit score adjustments by state (ACT +51, NT -20 from national average)
- State-level validation: ACT highest credit (905), NT lowest (824), matches Equifax 2025

**Calibration against 11 official sources**
- ATO Taxation Statistics 2022-23, ABS Employee Earnings Aug 2025, ABS Characteristics of Employment Aug 2025, ABS Lending Indicators Dec Q 2025, APRA Quarterly ADI Property Exposures Sep Q 2025, Equifax 2025 Credit Scorecard, RBA Financial Stability Review Oct 2025, CoreLogic 2025, ABS Total Value of Dwellings Dec Q 2025, Melbourne Institute HEM 2025/2026, AFSA 2024-25

### Validation results

| Parameter | Before | After | Target | Source |
|-----------|--------|-------|--------|--------|
| Income (single) | $70K est. | $79,821 | $74,100 | ABS 2025 |
| Credit score | ~846 est. | 875 | 864 | Equifax 2025 |
| LVR >= 80% | uncalibrated | 32.1% | 30.8% | APRA Sep Q 2025 |
| Approval rate | uncalibrated | 66.3% | 65-75% | Big 4 banks |
| Employment split | 55/15/20/10% est. | 68/12/12/8% | 68/12/12/8% | ABS 2025 |

### Files changed
- `backend/apps/ml_engine/services/data_generator.py` — major rewrite
- `backend/apps/ml_engine/services/trainer.py` — `state` categorical column
- `backend/apps/ml_engine/services/predictor.py` — `state` in feature dict
- `backend/apps/loans/models.py` — `AustralianState` choices and `state` field
- `backend/apps/loans/serializers.py` — `state` in serializer fields

---

## 2026-03-18 — Banking Metrics, Drift Monitoring, and Fairness Analysis

**Goal:** Add banking-industry-standard model evaluation metrics that go beyond accuracy/F1, implement per-application drift detection, and add fairness metrics with disparate impact analysis.

### Why these metrics matter

A model with 90% accuracy sounds good until you realise it's approving loans that default and denying loans that would have been profitable. Banks don't use accuracy — they use Gini (discrimination power), KS (separation between good and bad), PSI (distribution shift), and calibration (are the probabilities trustworthy). Adding these shows understanding of what matters in production credit risk.

### What changed

**Banking metrics:** Gini coefficient, KS statistic, log loss, ECE (Expected Calibration Error), decile lift analysis, threshold sweep with 3 optimal strategies (F1, Youden's J, cost-matrix with banking 5:1 FP:FN ratio)

**PSI drift monitoring:** Batch PSI comparing training vs production distributions, per-feature PSI to identify which features drifted, APRA CPG 235 thresholds (<0.10 stable, 0.10-0.25 moderate, >=0.25 retrain)

**Per-application drift detection:** Z-score against training distribution, flags at 3σ (warning) and 4σ (drift), triggers human review

**Fairness metrics:** Per-group TPR/FPR, disparate impact ratio, EEOC 80% rule check, equalized odds difference

### Files changed
- `backend/apps/ml_engine/services/metrics.py` — all new metric computations
- `backend/apps/ml_engine/services/predictor.py` — drift detection
- `backend/apps/ml_engine/services/trainer.py` — reference distribution, fairness
- `backend/apps/ml_engine/views.py` — drift monitoring endpoint

---

## 2026-03-17 — Model Training Pipeline Hardening (Calibration, SHAP, Overfitting Detection)

**Goal:** Make the model training pipeline production-grade with probability calibration, per-prediction explainability, and overfitting safeguards.

### Why calibration matters

An XGBoost model might output "0.72 probability of approval" — but that doesn't mean 72 out of 100 applicants with that score actually get approved. Isotonic calibration warps the raw probabilities to match observed frequencies, making the numbers meaningful for risk-based pricing and regulatory reporting.

### What changed

**Isotonic probability calibration:** Custom `_CalibratedModel` wrapper, fitted on held-out validation set (10% of data), 80/10/10 split to prevent leakage

**SHAP feature explanations:** TreeExplainer for per-prediction SHAP values, extracts underlying estimator from calibration wrapper

**XGBoost training improvements:** RandomizedSearchCV (50 iterations), `scale_pos_weight` for class imbalance, early stopping (20 rounds), thread management for oversubscription prevention

**Overfitting detection:** Train vs test AUC comparison, warning if gap > 0.05

**Data consistency checker:** Cross-field validation (deposit vs property value, DTI vs income/loan), blocks predictions on logically inconsistent inputs

**Model security:** SHA-256 hash verification, path traversal protection, thread-safe caching

### Files changed
- `backend/apps/ml_engine/services/trainer.py` — calibration, RandomizedSearchCV, overfitting
- `backend/apps/ml_engine/services/predictor.py` — SHAP, hash verification, caching
- `backend/apps/ml_engine/services/consistency.py` — cross-field validation

---

## 2026-03-16 — Email Guardrails System (10 Deterministic Checks)

**Goal:** Replace the basic email validation with a comprehensive guardrail system that catches compliance violations, hallucinated numbers, AI-sounding language, and formatting issues before any email goes out.

### Why deterministic checks over LLM review

Sending every email to an LLM for review is expensive, slow, and unreliable (LLMs hallucinate bias flags). Deterministic regex checks are free, instant, and consistent. The LLM is reserved for ambiguous cases that actually need interpretation — a 10x cost reduction with better reliability.

### What changed

10-check pipeline: prohibited language (discrimination acts), hallucinated numbers (validated against pricing engine), tone, AI giveaway language (30+ patterns), professional terms, plain text only, word count, required regulatory elements (Banking Code, AFCA, cooling-off), sign-off structure, sentence rhythm

**Pricing engine:** Realistic Australian lending rates by purpose and credit band, ASIC RG 262 comparison rate calculations

### Files changed
- `backend/apps/email_engine/services/guardrails.py`, `email_generator.py`, `pricing.py`, `prompts.py`

---

## 2026-03-15 — Bias Detection Redesign (3-Layer Tiered System)

**Goal:** Replace the naive "send everything to an LLM" bias check with a tiered deterministic-first approach that's cheaper, faster, and more reliable.

### Why 3 layers

Layer 1 (regex) catches 90% of issues at zero API cost. Layer 2 (LLM) only fires for the 10% that need interpretation. Layer 3 (human) catches the cases where the LLM isn't confident. This matches how real compliance departments work — junior analysts screen, senior analysts review flags, compliance officers sign off.

### What changed

**Layer 1:** Deterministic regex, weighted scoring 0-100, zero API cost
**Layer 2:** Claude Sonnet for moderate flags (60-80), sorts false positives from real issues
**Layer 3:** Human escalation for low-confidence LLM reviews (<0.70)
**Orchestrator:** Zombie run detection, auto-recovery after 5 minutes

### Files changed
- `backend/apps/agents/services/bias_detector.py`, `marketing_agent.py`, `orchestrator.py`, `tasks.py`

---

## 2026-03-14 — Next Best Offer Engine and Marketing Agent

**Goal:** When an applicant is denied, automatically generate alternative product suggestions and a marketing email — with its own compliance pipeline.

### Why NBO matters

A denial is a lost customer. If they don't qualify for a $600K home loan, they might qualify for a $400K loan with a longer term, or a secured personal loan. The NBO engine analyses why they were denied and suggests alternatives. This is standard practice at every major lender.

### What changed

**NBO engine:** Analyses denial reasons, generates up to 3 alternatives with estimated rates
**Marketing agent:** Claude generates professional follow-up email, separate bias check (tighter thresholds)
**Pipeline integration:** NBO + marketing fires automatically after denial

### Files changed
- `backend/apps/agents/services/next_best_offer.py`, `marketing_agent.py`, `orchestrator.py`

---

## 2026-03-13 — Frontend Polish and Customer Experience

**Goal:** Improve the frontend UI, add SHAP visualisation, implement agent status polling, and enforce customer profile completeness.

### What changed

- SHAP feature importance bar chart on application detail page
- Drift warning display for unusual applicant values
- `useAgentStatus` polling hook (2-second intervals during pipeline)
- Customer profile completeness enforcement before loan submission
- UI cleanup (unused CSS, button variants)

### Files changed
- `frontend/src/components/applications/ApplicationDetail.tsx`
- `frontend/src/hooks/useAgentStatus.ts`
- `frontend/src/app/globals.css`, `frontend/src/components/ui/button.tsx`

---

## 2026-03-12 — Initial Scaffold

**Goal:** Build the full project structure with all Django apps, frontend, Docker configuration, and basic functionality end-to-end.

### What was built

**Backend:** 5 Django apps (accounts, loans, ml_engine, email_engine, agents), JWT auth with Argon2, PII encryption, Celery with 3 queues, rate limiting, audit logging

**Frontend:** Next.js 15, React 19, shadcn/ui, TanStack Query, JWT auth flow

**Infrastructure:** Docker Compose (7 containers), PostgreSQL 17, Redis, separate ML/IO workers

**ML Pipeline:** XGBoost + Random Forest, synthetic data generator, GridSearchCV, model versioning

### Files created
- Full project structure: ~50 Python files, ~20 TypeScript/React files, 7 Docker configs
