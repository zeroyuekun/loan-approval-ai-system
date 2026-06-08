# Operations Runbook — AussieLoanAI

## Service Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend    │────>│   Backend    │────>│ PostgreSQL   │
│  (Next.js)  │     │  (Django)    │     │  (port 5432) │
│  port 3000  │     │  port 8000   │     └─────────────┘
└─────────────┘     │              │     ┌─────────────┐
                    │              │────>│   Redis      │
                    └──────┬───────┘     │  (port 6379) │
                           │             └─────────────┘
                    ┌──────┴───────┐
                    │   Celery     │
                    ├──────────────┤
                    │ worker_ml    │  Queue: ml (concurrency: 2)
                    │ worker_io    │  Queue: email, agents, celery (concurrency: 4)
                    │ beat         │  Scheduler (weekly tasks)
                    └──────────────┘
                    ┌──────────────┐
                    │  Monitoring  │
                    ├──────────────┤
                    │ Prometheus   │  port 9090
                    │ Grafana      │  port 3001 (admin/admin)
                    └──────────────┘
```

### Docker Compose Services

| Service | Image / Build | Ports | Health Check |
|---------|--------------|-------|-------------|
| `db` | `postgres:17-alpine` | 127.0.0.1:5432 | `pg_isready -U postgres` (10s interval) |
| `redis` | `redis:7-alpine` | 127.0.0.1:6379 | `redis-cli -a $REDIS_PASSWORD ping` (10s interval) |
| `backend` | `./backend` (gunicorn, 4 workers, 2 threads) | 8000 | HTTP GET `http://localhost:8000/api/v1/health/` (30s interval) |
| `celery_worker_ml` | `./backend` | None | `celery -A config inspect ping` (30s interval) |
| `celery_worker_io` | `./backend` | None | `celery -A config inspect ping` (30s interval) |
| `celery_beat` | `./backend` | None | None |
| `frontend` | `./frontend` (npm run dev) | 3000 | `wget -q --spider http://localhost:3000` (30s interval) |
| `prometheus` | `prom/prometheus:latest` | 9090 | None |
| `grafana` | `grafana/grafana:latest` | 3001 | None |

### Task Routing

| Task Pattern | Queue |
|-------------|-------|
| `apps.ml_engine.tasks.*` | `ml` |
| `apps.email_engine.tasks.*` | `email` |
| `apps.agents.tasks.*` | `agents` |
| All others | `celery` (default) |

## API Endpoints

### Health

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/health/` | No | Basic liveness check |
| GET | `/api/v1/health/deep/` | **Yes** (staff session or X-Health-Token) | DB + Redis + ML model check. Returns 503 in production if `HEALTH_CHECK_TOKEN` is unset. |
| GET | `/metrics` | **Yes** (staff session or X-Health-Token) | Prometheus metrics (django-prometheus). Not publicly routed. |

### Authentication (`/api/v1/auth/`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/register/` | No | Register new user |
| POST | `/api/v1/auth/login/` | No | Login (JWT in cookies) |
| POST | `/api/v1/auth/refresh/` | Cookie | Refresh JWT token |
| POST | `/api/v1/auth/logout/` | Yes | Logout |
| GET | `/api/v1/auth/csrf/` | No | Set CSRF cookie |
| GET/PUT | `/api/v1/auth/me/` | Yes | User profile |
| GET/PUT | `/api/v1/auth/me/profile/` | Yes | Customer profile |
| GET | `/api/v1/auth/me/data-export/` | Yes | Customer data export |
| GET | `/api/v1/auth/customers/` | Staff | List all customers |
| GET | `/api/v1/auth/customers/<user_id>/profile/` | Staff | Customer profile detail |
| GET | `/api/v1/auth/customers/<user_id>/activity/` | Staff | Customer activity history |

### Loans (`/api/v1/loans/`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/loans/` | Yes | List loan applications |
| POST | `/api/v1/loans/` | Yes | Create loan application |
| GET | `/api/v1/loans/<id>/` | Yes | Loan application detail |
| PUT/PATCH | `/api/v1/loans/<id>/` | Yes | Update loan application |

### ML Engine (`/api/v1/ml/`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/ml/predict/<loan_id>/` | Yes | Run ML prediction on a loan |
| GET | `/api/v1/ml/models/active/metrics/` | Yes | Active model performance metrics |
| GET | `/api/v1/ml/models/active/drift/` | Yes | PSI drift analysis |
| POST | `/api/v1/ml/models/train/` | Staff | Trigger model training |

