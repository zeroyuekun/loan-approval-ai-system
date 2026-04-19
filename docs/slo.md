# Service Level Indicators & Objectives

SLIs (what we measure) and SLOs (what we promise). These are realistic targets for the current system, not aspirational — aspirational targets get ignored.

## SLI catalogue

### API availability

**SLI:** % of HTTP requests to `/api/v1/` with status < 500 (per 5-minute window).

**Measurement:** `django_http_responses_total_by_status` (django-prometheus).

**SLO target:** 99.5% over any 30-day rolling window.

**Error budget:** 30 days × 0.5% = 3.6 hours of downtime per month.

**Alert:** page when burn rate > 10× for 1 hour (burning the month's budget in 3 days).

---

### Application submission latency

**SLI:** p95 latency of `POST /api/v1/applications/` (time from request start to 202 response — queueing is async, this is just the API part).

**Measurement:** `django_http_requests_latency_seconds_by_view_method` filtered to the applications view.

**SLO target:** p95 < 500 ms, p99 < 1500 ms.

**Alert:** page when p95 > 1 s for 15 minutes.

---

### Decision pipeline end-to-end latency

**SLI:** time from application submission to decision persisted (all 6 pipeline stages).

**Measurement:** custom histogram `pipeline_e2e_seconds{status,decision}` — observed in `apps.agents.services.step_tracker.StepTracker.finalize_run` on every terminal run (completed / failed / escalated). Buckets: 1 – 120 s.

**SLO target:** p95 < 30 s, p99 < 60 s.

**Alert:** page when p95 > 60 s for 30 minutes.

---

### Email generation success rate

**SLI:** % of email generation tasks that complete without guardrail failure or Claude API error.

**Measurement:** custom counter `email_generation_total{decision,source,status}` where `status` is `success` | `guardrail_fail`. Emitted from `apps.email_engine.services.email_generator.EmailGenerator.generate` on every return path (claude_api + template_fallback sources).

**SLO target:** 98.0%.

**Error budget:** 2% per month — roughly 1 in 50 applications can fall back to human review without burning the budget.

---

### ML prediction success rate

**SLI:** % of prediction tasks that return a probability without exception.

**Measurement:** counter `ml_predictions_total{decision,model_version}` + histogram `ml_prediction_latency_seconds{algorithm}` — both emitted in `apps.ml_engine.services.predictor.ModelPredictor`. `algorithm` label lets the Grafana latency panel segment xgboost / rf / logistic models separately.

**SLO target:** 99.9%.

---

### Bias review escalation rate

**SLI:** % of emails that get escalated to human review via the bias pipeline.

**Measurement:** counter `bias_review_total{outcome}` + histogram `bias_review_ttr_seconds{decision}` (time-to-resolution for escalated applications). Emitted from `apps.agents.services.human_review_handler.HumanReviewHandler.resume_after_review`.

**SLO target:** not a latency/error SLO — tracked as a business quality signal. Alert on > 15% weekly (indicates the pre-screen or the model are drifting).

---

## What's NOT an SLO yet

- **Cost per decision** — tracked internally but no SLO. Claude API pricing dominates; template-first strategy caps at $5/day.
- **Model AUC** — tracked per `ModelVersion`; rollback threshold is AUC < 0.82 but not SLO-enforced in prod.
- **Disk / memory utilisation** — covered by infra alerting, not customer-facing SLO.

## How targets get set or moved

1. Measure actual performance for 4 weeks.
2. Set the target at p95 of observed performance, not worst case.
3. Review targets quarterly. Missed targets become engineering work, not target adjustments — unless the target was wrong, in which case document why in a new revision of this file.

## Alert routing

| Severity | Channel | Response |
|----------|---------|----------|
| Page | PagerDuty (prod) / Discord (dev) | Owner acknowledges within 15 min |
| Ticket | GitHub Issues with `incident` label | Triaged next business day |
| Ambient | Grafana dashboard | Reviewed weekly |
