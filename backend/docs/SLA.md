# Service Level Agreement — AussieLoanAI

**Effective date:** 2026-03-23
**Review cadence:** Quarterly

---

## 1. Service Level Objectives (SLOs)

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

---

## 2. Error Budget

| Parameter | Value |
|-----------|-------|
| Monthly budget | 0.1% of total minutes = **43.2 minutes** |
| Calculation | 30 days x 24 hours x 60 minutes x 0.001 |
| Tracking | Grafana dashboard "SLO / Error Budget" |

### Error Budget Policy

| Budget remaining | Action |
|-----------------|--------|
| > 50% | Normal development velocity. Ship features freely. |
| 25%--50% | Increase review rigour. Require load test pass before deploy. |
| 5%--25% | Freeze non-critical deploys. Prioritise reliability work. |
| 0%--5% (exhausted) | **Full deployment freeze.** All engineering effort shifts to reliability until budget recovers. |

---

## 3. SLO-to-Alert Mapping

| SLO | Grafana Alert Name | Condition | For |
|-----|--------------------|-----------|-----|
| API availability | `HealthCheckFailing` | `up < 1` | 1 min |
| Prediction latency | `HighPredictionLatency` | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{endpoint="/api/v1/ml/predict/"}[5m])) > 2` | 5 min |
| Email generation | `SlowEmailGeneration` | `celery_task_duration_seconds{task="email_engine.generate", quantile="0.95"} > 30` | 5 min |
| Error rate | `HighErrorRate` | `rate(http_responses_total{status=~"5.."}[2m]) / rate(http_responses_total[2m]) > 0.05` | 2 min |
| Health check response | `SlowHealthCheck` | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{endpoint="/api/v1/health/"}[1m])) > 0.2` | 1 min |

### Notification Channels

- **P1/P2**: PagerDuty on-call rotation + Slack `#incidents`
- **P3/P4**: Slack `#alerts` only

---

## 4. Incident Response Times

| Severity | Description | Response Time | Resolution Target | Examples |
|----------|-------------|---------------|-------------------|----------|
| **P1 Critical** | Service is down or data integrity at risk | 15 minutes | 4 hours | Database unreachable, all predictions failing, data breach |
| **P2 High** | Major feature degraded, workaround exists | 1 hour | 24 hours | Email generation failing, bias detection timeout, auth broken |
| **P3 Medium** | Minor feature issue, most users unaffected | 4 hours | 72 hours | Dashboard chart not loading, single endpoint slow |
| **P4 Low** | Cosmetic issue or improvement request | 24 hours | 1 week | Typo in email template, non-critical log noise |

### Escalation Path

1. On-call engineer acknowledges alert
2. If not resolved within 50% of resolution target, escalate to tech lead
3. If not resolved within 75% of resolution target, escalate to engineering manager
4. Post-incident review (PIR) required for all P1 and P2 incidents within 48 hours

---

## 5. Secrets Rotation Schedule

| Secret | Rotation Frequency | Method |
|--------|-------------------|--------|
| `DJANGO_SECRET_KEY` | Every 90 days | Generate new key, rolling restart of all backend pods |
| `ANTHROPIC_API_KEY` | Every 90 days | Rotate in Anthropic console, update K8s secret, restart email/agent workers |
| `POSTGRES_PASSWORD` | On incident or annually | Update RDS master password, roll credentials in K8s, restart backend |
| `REDIS_PASSWORD` | On incident or annually | Update ElastiCache auth token, restart Celery workers |
| `FIELD_ENCRYPTION_KEY` | Annually | MultiFernet supports key rotation -- add new key as primary, keep old as secondary for decryption |
| JWT signing key | Derived from `DJANGO_SECRET_KEY` | Rotates with Django secret key. Existing tokens invalidated on rotation. |

### Rotation Procedure

1. Generate new secret value
2. Update the secret in the secrets manager (K8s Secret or AWS Secrets Manager)
3. Perform rolling restart of affected services
4. Verify health checks pass on all pods
5. Monitor error rate for 15 minutes post-rotation
6. Remove old secret value after confirmation period (24 hours for encryption keys)

---

## 6. Capacity Planning

### Current Baseline (Development)

| Resource | Configuration |
|----------|--------------|
| Backend replicas | 2 |
| Celery ML workers | 2 replicas x 2 concurrency = 4 parallel predictions |
| Celery IO workers | 3 replicas x 4 concurrency = 12 parallel email/agent tasks |
| Database | RDS `db.t3.micro` |
| Redis | ElastiCache `cache.t3.micro` |
| Concurrent users | 50 |
| Throughput | 50 req/s |

### Production Recommendations

| Resource | Configuration | Scaling Trigger |
|----------|--------------|-----------------|
| Backend replicas | 2--10 via K8s HPA | CPU > 70% avg over 2 min |
| Celery ML workers | 2--6 via KEDA | Queue depth > 10 for 1 min |
| Celery IO workers | 3--10 via KEDA | Queue depth > 20 for 1 min |
| Database | RDS `db.r6g.large` + read replica | Connections > 80% max |
| Redis | ElastiCache `cache.r6g.large` | Memory > 75% |

### Growth Projections

| Metric | Current | 6-month target | 12-month target |
|--------|---------|----------------|-----------------|
| Concurrent users | 50 | 200 | 500 |
| Daily applications | 100 | 500 | 2,000 |
| Throughput (req/s) | 50 | 200 | 500 |
| Storage (DB) | 1 GB | 10 GB | 50 GB |

### Load Test Validation

Run load tests (see `/loadtests/`) before every production deploy that changes:
- Database queries or schema
- Celery task logic
- Authentication flow
- Any endpoint in the critical path (predict, email generate, bias detect)

---

## 7. Maintenance Windows

| Window | Schedule | Impact |
|--------|----------|--------|
| Planned maintenance | Sundays 02:00--04:00 AEST | Rolling restarts, zero downtime target |
| Database maintenance | First Sunday of month, 03:00--04:00 AEST | Possible brief read-only period |
| Emergency maintenance | As needed | Communicated via status page within 5 minutes |

Planned maintenance windows do **not** count against the error budget.

---

## 8. Revision History

| Date | Change | Author |
|------|--------|--------|
| 2026-03-23 | Initial SLA document | Engineering team |