### Email Engine (`/api/v1/emails/`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/emails/` | Yes | List generated emails |
| POST | `/api/v1/emails/generate/<loan_id>/` | Yes | Generate approval/denial email |
| GET | `/api/v1/emails/<loan_id>/` | Yes | Email detail for a loan |

### Agents (`/api/v1/agents/`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/agents/orchestrate/<loan_id>/` | Yes | Run full pipeline (predict + email + bias) |
| POST | `/api/v1/agents/orchestrate-all/` | Staff | Batch orchestrate all pending loans |
| GET | `/api/v1/agents/runs/` | Yes | List agent runs |
| GET | `/api/v1/agents/runs/<loan_id>/` | Yes | Agent run detail for a loan |
| POST/PUT | `/api/v1/agents/review/<run_id>/` | Staff | Human review for bias-flagged runs |

### Task Status

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/tasks/<task_id>/status/` | Yes | Poll async Celery task result |

## Health Check Endpoints

| Endpoint | What It Checks | Healthy | Unhealthy |
|----------|---------------|---------|-----------|
| `GET /api/v1/health/` | Basic service alive | 200 `{"status": "ok"}` | 503 |
| `GET /api/v1/health/deep/` | DB + Redis + ML model | 200 `{"database": "ok", "redis": "ok", "ml_model": "ok", "status": "healthy"}` | 503 with `"status": "degraded"` and failed components |

## Monitoring

| Service | URL | Credentials |
|---------|-----|------------|
| Grafana | http://localhost:3001 | admin / admin |
| Prometheus | http://localhost:9090 | None |
| Django metrics | http://localhost:8000/metrics | None |

### Prometheus Scrape Config

| Job Name | Target | Interval |
|----------|--------|----------|
| `django-backend` | `backend:8000/metrics` | 10s |
| `redis` | `redis:6379` | 15s (global default) |

### Alert Rules Configured

| Alert | Condition | Severity | What It Means | What To Do |
|-------|-----------|----------|--------------|-----------|
| **High Error Rate (>5%)** | 5xx responses exceed 5% of total over 5 min, sustained 2 min | Critical | Backend is returning server errors at a dangerous rate | Check backend logs (`docker logs`), check deep health endpoint, look for DB or Redis connection failures |
| **High API Latency (p95 > 2s)** | 95th percentile request latency exceeds 2 seconds over 5 min, sustained 5 min | Warning | Requests are abnormally slow — likely slow DB queries or long ML prediction times | Check for slow queries, verify ML model is loaded, check DB connection pool |
| **Health Check Failing** | Prometheus `up{job="django-backend"}` drops below 1, sustained 1 min | Critical | Backend service is completely DOWN — Prometheus cannot reach `/metrics` | Restart backend service immediately, check container logs for crash reason |
| **Celery Queue Backlog** | POST request rate exceeds 50 requests/5min, sustained 5 min | Warning | Unusual volume of mutations — potential queue backup or abuse | Check Celery queue lengths, verify workers are running, scale workers if legitimate traffic |

## Common Incidents

### 1. Model Producing Bad Predictions

**Symptoms:** Approval rate suddenly spikes or drops; customer complaints about incorrect decisions

**Diagnosis:**
```bash
# Check active model and its metrics
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c "
from apps.ml_engine.models import ModelVersion
mv = ModelVersion.objects.filter(is_active=True).first()
print(f'Active model: {mv.algorithm} {mv.version}')
print(f'AUC: {mv.auc_roc}, Gini: {mv.gini_coefficient}')
print(f'Accuracy: {mv.accuracy}, F1: {mv.f1_score}')
print(f'File hash: {mv.file_hash}')
"

# Check PSI drift via API
curl http://localhost:8000/api/v1/ml/models/active/drift/

# Check model metrics via API
curl http://localhost:8000/api/v1/ml/models/active/metrics/
```

**Resolution:**
```bash
# Retrain on fresh synthetic data
docker exec loan-approval-ai-system-backend-1 python manage.py generate_data --num-records 10000 --create-db-records 0
docker exec loan-approval-ai-system-backend-1 python manage.py train_model --algorithm xgb

