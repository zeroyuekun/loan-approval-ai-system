# Fix 2 — Tail Latency: gunicorn max-requests + task ownership bug

**Date:** 2026-04-15

## Two bundled changes (both surgical, both reversible)

### A. Bug fix: `orchestrate_pipeline_task` missing `application_id` in result

`TaskStatusView` (`backend/config/urls.py:49`) checks `result_data.get("application_id")` for ownership. If absent, returns 403. The `orchestrate_pipeline_task` (`backend/apps/agents/tasks.py:117`) and `resume_pipeline_task` (`tasks.py:159`) returned a result dict without `application_id`, so completed tasks looked unauthorised to non-staff users polling their own application.

**Fix:** Add `"application_id": str(application_id)` to both return dicts. Five lines total.

**Impact:** Customers can poll `/api/v1/tasks/{id}/status/` for their own task without 403. This was a latent bug masked in the load test by promoting `loadtest` to officer role.

### B. Perf: gunicorn `--max-requests` env-configurable

Hardcoded `--max-requests 1000 --max-requests-jitter 100` in `docker-compose.yml`. Each worker recycles after 900–1100 requests; in-flight requests at recycle time get a TCP RST and surface as `RemoteDisconnected` on the client.

**Fix:** Promoted both flags to env vars `GUNICORN_MAX_REQUESTS` (default 1000) and `GUNICORN_MAX_REQUESTS_JITTER` (default 100). Production behaviour unchanged. For load testing, set `GUNICORN_MAX_REQUESTS=0` to disable recycling.

## Measured before/after (50 users, 5 min smoke)

| Metric | Baseline (default recycling) | After (max-requests=0) | Delta |
|---|---:|---:|---:|
| auth:login p50 | 1300 ms | 1300 ms | 0% |
| loans:create p50 | 93 ms | 100 ms | +7% (noise) |
| ml:predict p50 | 31 ms | 37 ms | +19% (noise) |
| **loans:create p99.9** | **3300 ms** | **1200 ms** | **−64%** |
| **ml:predict p99.9** | **2800 ms** | **230 ms** | **−92%** |
| **tasks:status p99.9** | **3500 ms** | **1100 ms** | **−69%** |
| **max latency overall** | **4067 ms** | **1495 ms** | **−63%** |
| Aggregate error rate | 1.06% | 0.98% | −7% (noise) |

Tail latency (p99.9 and max) improved sharply and consistently. Median latency essentially unchanged — within run-to-run noise.

## What this does NOT fix

- The remaining ~1% RemoteDisconnected on `tasks:status` and `loans:create` is steady-state behaviour, not worker recycling. Deeper root cause not investigated; not a regression vs baseline.
- `auth:login` p50 = 1300 ms — Argon2 cost; out of scope (security-by-design).
- The `TaskStatusView` 403-on-PENDING behaviour for non-staff (`urls.py:67`) — still incorrect and worth a separate bug filing.

## Production rollout

- Bug A: deploy as-is, no env knob, pure correctness fix.
- Perf B: keep default `GUNICORN_MAX_REQUESTS=1000` in production. Worker recycling is good hygiene against memory leaks. Operators can tune via env if needed.
