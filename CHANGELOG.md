# Changelog

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