# Or retrain with Random Forest if XGBoost is suspect
docker exec loan-approval-ai-system-backend-1 python manage.py train_model --algorithm rf
```

**Rollback:**
```bash
# List recent model versions
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c "
from apps.ml_engine.models import ModelVersion
for mv in ModelVersion.objects.order_by('-created_at')[:5]:
    print(f'{mv.version} | {mv.algorithm} | AUC: {mv.auc_roc} | Active: {mv.is_active}')
"

# Activate a previous version (ModelVersion.save() atomically deactivates others)
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c "
from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.predictor import clear_model_cache
old = ModelVersion.objects.get(version='VERSION_STRING_HERE')
old.is_active = True
old.save()
clear_model_cache()
print(f'Activated: {old.algorithm} {old.version}')
"
```

### 2. Email Generation Failing

**Symptoms:** Emails not being sent; guardrail failure rate spiking; template fallback being used

**Diagnosis:**
```bash
# Check Claude API budget and circuit breaker
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c "
from django.core.cache import cache
calls = cache.get('api_budget:daily_calls', 0)
print(f'API calls today: {calls}/500')
cb_state = cache.get('api_budget:circuit_breaker')
print(f'Circuit breaker: {cb_state or \"closed (healthy)\"}')
"

# Check recent email guardrail results
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c "
from apps.email_engine.models import GeneratedEmail
recent = GeneratedEmail.objects.order_by('-created_at')[:5]
for e in recent:
    print(f'{e.created_at} | passed={e.passed_guardrails} | attempt={e.attempt_number} | fallback={e.template_fallback}')
"

# Check Celery email queue
docker exec loan-approval-ai-system-celery_worker_io-1 celery -A config inspect active
```

**Resolution:**
- If circuit breaker is open: wait 10 minutes for auto-reset
- If API budget exhausted: resets daily at midnight UTC
- If guardrails failing: check prompt templates have not been corrupted (never add apology language to denial emails)
- Template fallback activates automatically -- emails still go out with static template

### 3. Celery Queue Backing Up

**Symptoms:** Tasks stuck in pending; predictions/emails delayed; `/api/v1/tasks/<id>/status/` returns PENDING for extended periods

**Diagnosis:**
```bash
# Check worker health
docker exec loan-approval-ai-system-celery_worker_ml-1 celery -A config inspect active
docker exec loan-approval-ai-system-celery_worker_io-1 celery -A config inspect active

# Check queue lengths
docker exec loan-approval-ai-system-redis-1 redis-cli -a $REDIS_PASSWORD llen ml
docker exec loan-approval-ai-system-redis-1 redis-cli -a $REDIS_PASSWORD llen email
docker exec loan-approval-ai-system-redis-1 redis-cli -a $REDIS_PASSWORD llen agents
docker exec loan-approval-ai-system-redis-1 redis-cli -a $REDIS_PASSWORD llen celery
```

**Resolution:**
```bash
# Restart workers
docker compose restart celery_worker_ml celery_worker_io

# Scale up IO workers if needed
docker compose up -d --scale celery_worker_io=3
```

### 4. Database Connection Failures

**Symptoms:** 503 on `/api/v1/health/deep/` with `"database": "error: ..."` ; connection errors in backend logs

**Diagnosis:**
```bash
# Check PostgreSQL container
docker exec loan-approval-ai-system-db-1 pg_isready -U postgres
docker logs loan-approval-ai-system-db-1 --tail 20

# Check deep health for specifics
curl -s http://localhost:8000/api/v1/health/deep/ | python -m json.tool
```

**Resolution:**
```bash
docker compose restart db
# Wait for health check (10s interval, 5 retries)
sleep 15
docker compose restart backend celery_worker_ml celery_worker_io celery_beat
```

### 5. High Error Rate Alert Firing

**Symptoms:** Grafana alert "High Error Rate (>5%)" triggered; error rate sustained for 2+ minutes

**Diagnosis:**
```bash
# Check backend logs for 5xx errors
docker logs loan-approval-ai-system-backend-1 --tail 50

# Check deep health for component-level failures
curl -s http://localhost:8000/api/v1/health/deep/ | python -m json.tool

