# Load Test Baseline

Baseline performance targets and load testing procedures for the Loan Approval AI System.

Last updated: 2026-03-30

---

## Test Script

The k6 load test script lives at:

```
tests/load/pipeline_load_test.js
```

It is also run automatically in CI on pushes to `master` (see `.github/workflows/ci.yml`, job `load-test`).

---

## Test Configuration

### Scenarios

| Scenario | Type | VUs | Duration | Purpose |
|----------|------|-----|----------|---------|
| Smoke | constant-vus | 5 | 30s | Verify basic functionality under minimal load |
| Load | ramping-vus | 0 -> 20 -> 50 -> 0 | ~2m30s (starts after smoke) | Simulate realistic traffic with ramp-up and peak |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `http://localhost:8500` | Backend URL |
| `TEST_USERNAME` | `admin` | Admin user for authenticated endpoints |
| `TEST_PASSWORD` | `admin123` | Admin user password |

---

## Endpoints Tested

| Group | Endpoint | Method | Auth | Description |
|-------|----------|--------|------|-------------|
| Health check | `/api/v1/health/ready/` | GET | No | Readiness probe |
| Authentication | `/api/v1/auth/login/` | POST | No | JWT/session login |
| List applications | `/api/v1/loans/applications/?page=1` | GET | Yes | Paginated loan list (read-heavy) |
| Trigger pipeline | `/api/v1/agents/orchestrate/{id}/` | POST | Yes | Queue orchestration pipeline (ML + LLM) |
| Poll task status | `/api/v1/tasks/{task_id}/status/` | GET | Yes | Poll Celery task result |

---

## How to Run Locally

### Prerequisites

1. Install k6: https://k6.io/docs/getting-started/installation/
2. Start the backend stack (Django + PostgreSQL + Redis + Celery):
   ```bash
   docker compose up -d --wait
   ```
3. Seed an admin user:
   ```bash
   docker compose exec backend python manage.py shell -c "
   from apps.accounts.models import CustomUser
   if not CustomUser.objects.filter(username='admin').exists():
       CustomUser.objects.create_superuser('admin', 'admin@test.com', 'admin123', role='admin')
   "
   ```
4. Seed at least one loan application so the pipeline trigger test has data.

### Run smoke test (quick validation)

```bash
k6 run tests/load/pipeline_load_test.js --duration 30s --vus 5
```

### Run full load test

```bash
k6 run tests/load/pipeline_load_test.js
```

### Run with custom settings

```bash
k6 run --vus 50 --duration 2m tests/load/pipeline_load_test.js
```

### Run against a different host

```bash
k6 run tests/load/pipeline_load_test.js \
  --env BASE_URL=http://staging.example.com:8500 \
  --env TEST_USERNAME=testadmin \
  --env TEST_PASSWORD=secret
```

### Save results to JSON

```bash
mkdir -p tests/load/results
k6 run tests/load/pipeline_load_test.js \
  --out json=tests/load/results/k6-output.json
```

The script also writes a summary to `tests/load/results/summary.json` via the `handleSummary` hook.

---

## Baseline SLA Targets

These are the performance targets the system must meet. Thresholds are enforced in the k6 script -- breaching them causes the test to fail.

### Response Time (p95)

| Endpoint Category | p95 Target | Rationale |
|-------------------|------------|-----------|
| Health check | < 200ms | Simple DB/Redis connectivity check |
| Read endpoints (list applications) | < 500ms | Paginated DB query with select_related |
| Authentication (login) | < 1000ms | Password hashing + JWT generation |
| Pipeline trigger (queue) | < 500ms | Only queues a Celery task, does not wait for completion |
| ML prediction (end-to-end) | < 2000ms | Random Forest / XGBoost inference on a single application |
| Email generation (end-to-end) | < 5000ms | Claude API call for email text generation |

Notes on ML and email targets:
- The pipeline trigger endpoint returns 202 immediately after queuing. The ML and email SLAs apply to the Celery task execution time, not the HTTP response.
- ML prediction latency depends on model size and feature computation. The 2s target assumes a warm model in memory.
- Email generation latency is dominated by the Claude API round-trip. The 5s target accounts for network latency and token generation.

### Error Rate

