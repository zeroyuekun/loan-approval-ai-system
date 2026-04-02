# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.8.1] - 2026-04-02

### Security
- Restrict ML model views (metrics, model card, versions, drift) to admin/officer only — were accessible to customers
- Bind Prometheus and Grafana monitoring ports to `127.0.0.1` — were on `0.0.0.0`
- Use `hmac.compare_digest` for health check token comparison (timing-attack safe)
- Randomize Django admin URL via `DJANGO_ADMIN_URL` env var
- Narrow LogoutView exception handler to `TokenError` — was bare `except Exception`
- Add `dast-scan` failure check to CI deploy gate condition
- Pin Trivy GitHub Action to commit SHA after supply-chain compromise (GHSA-69fq-xp46-6x23)
- Add `max_length=10000` to complaint description serializer (was unbounded)

### Fixed
- Optuna `cross_val_score` uses `fit_params=` instead of `params=` — was silently dropping sample weights
- `lvr_x_property_growth` feature interaction: normalize percentage to fraction (`/ 100`) — was ~100x magnitude error
- Remove inert `MedianPruner` from Optuna study (no `trial.report()` calls in batch cross-validation)
- Add 1200s wall-clock timeout to Optuna `study.optimize` — prevents exceeding Celery task time limit
- Fix reject inference `transform()` clobbering train imputation values after restore
- Fix watchdog Celery app connection leak — reuse single instance across cycles
- Watchdog sends `X-Health-Token` header when polling `/health/deep/`
- Watchdog CLI args enforce minimum bounds (interval>=5s, idle>=1m, failures>=1)
- Fix `setTimeout` memory leak in `usePipelineOrchestration` — cleanup on unmount
- Fix `useAuth.register` callback type: `any` → `RegisterPayload`
- Narrow `AgentStep.result_summary` and `TaskStatus.result` from `any` to typed union
- Resolve Trivy HIGH vulnerabilities in frontend Docker image
- Update numeric cols test assertion (90 → 94) and metamorphic test for `credit_x_employment`

## [1.8.0] - 2026-04-02

### Added
- **Optuna Bayesian hyperparameter optimization** for XGBoost, replacing RandomizedSearchCV. Uses TPE sampler with configurable trial count (`ML_OPTUNA_TRIALS`, default 50). Wider search space: max_depth 4-10, learning_rate 0.01-0.15 (log), reg_lambda 1-50 (log), plus reg_alpha and gamma
- **4 research-backed feature interactions**: `lvr_x_property_growth` (negative equity risk), `deposit_x_income_stability` (compounding risk), `dti_x_rate_sensitivity` (rate exposure), `credit_x_employment` (profile strength)
- **Self-healing watchdog service** running as Docker container: health endpoint polling, stuck Celery task detection and revocation, idle DB connection termination, Redis-backed health state tracking
- **Trivy container image scanning** in CI for backend and frontend Docker images. Pinned to commit SHA (not mutable tag) after trivy-action supply-chain compromise (GHSA-69fq-xp46-6x23)
- "What to look for in this project" recruiter section in README

### Changed
- XGBoost hyperparameter search now uses Optuna TPE sampler instead of sklearn RandomizedSearchCV (10x faster convergence, research-backed for credit risk modeling)
- Feature engineering module now produces 31 derived features (up from 27)
- CI pipeline now runs 12 jobs: backend lint, backend tests, frontend lint, frontend tests, security scan, secret scan, dependency audit, Docker build, Trivy scan, DAST (ZAP), load test (k6), image push

### Fixed
- Duplicate dictionary keys in `template_fallback.py` (ruff F601)
- Import ordering in migration 0019 (ruff I001)
- `test_data_export.py` hardcoded `/app/ml_models/` path replaced with `settings.ML_MODELS_DIR`
- lodash updated to 4.18.1 (npm audit high severity vulnerability)
- All stale GridSearchCV references updated to Optuna in UI, MODEL_CARD, workflows, and trainer comments

## [1.7.1] - 2026-04-02

### Added
- Sentry error tracking on backend (Django + Celery) and frontend (Next.js), guarded by DSN env vars
- RBA Table E2 live fetch for household debt-to-income ratios with percentage normalization
- AIHW Housing Data Dashboard delinquency benchmarks as secondary cross-validation in `CalibrationValidator`
- SA3-level property data service with population-weighted region assignment (~50 seeded regions)