# Check Prometheus for error rate breakdown
# Open http://localhost:9090 and query:
# sum(rate(django_http_responses_total_by_status_total{status=~"5.."}[5m])) by (status)
```

**Resolution:**
- If DB-related: see incident #4
- If Redis-related: `docker compose restart redis`, then restart backend and workers
- If code error: check backend logs for traceback, deploy fix
- If resource exhaustion: check container memory/CPU with `docker stats`

### 6. Redis Connection Failures

**Symptoms:** Celery tasks not executing; `"redis": "error: ..."` in deep health check

**Diagnosis:**
```bash
docker exec loan-approval-ai-system-redis-1 redis-cli -a $REDIS_PASSWORD ping
docker logs loan-approval-ai-system-redis-1 --tail 20
```

**Resolution:**
```bash
docker compose restart redis
sleep 10
docker compose restart backend celery_worker_ml celery_worker_io celery_beat
```

**If loans submitted during the outage:**
Submissions that could not reach the broker are written to
`loans_pipelinedispatchoutbox` and the loan transitions to
`status=queue_failed`. The beat task `retry_failed_dispatches` drains the
outbox on a 60s cadence once Redis returns — loans auto-transition back to
`pending`. Rows that reach `MAX_DISPATCH_ATTEMPTS` (5) are surfaced in
`/admin/loans/pipelinedispatchoutbox/` for operator review:

```bash
# Manually drain (e.g. after an extended outage):
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c \
  "from apps.loans.tasks import retry_failed_dispatches; print(retry_failed_dispatches())"
```

### 7. Frontend Not Loading

**Symptoms:** Blank page at http://localhost:3000; health check failing

**Diagnosis:**
```bash
docker logs loan-approval-ai-system-frontend-1 --tail 30
# Verify backend is reachable from frontend
curl -s http://localhost:8000/api/v1/health/
```

**Resolution:**
```bash
docker compose restart frontend
# If persistent, rebuild
docker compose up -d --build frontend
```

## Operational Commands

### Data Management
```bash
# Generate fresh synthetic data (10K records) with 100 DB records and demo customers
docker exec loan-approval-ai-system-backend-1 python manage.py generate_data --num-records 10000 --create-db-records 100

# Generate without DB records (CSV only to .tmp/synthetic_loans.csv)
docker exec loan-approval-ai-system-backend-1 python manage.py generate_data --num-records 10000 --create-db-records 0

# Custom output path
docker exec loan-approval-ai-system-backend-1 python manage.py generate_data --num-records 5000 --output .tmp/custom_data.csv
```

### Model Management
```bash
# Train new XGBoost model (default, recommended)
docker exec loan-approval-ai-system-backend-1 python manage.py train_model --algorithm xgb

# Train Random Forest model
docker exec loan-approval-ai-system-backend-1 python manage.py train_model --algorithm rf

# Train with custom data path
docker exec loan-approval-ai-system-backend-1 python manage.py train_model --algorithm xgb --data-path .tmp/custom_data.csv

# List model versions
docker exec loan-approval-ai-system-backend-1 python manage.py shell -c "
from apps.ml_engine.models import ModelVersion
for mv in ModelVersion.objects.order_by('-created_at')[:10]:
    print(f'{mv.version} | {mv.algorithm} | AUC: {mv.auc_roc:.4f} | Gini: {mv.gini_coefficient} | Active: {mv.is_active} | {mv.created_at}')
"

# Prune stale .joblib artifacts in backend/ml_models/
# Keeps active ModelVersion + N recent inactive per segment + contract_test_model.joblib.
# Use --dry-run first to preview.
docker compose exec backend python manage.py prune_model_artifacts --dry-run
docker compose exec backend python manage.py prune_model_artifacts --keep 2
```

### Service Management
```bash
# Start all services
docker compose up -d

# Rebuild and restart all
docker compose up -d --build

# View logs (follow)
docker compose logs -f backend
docker compose logs -f celery_worker_ml
docker compose logs -f celery_worker_io

# Restart specific service
docker compose restart backend

# Check container status
docker compose ps

# Check resource usage
docker stats --no-stream
```

### Database Management
```bash
# Run migrations
docker exec loan-approval-ai-system-backend-1 python manage.py migrate

# Create superuser
docker exec -it loan-approval-ai-system-backend-1 python manage.py createsuperuser

# Database shell
docker exec -it loan-approval-ai-system-db-1 psql -U postgres -d loan_approval

# Reverse last migration (example for loans app)
docker exec loan-approval-ai-system-backend-1 python manage.py migrate loans PREVIOUS_MIGRATION_NAME
```

## Rollback Procedures

### Code Rollback
```bash
# Pull specific image version
docker pull ghcr.io/OWNER/loan-approval-ai-system/backend:COMMIT_SHA
docker pull ghcr.io/OWNER/loan-approval-ai-system/frontend:COMMIT_SHA