| Metric | Target | Notes |
|--------|--------|-------|
| HTTP error rate | < 1% | Measured across all endpoints |
| Pipeline queue success rate | > 95% | Percentage of pipeline triggers that return 202 |

### Throughput

| Endpoint Category | Target | Notes |
|-------------------|--------|-------|
| Read endpoints | > 50 req/s | Sustained under 20 concurrent VUs |
| Write endpoints | > 10 req/s | Pipeline triggers under load |

---

## How to Interpret Results

### k6 Output Metrics

After a run, k6 prints a summary. Key metrics to review:

| Metric | What it means |
|--------|---------------|
| `http_req_duration` | Overall request latency distribution (avg, p90, p95, p99) |
| `http_req_failed` | Percentage of requests that returned non-2xx status |
| `http_reqs` | Total request count and requests/second |
| `health_check_duration` | Custom metric: health endpoint latency |
| `login_duration` | Custom metric: authentication latency |
| `application_list_duration` | Custom metric: list applications latency |
| `pipeline_trigger_duration` | Custom metric: pipeline queue latency |
| `pipeline_queued_success` | Custom metric: rate of successful pipeline triggers |
| `iteration_duration` | Time for one full VU iteration (all groups) |

### Pass / Fail

The k6 script defines thresholds that map to the SLA targets above. If any threshold is breached, k6 exits with a non-zero code and prints which thresholds failed. In CI, the load test job uses `continue-on-error: true` so it does not block the pipeline, but results are uploaded as artifacts for review.

### JSON Summary

The `handleSummary` hook writes a structured JSON file to `tests/load/results/summary.json` with:

```json
{
  "timestamp": "2026-03-30T12:00:00.000Z",
  "sla_targets": {
    "health_p95": 200,
    "login_p95": 1000,
    "application_list_p95": 500,
    "pipeline_trigger_p95": 500
  },
  "results": {
    "health_p95": null,
    "login_p95": null,
    "application_list_p95": null,
    "pipeline_trigger_p95": null,
    "pipeline_success_rate": null,
    "http_error_rate": null
  },
  "total_requests": 0,
  "total_duration": null
}
```

Compare `results` values against `sla_targets` to identify regressions.

---

## Baseline Results

> Results have not yet been captured against localhost:8500. Run the load test locally and update this section with actual numbers.

### Placeholder

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Health check p95 | -- | < 200ms | -- |
| Login p95 | -- | < 1000ms | -- |
| Application list p95 | -- | < 500ms | -- |
| Pipeline trigger p95 | -- | < 500ms | -- |
| Pipeline queue success rate | -- | > 95% | -- |
| HTTP error rate | -- | < 1% | -- |
| Total requests | -- | -- | -- |
| Requests/second (sustained) | -- | > 50 req/s (reads) | -- |

To fill in these results, run:

```bash
k6 run tests/load/pipeline_load_test.js
```

Then copy the p95 values from the console output or from `tests/load/results/summary.json`.

---

## CI Integration

The load test runs automatically in GitHub Actions on pushes to `master`:

- **Job**: `load-test` in `.github/workflows/ci.yml`
- **Trigger**: Only on `master` branch pushes (not on PRs)
- **Profile**: Smoke test only (5 VUs, 30s) to keep CI fast
- **Artifacts**: Results uploaded to `load-test-results` artifact (retained 30 days)
- **Failure mode**: `continue-on-error: true` -- load test failures do not block deployment

### Running the Full Load Profile in CI

The CI job overrides the script to run a smoke-only profile. To run the full ramping profile, remove the `--duration 30s --vus 5` flags from the CI step.

---

## Scaling Considerations

- **Database connections**: At 50 VUs, each iteration opens a session. Ensure PostgreSQL `max_connections` can handle the load (default 100).
- **Celery workers**: Pipeline triggers queue Celery tasks. Under load, tasks may queue up if workers are saturated. Monitor `celery inspect active` during tests.
- **Redis**: Used as both Celery broker and cache. Watch memory usage under sustained load.
- **Claude API rate limits**: Email generation tasks call the Claude API. Under heavy pipeline load, rate limiting may cause email generation failures. The system has a $5/day cost cap.
- **Model warm-up**: First ML prediction after a cold start may exceed the 2s target due to model loading. Subsequent predictions should be within target.