### Fixed
- Version strings synced to 1.7.0 across `base.py` and `package.json`
- Predictor `CATEGORICAL_COLS` mismatch with trainer (added `sa3_region`, `industry_anzsic`)
- Test count assertions updated (89 to 90 numeric, 7 to 9 categorical columns)
- All 993 tests now passing (0 failures)

### Removed
- Compliance footer from login, register, and apply pages

## [1.7.0] - 2026-04-01

### Added
- Application state machine (submitted, processing, approved, denied, withdrawn)
- Fairness gate with EEOC 80% rule threshold on employment type
- Repayment estimator component on application detail page
- AU regulatory compliance disclosures (NCCP Act, AFCA, Privacy Policy)
- WCAG accessibility improvements (focus rings, ARIA labels)

### Changed
- Reordered application detail cards (repayment estimator above ML decision)
- Pipeline state transitions enforce valid state machine paths
- Console email backend fallback when SMTP not configured

### Fixed
- DecisionSection test assertions for updated pipeline states
- Ruff format and import sorting violations
- `.env` loading via python-dotenv in manage.py, wsgi.py, celery.py

## [1.6.0] - 2026-03-31

### Added
- Real-world Australian lending calibration with 65+ synthetic features
- Gaussian copula correlation matrix for realistic feature joint distributions
- Sub-population mixture model (6 borrower segments: FHB, upgrader, refinancer, personal, business, investor)
- State-specific profiles (median house prices, income multipliers, credit score adjustments)
- Macroeconomic context features (RBA cash rate history, unemployment, property growth, CCI)
- Behavioural realism features (optimism bias, financial literacy, application channels)
- CDR/Open Banking features (savings trends, gambling flags, BNPL tracking)
- Comprehensive Credit Reporting (CCR) features
- `RealWorldBenchmarks` service with live data from ABS, APRA, RBA, Equifax (7-day cache, hardcoded fallbacks)
- `CalibrationValidator` for APRA benchmark comparison (SR 11-7 outcomes analysis)

## [1.5.0] - 2026-03-27

### Added
- Pipeline auto-completion (prediction, email, bias detection in single orchestrator run)
- Champion/challenger model scoring with shadow predictions
- Conformal prediction intervals with coverage guarantees
- Stress testing (4 adverse scenarios: income, property, credit, combined)
- Counterfactual explanations for denied applications
- Drift detection using PSI (Population Stability Index)
- Monotonic constraints on all XGBoost features

### Changed
- Email generation improved with HTML bold headers and marketing delivery tracking
- Denial emails streamlined (no assessment details, clearer adverse action reasons)

## [1.4.0] - 2026-03-27

### Added
- k6 load test suite with SLA assertions (P95 thresholds for health, login, list, pipeline)
- `ModelValidationReport` model for SR 11-7 independent validation sign-off
- `validate_model` management command: champion vs challenger evaluation with fairness analysis
- Data retention lifecycle: weekly `enforce_retention` task per AML/CTF Act and APRA CPG 235
- Frontend component tests for BiasScoreBadge (7 tests) and stepLabels (17 tests)

## [1.3.0] - 2026-03-27

### Added
- TOTP-based 2FA for officer/admin roles (django-otp)
- `SoftDeleteModel` mixin on CustomerProfile and LoanApplication
- Encrypted address, phone, and employer fields at rest (Fernet AES)
- `retraining_policy` JSON field on ModelVersion (SR 11-7)
- Weekly fairness violation alerting Celery task (80% disparate impact rule)
- Schemathesis contract test scaffold
- `SECURE_PROXY_SSL_HEADER` for reverse proxy deployments
- `/health/ready` readiness probe alias
- aria-labels for WCAG accessibility on applications page

## [1.2.0] - 2026-03-26

### Added
- Docker CPU/memory resource limits on all services
- PII masking log filter (TFN, Medicare, phone, income redaction in production logs)
- Model governance fields: decision thresholds, review dates, explainability method
- Credit score disclosure and 90-day free report right in denial emails
- Celery pipeline rate limit (60 tasks/min)
- Frontend error toast and empty state on applications page

## [1.1.0] - 2026-03-24

### Added
- Fraud detection service with velocity checks and risk scoring
- Decision waterfall (ML prediction + fraud check + business rules)
- Conditional approval support with conditions tracking
- Model card generator (APRA CPG 235 compliance)
- Field-level encryption for identity document numbers (Fernet AES-128-CBC)
- Encryption key rotation management command