# Update docker-compose to use specific tag, then restart
docker compose up -d
```

### Model Rollback
See [Incident #1 — Model Producing Bad Predictions](#1-model-producing-bad-predictions) above. Key point: `ModelVersion.save()` with `is_active=True` atomically deactivates all other versions. Always call `clear_model_cache()` after switching.

### Database Rollback
```bash
# Reverse last migration for a specific app
docker exec loan-approval-ai-system-backend-1 python manage.py showmigrations loans
docker exec loan-approval-ai-system-backend-1 python manage.py migrate loans PREVIOUS_MIGRATION_NAME
```

## Weekly Scheduled Tasks

These are configured in Celery Beat (`config/celery.py`):

| Task | Celery Task Path | Schedule | Queue | What It Does |
|------|-----------------|----------|-------|-------------|
| Weekly Drift Report | `apps.ml_engine.tasks.compute_weekly_drift_report` | Monday 2:00 AM | `ml` | PSI analysis for model drift detection |
| Guardrail Analytics | `apps.email_engine.tasks.compute_guardrail_analytics` | Monday 3:00 AM | `email` | Guardrail pass/fail rates and trends |
| Pipeline SLA | `apps.agents.tasks.compute_pipeline_sla` | Monday 4:00 AM | `agents` | Pipeline step timing analysis |

To verify beat is scheduling correctly:
```bash
docker logs loan-approval-ai-system-celery_beat-1 --tail 20
```

## Escalation Matrix

| Severity | Condition | Action |
|----------|-----------|--------|
| **P1 Critical** | Service down, no predictions possible; Health Check Failing alert | Restart services immediately, page on-call |
| **P2 High** | Model drift detected (PSI > 0.25); High Error Rate alert | Retrain model within 24 hours; investigate error source |
| **P3 Medium** | Guardrail fail rate > 20%; High API Latency alert | Review prompt templates; investigate slow queries |
| **P4 Low** | Celery Queue Backlog alert; minor email fallbacks | Monitor, scale workers if persistent |

## Bias Detection Escalation

When the bias detection pipeline flags an email:
1. Junior analyst (Claude Sonnet) classifies each flag
2. Senior reviewer (Claude Opus) performs holistic review
3. If confidence < 0.70 OR approved=False, the run enters the **human review queue**
4. Human reviewer accesses `/dashboard/human-review` in the frontend to make the final decision
5. Staff submits review via `POST /api/v1/agents/review/<run_id>/`
6. Decision is logged in BiasReport with reviewer ID

## Environment Variables

Key variables (stored in `.env` at project root, never commit):

| Variable | Purpose |
|----------|---------|
| `POSTGRES_DB` | Database name (default: `loan_approval`) |
| `POSTGRES_USER` | Database user (default: `postgres`) |
| `POSTGRES_PASSWORD` | Database password |
| `REDIS_PASSWORD` | Redis auth password |
| `DJANGO_SETTINGS_MODULE` | Settings module (default: `config.settings.development`) |
| `CELERY_BROKER_URL` | Auto-set in docker-compose: `redis://:$REDIS_PASSWORD@redis:6379/0` |
| `ANTHROPIC_API_KEY` | Claude API key for email generation and bias detection |

### 8. Claude API Extended Outage

**Symptoms:** All pipeline runs fail at the `email_generation` or `bias_detection` step. Circuit breaker trips open. `AgentRun.status = 'failed'` with Claude API errors in the step log. Template fallback emails may be sending instead of AI-generated ones.

**Diagnosis:**
```bash
# Check API budget stats and circuit breaker state
docker compose exec backend python manage.py shell -c "
from apps.agents.services.api_budget import ApiBudgetGuard
print(ApiBudgetGuard().get_daily_stats())
"

# Check Anthropic status page
# https://status.anthropic.com

# Check circuit breaker directly in Redis
docker compose exec redis redis-cli -a $REDIS_PASSWORD GET ai_budget:circuit_breaker
```

**Impact:**
- **Decision emails (approval/denial):** Template fallback activates automatically. Emails still go out using static templates — no customer-facing disruption for decision notifications.
- **NBO and marketing pipeline:** Produces no output. Denied applicants do not receive alternative product offers until the API recovers.
- **Bias detection:** Defaults to a score of 65 (moderate flag). Emails that would normally pass AI review are held for human review instead.

