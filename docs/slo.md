# Service level indicators & objectives

SLIs (what we measure) and SLOs (what we promise). These are realistic targets for the current system, not aspirational ones. Aspirational targets get ignored.

This is the single home for service levels. It also holds the sections that used to be a separate service level agreement: service-wide targets, error budget policy, alert mapping, incident response times, secrets rotation, capacity planning and maintenance windows. Where the two documents disagreed, both values are kept and marked **Open question**.

## SLI catalogue

### API availability

**SLI:** % of HTTP requests to `/api/v1/` with status < 500 (per 5-minute window).

**Measurement:** `django_http_responses_total_by_status` (django-prometheus).

**SLO target:** 99.5% over any 30-day rolling window.

**Error budget:** 30 days × 0.5% = 3.6 hours of downtime per month.

**Alert:** page when burn rate > 10× for 1 hour (burning the month's budget in 3 days).

**Open question:** the [service-wide targets](#service-wide-targets) below set API availability at 99.9% over a rolling 30 days, measured as successful health check probes, with a 43.2-minute monthly error budget. This section sets 99.5%, measured on `/api/v1/` responses, with a 3.6-hour budget. One target and one measurement need to be chosen.

---

### Application submission latency

**SLI:** p95 latency of `POST /api/v1/applications/` (time from request start to the 202 response; queueing is async, so this covers only the API part).

**Measurement:** `django_http_requests_latency_seconds_by_view_method` filtered to the applications view.

**SLO target:** p95 < 500 ms, p99 < 1500 ms.

**Alert:** page when p95 > 1 s for 15 minutes.

---

### Decision pipeline end-to-end latency

**SLI:** time from application submission to decision persisted (all 6 pipeline stages).

**Measurement:** custom histogram `pipeline_e2e_seconds{status,decision}`, observed in `apps.agents.services.step_tracker.StepTracker.finalize_run` on every terminal run (completed / failed / escalated). Buckets: 1-120 s.

**SLO target:** p95 < 30 s, p99 < 60 s.

**Alert:** page when p95 > 60 s for 30 minutes.

---

### Email generation success rate

**SLI:** % of email generation tasks that complete without guardrail failure or Claude API error.

**Measurement:** custom counter `email_generation_total{decision,source,status}` where `status` is `success` | `guardrail_fail`. Emitted from `apps.email_engine.services.email_generator.EmailGenerator.generate` on every return path (claude_api + template_fallback sources).

**SLO target:** 98.0%.

**Error budget:** 2% per month, so roughly 1 in 50 applications can fall back to human review without burning the budget.

---

### ML prediction success rate

**SLI:** % of prediction tasks that return a probability without exception.

**Measurement:** counter `ml_predictions_total{decision,model_version}` + histogram `ml_prediction_latency_seconds{algorithm}`, both emitted in `apps.ml_engine.services.predictor.ModelPredictor`. The `algorithm` label lets the Grafana latency panel show xgboost / rf / logistic models separately.

**SLO target:** 99.9%.

---

### Bias review escalation rate

**SLI:** % of emails that get escalated to human review via the bias pipeline.

**Measurement:** counter `bias_review_total{outcome}` + histogram `bias_review_ttr_seconds{decision}` (time-to-resolution for escalated applications). Emitted from `apps.agents.services.human_review_handler.HumanReviewHandler.resume_after_review`.

**SLO target:** not a latency/error SLO; tracked as a business quality signal. Alert on > 15% weekly (a sign that the pre-screen or the model is drifting).

---

## Service-wide targets

These targets took effect on 2026-03-23 and are reviewed quarterly.

| Metric | Target | Measurement Window |
|--------|--------|--------------------|
| API availability | 99.9% | Rolling 30 days |
| Prediction latency (p95) | < 2 seconds | Rolling 5 minutes |
| Email generation (p95) | < 30 seconds | Rolling 5 minutes |
| Bias review (p95) | < 60 seconds | Rolling 5 minutes |
| Health check response (p95) | < 200 ms | Rolling 1 minute |
| Error rate (5xx) | < 1% | Rolling 5 minutes |

### Definitions

- **Availability** is measured as the percentage of successful health check probes over total probes in a 30-day window.
- **Latency** is measured at the server side (from request received to response sent), excluding network transit.
- **Error rate** counts only server errors (HTTP 5xx). Client errors (4xx) are excluded.

**Open question:** the error rate target is < 1% over 5 minutes, but the `HighErrorRate` alert in the [SLO-to-alert mapping](#slo-to-alert-mapping) fires at > 0.05 (5%) over 2 minutes. The target and the alert threshold need to be reconciled.

---

## Error budget

This budget follows from the 99.9% availability target. The API availability SLI above uses 99.5% and a 3.6-hour budget; see the open question there.

| Parameter | Value |
|-----------|-------|
| Monthly budget | 0.1% of total minutes = **43.2 minutes** |
| Calculation | 30 days x 24 hours x 60 minutes x 0.001 |
| Tracking | Grafana dashboard "SLO / Error Budget" |

### Error budget policy

| Budget remaining | Action |
|-----------------|--------|
| > 50% | Normal development velocity. Ship features freely. |
| 25%-50% | Increase review rigour. Require load test pass before deploy. |
| 5%-25% | Freeze non-critical deploys. Prioritise reliability work. |
| 0%-5% (exhausted) | **Full deployment freeze.** All engineering effort shifts to reliability until budget recovers. |

---

## SLO-to-alert mapping

| SLO | Grafana Alert Name | Condition | For |
|-----|--------------------|-----------|-----|
| API availability | `HealthCheckFailing` | `up < 1` | 1 min |
| Prediction latency | `HighPredictionLatency` | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{endpoint="/api/v1/ml/predict/"}[5m])) > 2` | 5 min |
| Email generation | `SlowEmailGeneration` | `celery_task_duration_seconds{task="email_engine.generate", quantile="0.95"} > 30` | 5 min |
| Error rate | `HighErrorRate` | `rate(http_responses_total{status=~"5.."}[2m]) / rate(http_responses_total[2m]) > 0.05` | 2 min |
| Health check response | `SlowHealthCheck` | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{endpoint="/api/v1/health/"}[1m])) > 0.2` | 1 min |

### Notification channels

- **P1/P2**: PagerDuty on-call rotation + Slack `#incidents`
- **P3/P4**: Slack `#alerts` only

**Open question:** [Alert routing](#alert-routing) below sends pages to PagerDuty in prod and Discord in dev, and tickets to GitHub Issues. These channels name PagerDuty plus Slack `#incidents` and Slack `#alerts`. One routing scheme needs to be chosen.

---

## Incident response times

| Severity | Description | Response Time | Resolution Target | Examples |
|----------|-------------|---------------|-------------------|----------|
| **P1 Critical** | Service is down or data integrity at risk | 15 minutes | 4 hours | Database unreachable, all predictions failing, data breach |
| **P2 High** | Major feature degraded, workaround exists | 1 hour | 24 hours | Email generation failing, bias detection timeout, auth broken |
| **P3 Medium** | Minor feature issue, most users unaffected | 4 hours | 72 hours | Dashboard chart not loading, single endpoint slow |
| **P4 Low** | Cosmetic issue or improvement request | 24 hours | 1 week | Typo in email template, non-critical log noise |

### Escalation path

1. On-call engineer acknowledges alert
2. If not resolved within 50% of resolution target, escalate to tech lead
3. If not resolved within 75% of resolution target, escalate to engineering manager
4. Post-incident review (PIR) required for all P1 and P2 incidents within 48 hours

---

## Secrets rotation schedule

| Secret | Rotation Frequency | Method |
|--------|-------------------|--------|
| `DJANGO_SECRET_KEY` | Every 90 days | Generate new key, rolling restart of all backend pods |
| `ANTHROPIC_API_KEY` | Every 90 days | Rotate in Anthropic console, update K8s secret, restart email/agent workers |
| `POSTGRES_PASSWORD` | On incident or annually | Update RDS master password, roll credentials in K8s, restart backend |
| `REDIS_PASSWORD` | On incident or annually | Update ElastiCache auth token, restart Celery workers |
| `FIELD_ENCRYPTION_KEY` | Annually | MultiFernet supports key rotation: add new key as primary, keep old as secondary for decryption |
| JWT signing key | Derived from `DJANGO_SECRET_KEY` | Rotates with Django secret key. Existing tokens invalidated on rotation. |

### Rotation procedure

1. Generate new secret value
2. Update the secret in the secrets manager (K8s Secret or AWS Secrets Manager)
3. Perform rolling restart of affected services
4. Verify health checks pass on all pods
5. Monitor error rate for 15 minutes post-rotation
6. Remove old secret value after confirmation period (24 hours for encryption keys)

**Open question:** the [secrets rotation runbook](../backend/docs/SECRETS_ROTATION.md) gives different frequencies: `POSTGRES_PASSWORD` and `REDIS_PASSWORD` every 90 days (here: on incident or annually), and `FIELD_ENCRYPTION_KEY` every 180 days or on compromise (here: annually). It also lists `EMAIL_HOST_PASSWORD` at 180 days, which this table omits. One schedule needs to be chosen.

---

## Capacity planning

### Current baseline (development)

| Resource | Configuration |
|----------|--------------|
| Backend replicas | 2 |
| Celery ML workers | 2 replicas x 2 concurrency = 4 parallel predictions |
| Celery IO workers | 3 replicas x 4 concurrency = 12 parallel email/agent tasks |
| Database | RDS `db.t3.micro` |
| Redis | ElastiCache `cache.t3.micro` |
| Concurrent users | 50 |
| Throughput | 50 req/s |

### Production recommendations

| Resource | Configuration | Scaling Trigger |
|----------|--------------|-----------------|
| Backend replicas | 2-10 via K8s HPA | CPU > 70% avg over 2 min |
| Celery ML workers | 2-6 via KEDA | Queue depth > 10 for 1 min |
| Celery IO workers | 3-10 via KEDA | Queue depth > 20 for 1 min |
| Database | RDS `db.r6g.large` + read replica | Connections > 80% max |
| Redis | ElastiCache `cache.r6g.large` | Memory > 75% |

### Growth projections

| Metric | Current | 6-month target | 12-month target |
|--------|---------|----------------|-----------------|
| Concurrent users | 50 | 200 | 500 |
| Daily applications | 100 | 500 | 2,000 |
| Throughput (req/s) | 50 | 200 | 500 |
| Storage (DB) | 1 GB | 10 GB | 50 GB |

### Load test validation

Run load tests (see `tests/load/`: k6 in CI, Locust in `tests/load/locust/`) before every production deploy that changes:
- Database queries or schema
- Celery task logic
- Authentication flow
- Any endpoint in the critical path (predict, email generate, bias detect)

---

## Maintenance windows

| Window | Schedule | Impact |
|--------|----------|--------|
| Planned maintenance | Sundays 02:00-04:00 AEST | Rolling restarts, zero downtime target |
| Database maintenance | First Sunday of month, 03:00-04:00 AEST | Possible brief read-only period |
| Emergency maintenance | As needed | Communicated via status page within 5 minutes |

Planned maintenance windows do **not** count against the error budget.

---

## What's not an SLO yet

- **Cost per decision:** tracked internally, but no SLO. Claude API pricing dominates; the template-first strategy caps at $5/day.
- **Model AUC:** tracked per `ModelVersion`; the rollback threshold is AUC < 0.82, but it is not SLO-enforced in prod.
- **Disk / memory utilisation:** covered by infra alerting, not a customer-facing SLO.

## How targets get set or moved

1. Measure actual performance for 4 weeks.
2. Set the target at p95 of observed performance, not worst case.
3. Review targets quarterly. Missed targets become engineering work, not target adjustments. The exception is a target that was wrong; in that case, document why in a new revision of this file.

## Alert routing

| Severity | Channel | Response |
|----------|---------|----------|
| Page | PagerDuty (prod) / Discord (dev) | Owner acknowledges within 15 min |
| Ticket | GitHub Issues with `incident` label | Triaged next business day |
| Ambient | Grafana dashboard | Reviewed weekly |

---

## Revision history

| Date | Change | Author |
|------|--------|--------|
| 2026-03-23 | Initial SLA document | Engineering team |
