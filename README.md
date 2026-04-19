# Loan Approval AI System

![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Django 5](https://img.shields.io/badge/Django-5-092E20?logo=django&logoColor=white)
[![CI](https://github.com/zeroyuekun/loan-approval-ai-system/actions/workflows/test.yml/badge.svg)](https://github.com/zeroyuekun/loan-approval-ai-system/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/zeroyuekun/loan-approval-ai-system)](https://github.com/zeroyuekun/loan-approval-ai-system/releases)
![Last commit](https://img.shields.io/github/last-commit/zeroyuekun/loan-approval-ai-system)
![License](https://img.shields.io/badge/License-MIT-yellow)

Full-stack loan approval system for Australian lending. XGBoost scores applicants, Claude writes the decision emails, and an agent pipeline checks everything for bias before it ships.

**What makes it different:**

- **3-layer bias detection** — regex pre-screen → Claude review → human escalation, scored 0–100 per generated email
- **15 deterministic guardrails** on every Claude message (prohibited language, hallucinated dollar amounts, aggressive tone, regulatory-element presence, and more)
- **$5/day Claude spend cap** with template-first generation — production cost control built in, not an afterthought

The compliance layer — APRA serviceability buffers, NCCP Act responsible lending, Banking Code disclosure — is where most of the work went.

<details>
<summary><strong>Screenshots</strong> (click to expand)</summary>

### Dashboard
![Dashboard](docs/screenshots/01-dashboard.png)

### Loan Applications
![Applications](docs/screenshots/02-applications.png)

### Application Detail
![Application Detail](docs/screenshots/03-application-detail.png)

### Model Metrics
![Model Metrics](docs/screenshots/04-model-metrics.png)

### Generated Emails
![Emails](docs/screenshots/05-emails.png)

</details>

## How the pipeline works

```mermaid
flowchart TD
    A[Application submitted] --> B[1. XGBoost scores it]
    B --> B1[probability + SHAP]
    B1 --> C[2. Claude writes the email]
    C --> D[3. Guardrails — 15 deterministic checks]
    D --> E[4. Bias pre-screen regex<br/>score 0–100]
    E -- "score ≤ 60" --> F[Send the email]
    E -- "60–80" --> G[Claude reviews flags]
    G -- "confidence &lt; 0.70" --> H[Human review]
    G -- "confidence ≥ 0.70" --> F
    E -- "score &gt; 80" --> H
    F --> I[5. Email sends]
    I --> J{Denied?}
    J -- yes --> K[6. NBO — alternative offers]
    J -- no --> L[7. Frontend polls status]
    K --> L

    classDef primary fill:#1e40af,color:#fff,stroke:#1e3a8a
    classDef review fill:#dc2626,color:#fff,stroke:#991b1b
    classDef ok fill:#059669,color:#fff,stroke:#065f46
    class A,B,C,I primary
    class H review
    class F,L ok
```

Failed steps put the application into "review" with a log of where it broke. Stuck pipelines auto-recover after 5 minutes.

## Stack

| Layer | Tech |
|-------|------|
| Backend | Django 5, DRF, PostgreSQL 17, Celery + Redis |
| Frontend | Next.js 15, React 19, TanStack Query, Tailwind, shadcn/ui |
| ML | scikit-learn, XGBoost, SHAP, Optuna |
| AI | Claude API (Sonnet for generation, Opus for compliance review) |
| Infra | Docker Compose, 7 containers, separate ML and IO Celery workers |

## Run locally in 60 seconds

Prereqs: Docker Desktop (or Docker Engine + Compose v2), ~4 GB free RAM, an Anthropic API key.

```bash
git clone https://github.com/zeroyuekun/loan-approval-ai-system.git
cd loan-approval-ai-system
cp .env.example .env      # add ANTHROPIC_API_KEY
docker compose up -d      # backend, frontend, db, redis, ml + io workers
docker compose exec backend bash scripts/init_db.sh
docker compose exec backend bash scripts/seed_data.sh
```

Then:

- Dashboard → [http://localhost:3000](http://localhost:3000) — default login `admin` / `admin1234`
- API docs → [http://localhost:8000/api/schema/swagger-ui/](http://localhost:8000/api/schema/swagger-ui/)
- Tests → `docker compose exec backend pytest tests/ -v`

Something broken? See [runbooks](docs/runbooks/).

<details>
<summary><strong>Project layout</strong> (click to expand)</summary>

```
backend/
  apps/
    accounts/       # JWT auth, roles (admin, officer, customer)
    loans/          # application CRUD, status management, audit log
    ml_engine/      # training, prediction, drift detection, metrics
    email_engine/   # Claude emails, guardrails, pricing
    agents/         # bias detection, NBO, marketing agent, orchestrator
  config/           # settings, celery, urls

frontend/src/
  app/              # pages (dashboard, applications, agents, customers)
  components/       # shadcn/ui + domain components
  hooks/            # polling, mutations, auth

scripts/            # init_db.sh, seed_data.sh
tools/              # standalone training + evaluation scripts
workflows/          # markdown SOPs for each pipeline stage
```

</details>

## Design decisions

| Decision | ADR |
|----------|-----|
| Gaussian copula synthetic data calibrated to ATO/ABS/APRA stats | [001](backend/docs/adr/001-synthetic-data-with-copula.md) |
| XGBoost with monotonic constraints for regulatory consistency | [002](backend/docs/adr/002-xgboost-with-monotonic-constraints.md) |
| Three-layer bias detection (regex -> LLM -> human escalation) | [003](backend/docs/adr/003-hybrid-bias-detection.md) |
| Temporal validation strategy with out-of-time splits | [004](backend/docs/adr/004-temporal-validation-strategy.md) |
| Django over FastAPI | [005](backend/docs/adr/005-django-over-fastapi.md) |
| Template-first email with $5/day Claude budget cap | [006](backend/docs/adr/006-template-first-email-with-cost-cap.md) |
| WAT architecture (workflows, agents, tools) | [007](backend/docs/adr/007-wat-architecture.md) |
| Security architecture | [008](backend/docs/adr/008-security-architecture.md) |

<details>
<summary><strong>ML model details</strong> (click to expand)</summary>

XGBoost trained on synthetic Australian lending data. 71 raw applicant input fields (48 numeric + categoricals) with 31 engineered interactions, Optuna Bayesian hyperparameter optimisation, isotonic probability calibration, 21 monotonic constraints (higher income -> lower risk, etc.).

The synthetic data is calibrated against ATO, ABS, APRA, and Equifax published statistics. It includes latent variables the model can't see (documentation quality, savings patterns, employer stability), underwriter disagreement noise, and measurement error — so the model hits realistic metrics (test AUC 0.88 per the active `ModelVersion`; reproducible benchmark on a 2,000-record subset is 0.85 with default hyperparameters — see `docs/experiments/benchmark.md`) rather than the 0.99 you get with clean synthetic labels.

Other ML features: IV-based feature selection, PSI/CSI drift monitoring, reject inference (parcelling method), conformal prediction intervals, SHAP-mapped adverse action reason codes (70 codes), APRA stress testing (+3% rate buffer), and a WOE scorecard built alongside XGBoost for interpretability comparison.

## Email guardrails

Every email Claude generates goes through 10 checks before sending:

1. Prohibited language (discrimination acts)
2. Hallucinated dollar amounts (validated against application data)
3. Aggressive tone
4. Overly formal/corporate phrasing
5. Unprofessional financial language
6. Markdown/HTML rejection (plain text only)
7. Word count limits
8. Required regulatory elements (AFCA reference, cooling-off period, etc.)
9. Double sign-off detection
10. Sentence rhythm uniformity (flags suspiciously even sentence lengths)

Three regeneration attempts, then human review.

### Retraining the model

```bash
docker compose exec backend python manage.py generate_data --num-records 10000 --output .tmp/synthetic_loans.csv
docker compose exec backend python manage.py train_model --algorithm xgb --data-path .tmp/synthetic_loans.csv
```

</details>

<details>
<summary><strong>API reference</strong> (click to expand)</summary>

Auth: `POST /api/v1/auth/{register,login,refresh,logout}/`, `GET /api/v1/auth/me/`

Loans: `GET /api/v1/loans/`, `POST /api/v1/loans/`, `GET /api/v1/loans/{id}/`

ML: `POST /api/v1/ml/predict/{id}/`, `GET /api/v1/ml/models/active/metrics/`

Emails: `POST /api/v1/emails/generate/{id}/`, `GET /api/v1/emails/{id}/`

Agents: `POST /api/v1/agents/orchestrate/{id}/`, `GET /api/v1/agents/runs/{id}/`, `POST /api/v1/agents/review/{id}/`

</details>

## Security

JWT with HttpOnly cookies, 60-min access / 7-day refresh with rotation and blacklisting. Argon2 password hashing. Fernet field-level encryption for PII. Rate limiting (20/min anon, 60/min auth). CORS locked to frontend origin. Three roles with per-endpoint permission checks. Prompt injection defences on user text entering LLM prompts.

<details>
<summary><strong>Monitoring and observability</strong> (click to expand)</summary>

A full monitoring stack ships behind the `monitoring` profile — Prometheus, Grafana, Loki, Promtail, Alertmanager, a Celery exporter, and a Postgres exporter. Django exposes `/metrics` via `django-prometheus` with request latencies, ORM query counts, Celery task counters, and a custom training-duration histogram. Nothing runs by default, so the core stack stays small; you opt in when you want dashboards.

Grafana lives in `docker-compose.monitoring.yml` so the main stack parses without a Grafana admin password. Before launching, set `GRAFANA_ADMIN_PASSWORD` in `.env` (compose refuses to start the monitoring profile without it — no silent fallback), then launch alongside the regular stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring up -d
```

Or set `COMPOSE_FILE=docker-compose.yml:docker-compose.monitoring.yml` in `.env` to make both files the default, after which `docker compose --profile monitoring up -d` works as before.

Then:

- Grafana at `localhost:3001` for dashboards (Django request latencies, Celery queue depth, Postgres slow queries, system logs)
- Prometheus at `localhost:9090` for raw metric queries
- Loki at `localhost:3100` as the log aggregation backend for Promtail

A separate `watchdog` service runs in the core stack at all times. It polls every 30 seconds for loan applications stuck in the `pending` state for more than 5 minutes and re-queues their orchestration task — so transient worker or broker failures self-recover rather than leaving zombie applications in the queue.

</details>

## Testing

~1000 tests across 66 files. 60% backend coverage floor enforced in CI. CI pipeline runs Ruff, Bandit SAST, gitleaks, npm audit, OWASP ZAP DAST, k6 load test, and Trivy container scanning.

<details>
<summary><strong>Verifying the build</strong> (click to expand)</summary>

An end-to-end smoke script exercises the full pipeline (register → apply → orchestrate → decision → email) against a locally-running stack:

```bash
docker compose up -d
make seed                     # generate data + train model
tools/smoke_e2e.sh            # full cycle + teardown
tools/smoke_e2e.sh --keep-up  # leave stack up for manual inspection
```

Result is written to `.tmp/smoke_result.json`:

```json
{
  "started_at": "2026-04-19T12:34:56Z",
  "finished_at": "2026-04-19T12:35:42Z",
  "duration_ms": 46123,
  "status": "success",
  "reason": "ok",
  "model_version_id": "<uuid>",
  "email_subject_hash": "<sha256-prefix>"
}
```

The same script runs as a manually-triggered GitHub Actions job under `smoke-e2e` (see `.github/workflows/smoke-e2e.yml`). The workflow is `workflow_dispatch`-only by design — cost-conscious default; add a cron once the signal is known stable.

</details>

<details>
<summary><strong>Housekeeping</strong> (click to expand)</summary>

Local development accumulates build artifacts, test caches, and trained model files. To reclaim disk:

```bash
make clean-soft  # caches + build output ONLY — docker volumes (DB, redis) preserved
make clean       # FULL wipe: containers + volumes + caches (DB is wiped — use sparingly)
make clean-deep  # clean + removes node_modules and backend/.venv (forces reinstall)
```

Day-to-day, `make clean-soft` is the right default — it reclaims several hundred MB of Python/Next.js caches without touching the Postgres volume. Reserve `make clean` for "I want a fresh-from-seed DB".

To prune stale trained-model `.joblib` artifacts from `backend/ml_models/` (after many training iterations):

```bash
docker compose exec backend python manage.py prune_model_artifacts --dry-run  # preview
docker compose exec backend python manage.py prune_model_artifacts            # delete
```

</details>

## Scope & limits

- **Synthetic training data.** The data generator is calibrated against ATO, ABS, APRA, and Equifax published statistics, runs labels through a 1000-line rules-based underwriting engine, and adds a separate loan-performance simulator. It does not capture real-world feedback loops, fraud patterns, broker channel effects, or lender-specific heuristics. A production rollout would retrain on real historical data.
- **Reported AUC is on the synthetic pipeline.** XGBoost achieves 0.88 AUC on the synthetic holdout of the active `ModelVersion` (see `backend/docs/MODEL_CARD.md`). The TSTR validator estimates real-world AUC around 0.82 with moderate confidence. Walk-forward temporal CV AUC is reported in `training_metadata.temporal_cv_auc_mean` so the drift gap against random CV is visible.
- **XGBoost lift over a simple scorecard is a measured number.** Every training run fits a logistic-regression baseline on `credit_score, annual_income, loan_amount, debt_to_income` and records `training_metadata.baseline_auc` + `xgb_lift_over_baseline` on the model card.
- **Email generation is template-first.** Claude is used for creative variations only, with a $5/day spend cap on the Anthropic API. The guardrail layer runs 15 deterministic checks on every LLM-generated message before it ships.
- **Compliance framing is implemented, not audited.** APRA CPG 235, NCCP Act responsible lending, Banking Code disclosure, and adverse-action language are baked into the data model, email templates, and fairness gates. None of this has been independently reviewed by a compliance professional.
- **Reliability is prototype-grade.** Eight core services ship with healthchecks, the watchdog auto-recovers stuck pipelines, and the monitoring stack exposes Prometheus metrics + Grafana dashboards. No paging, no multi-region failover, no SLO enforcement. Good enough for a demo, not a fintech launch.

## License

MIT