**Resolution:**
```bash
# 1. Check if this is an Anthropic-side outage — if so, wait for resolution
#    Monitor https://status.anthropic.com

# 2. If the outage is resolved but circuit breaker is still open, reset manually
docker compose exec redis redis-cli -a $REDIS_PASSWORD DEL ai_budget:circuit_breaker

# 3. Verify recovery by triggering a single orchestration
curl -X POST http://localhost:8000/api/v1/agents/orchestrate/<loan_id>/ \
  -H "Cookie: access_token=<token>"

# 4. Confirm the agent run completed without Claude API errors
docker compose exec backend python manage.py shell -c "
from apps.agents.models import AgentRun
run = AgentRun.objects.order_by('-created_at').first()
print(f'Status: {run.status}')
print(f'Steps: {run.steps}')
"
```

## Pre-Activation Gate Enablement

Three opt-in env-var-driven gates control model and prediction safety. Each
defaults to a non-blocking mode so deployments ship zero behaviour change;
flip to enforcing modes only after confirming the prerequisites below.

| Variable | Default | Enforcing value | Effect when enforcing |
|---|---|---|---|
| `ML_FAIRNESS_GATE_MODE` | `warn` | `block` | `train_model_task` refuses activation if the EEOC 80% rule fails for any protected attribute, or if `metrics["fairness"]` is empty. Old segment models keep `is_active=True`; no zero-model gap. |
| `ML_PROMOTION_GATE_MODE` | `warn` | `block` | `train_model_task` refuses activation if `model_selector.promote_if_eligible` reports any of the four champion-challenger gates failed (KS regression, PSI stability, ECE calibration, AUC regression). |
| `CREDIT_POLICY_OVERLAY_MODE` | `shadow` | `enforce` | `apply_overlay_to_decision` overrides the model verdict on every prediction when policy rules trigger (P-codes in `services/credit_policy.py`). Shadow mode logs the would-be override but returns the model verdict; enforce mode actually applies it. |
| `DECISION_OVERTURN_GATE_MODE` | `off` | `2fa` / `second_approver` | Maker/checker control on officer overturns of denials at/above `DECISION_OVERTURN_THRESHOLD` (default `$100,000`). `2fa` requires the acting officer to hold a verified TOTP device (returns HTTP 403 otherwise); `second_approver` blocks high-value overturns at the API pending an out-of-band dual-approval process. Below-threshold overturns are never gated. Residual accepted risk in `off` mode: any officer-role account can self-overturn any denial within throttle limits (detective AuditLog only). |

The first two gate `train_model_task` (rare event — runs on retraining
cadence). The third gates **every prediction** that hits the policy overlay,
so its blast radius is broader and rollout deserves more care.

### Prerequisite checklist — `ML_FAIRNESS_GATE_MODE=block`

- [ ] Recent training runs produce `metrics["fairness"]` with all protected
      attributes recorded. Verify by inspecting
      `mv.training_metadata["fairness_gate"]` on the most recent active
      `ModelVersion` in each segment.
- [ ] Every currently-active model passes the EEOC 80% rule. Review the
      §1 Header `Compliance status` line in each active model's MRM
      dossier (`python manage.py generate_mrm_dossier <model_id>`) — if
      any show `NON-COMPLIANT` for fairness, retrain *before* flipping
      to `block`. The runtime gate runs on new training only and will not
      retroactively deactivate existing failing models, but operators
      should not be flying blind on the existing ones either.
- [ ] On-call alerting picks up `FairnessGateBlocked` Celery task
      failures (the exception subclass is `RuntimeError` so any generic
      Celery-failure alert catches it; you may want a dedicated alert
      that names the env var so the on-call sees the remediation path).
- [ ] Documented rollback acknowledged: set `ML_FAIRNESS_GATE_MODE=warn`
      and restart the `worker_ml` Celery worker.

### Prerequisite checklist — `ML_PROMOTION_GATE_MODE=block`

- [ ] Trainer emits `training_metadata.psi_by_feature` on every run
      (introduced in v1.9.9). Verify on the most recent training run.
- [ ] `metrics["calibration_data"]["ece"]` is populated (introduced
      pre-v1.9.0; legacy models without it will fail Gate 3).
