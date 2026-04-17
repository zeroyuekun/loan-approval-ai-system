# Changelog

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