## [1.0.0] - 2026-03-24

### Added
- Production-ready deployment configuration (multi-stage Docker, gunicorn)
- Monitoring stack (Prometheus, Grafana, AlertManager) as opt-in profile
- 5 provisioned Grafana dashboards (AI Ops, Celery, System, ML Metrics, SLO)
- OWASP ZAP DAST scanning in CI pipeline
- E2E tests with Playwright (auth, application, pipeline flows)

## [0.5.0] - 2026-03-24

### Performance
- Reduce XGBoost hyperparameter grid from 240 to 90 candidate fits (3x faster training)

### Fixed
- Marketing email guardrails: whitelist customer profile amounts and FCS $250k disclosure
- Approval email generation: increase max_tokens from 1024 to 4096 (was truncating tool_use JSON)
- Application status not updating to final decision after pipeline completion

## [0.4.0] - 2026-03-24

### Added
- Frontend test suite: Vitest + React Testing Library + MSW (7 test files)
- Backend test suite: 38 test files with 80% coverage enforcement in CI
- Prometheus metrics endpoint with custom ML counters (prediction latency, drift scores)
- Grafana dashboards for loan approval pipeline and ML model performance
- AlertManager rules for prediction latency, error rate, and model drift
- Kubernetes manifests with Kustomize (namespace, deployments, ingress, configmaps)
- Terraform IaC for AWS (VPC, RDS, ElastiCache, ALB, IAM)
- Architecture Decision Records (ADRs) for synthetic data, XGBoost constraints, bias detection, temporal validation
- Model Card documenting training methodology, fairness metrics, and known limitations
- Operations runbook with incident response procedures
- SLA definitions for pipeline latency and availability targets

### Fixed
- Pipeline resilience: added circuit breaker and retry logic for Claude API calls
- Mobile header overlapping navigation elements on small screens
- Email template rendering when profile context is missing
- LightGBM lazy import to avoid crash in environments without native library

## [0.3.0] - 2026-03-20

### Added
- Human review queue for escalated applications (bias flags, guardrail failures, low-confidence predictions)
- Batch orchestration endpoint for processing multiple applications
- Agent workflow timeline component showing step-by-step pipeline progress
- Resume-after-review flow: approved applications continue pipeline from where they paused
- Logo redesign and brand refresh across dashboard

### Fixed
- Orchestrator lock contention when multiple pipelines target the same application
- Timeline component not updating on WebSocket reconnect

## [0.2.0] - 2026-03-20

### Added
- Customer profile page with savings balance, checking balance, loyalty tier display
- Edit Profile functionality with form validation
- Profile link in admin dropdown navigation
- Customer experience flow documentation in README
- Staff view of customer details with banking relationship context

### Fixed
- Profile page layout breaking when optional fields are null
- Navigation not redirecting after profile update
- Missing CSRF token on profile PATCH requests

## [0.1.0] - 2026-03-19

### Added
- ML prediction pipeline: XGBoost with monotonic constraints, Platt calibration, SHAP explanations
- Synthetic data generator using Gaussian copula (calibrated against ABS/APRA/Equifax statistics)
- Claude API email generation for approval and denial decisions
- 10 deterministic guardrail checks (prohibited language, hallucinated numbers, tone, required elements)
- Hybrid bias detection: regex pre-screen + LLM review with escalation thresholds
- Next Best Offer engine with product recommendations for denied applicants
- Marketing email agent with compliance guardrails (Banking Code, NCCP Act, ASIC RG 234)
- Orchestrator pipeline chaining prediction, email, bias, NBO, and marketing steps
- Customer profile system with loyalty tiers and banking relationship tracking
- JWT authentication with role-based access (admin, loan officer, customer)
- Separate Celery queues for ML, email, and agent workloads
- Docker Compose environment with PostgreSQL 17, Redis 7, and hot-reload
- OpenAPI documentation via drf-spectacular at /api/docs/
- GitHub Actions CI: backend tests, lint, security scan, dependency audit, Docker build, GHCR deploy

## [0.0.1] - 2026-03-12

### Added
- Initial project scaffold
- Django 5 + Django REST Framework backend
- Next.js 15 frontend with shadcn/ui component library
- PostgreSQL and Redis service configuration
- Loan application model with CRUD endpoints
- Basic project structure: apps (accounts, loans, ml_engine, email_engine, agents)