- [ ] At least one champion exists per segment you train, OR you are
      okay with first-model-in-segment auto-promotion after PSI+ECE
      pass (the gate short-circuits Gates 1+4 in this case).
- [ ] Documented rollback acknowledged: set `ML_PROMOTION_GATE_MODE=warn`
      and restart the `worker_ml` Celery worker.

### Prerequisite checklist — `CREDIT_POLICY_OVERLAY_MODE=enforce`

This one is **not** purely an ML concern — the policy overlay can flip a
model `approved` to a hard `decline` (or vice versa for hard-pass rules).
Customer-facing impact is real.

- [ ] Shadow-mode telemetry has been collected for **at least four weeks**
      (or one full training cycle, whichever is longer). Review
      `PolicyOverlayDecision` rows or whatever observability surface the
      shadow-mode logs land in. Confirm the per-rule trigger rate matches
      expectations and there are no obvious false positives.
- [ ] Each P-code in `services/credit_policy.POLICY_RULES` has been
      reviewed by Compliance + Product for AU regulatory alignment.
      Hard-fail rules (P04 ATO tax-debt default, etc.) must be confirmed
      acceptable as decline drivers.
- [ ] Customer-facing decline messaging is in place for blocked
      predictions. The MRM dossier §2 wording will switch from
      "policy overlay runs in `shadow` (observational) mode" to
      "policy overlay runs in `enforce` mode" automatically — but the
      *email content* sent to declined customers is owned by
      `email_engine` and must reference policy-driven declines properly
      (see `email_engine/services/template_fallback.py` denial templates).
- [ ] On-call alerting picks up an unexpected spike in policy-driven
      declines (e.g. >20% of decisions in any 1-hour window). A bad rule
      could cause mass declines; an alert short-circuits the blast.
- [ ] Documented rollback acknowledged: set
      `CREDIT_POLICY_OVERLAY_MODE=shadow` and restart the backend +
      Celery workers (or `off` if you suspect a code-level overlay bug
      and need to bypass entirely while you investigate).

### Enablement procedure

1. Confirm all prerequisites for the gate you're enabling.
2. Update the deployment env file (or your secrets manager) with the new
   value. Do **not** edit `backend/config/settings/base.py` — the default
   stays at the safe value so a misconfigured deployment doesn't silently
   downgrade.
3. Restart the affected services:
   - `ML_FAIRNESS_GATE_MODE` and `ML_PROMOTION_GATE_MODE`: restart `worker_ml`
     (the Celery worker that runs `train_model_task`).
   - `CREDIT_POLICY_OVERLAY_MODE`: restart `backend` + all Celery workers
     (the setting is read on every prediction, but workers cache the
     resolved settings module on import).
4. Trigger a smoke test:
   - Fairness/promotion: kick off a training run via
     `POST /api/v1/ml/models/train/` and verify the resulting
     `mv.training_metadata.{fairness_gate_mode,promotion_gate_mode}` reflects
     the new mode. If `block` mode rejects the run, that is the gate working
     as intended — review the failure reasons before flipping back.
   - Overlay: hit a known out-of-scope application via the predictions
     endpoint and verify the response carries the policy-overlay decision
     in the audit log.
5. Monitor for 24 hours before considering the rollout permanent. The
   safe rollback is a one-line env-var change — there is no DB state or
   migration to worry about.

### Rollback

Set the relevant env var back to its safe default and restart the affected
services (see step 3 above):

| Variable | Safe default |
|---|---|
| `ML_FAIRNESS_GATE_MODE` | `warn` |
| `ML_PROMOTION_GATE_MODE` | `warn` |
| `CREDIT_POLICY_OVERLAY_MODE` | `shadow` |
| `DECISION_OVERTURN_GATE_MODE` | `off` |

Currently-active models with failed gates remain active across the flip —
the rollback path is symmetric with the enablement path. There is no
data-migration step.

The code paths for the safe defaults are byte-identical to the pre-gate
behaviour shipped before PRs #163 and #164, so reverting should never
introduce new failure modes — only remove the gate's protection.

**Prevention:** The circuit breaker auto-recovers after a 10-minute cooldown period (`AI_CIRCUIT_BREAKER_COOLDOWN = 600`). Template fallback ensures decision emails always go out regardless of API availability. The daily API budget (500 calls / $50 USD) resets at midnight UTC.
