# Fix 1 — Null Result: gunicorn workers 2 → 4

**Date:** 2026-04-15
**Hypothesis:** `tasks:status` RemoteDisconnected and `loans:create` bimodal latency are caused by gunicorn running with only 2 workers × 2 threads (4 concurrent slots) under 50 concurrent users.
**Change attempted:** Bump `GUNICORN_WORKERS` default from 2 to 4 in `docker-compose.yml`.

## Result: REVERTED

| Endpoint | Baseline (2W) p50 | Test (4W) p50 | Baseline p95 | Test p95 | Verdict |
|---|---:|---:|---:|---:|---|
| auth:login | 1300 ms | **23000 ms** | 1300 | **28000** | massive regression |
| loans:create | 93 | 140 | 1100 | 1100 | similar |
| ml:predict | 31 | 35 | 120 | 180 | slight worse |
| agents:orchestrate | 31 | 42 | 160 | 1400 | tail worse |
| tasks:status | 22 | 25 | 1000 | 1000 | same |
| Aggregate error rate | 1.06% | 0.92% | — | — | marginal improvement |

## Root cause of the regression

`Argon2PasswordHasher` is intentionally CPU-heavy (memory-hard KDF). On a 4-core dev machine, 2 gunicorn workers can serve Argon2 logins without thrashing. With 4 workers, simultaneous logins (50 users at spawn rate 5/sec) all hit Argon2 in parallel and contend on physical CPU cores. Login latency exploded ~18× from 1.3s to 23s.

The 4-worker change marginally helped concurrent-non-CPU-bound endpoints but the auth regression dominates.

## Decision

Reverted `GUNICORN_WORKERS` default to 2 in `docker-compose.yml`. Kept the env-configurability (the env var still exists, just defaults to the original value) so future tuning can experiment without re-editing files. The `Dockerfile` env-aware CMD is also retained because it's correct as a best practice even though `docker-compose.yml`'s `command:` overrides it.

## Lessons

1. **Worker count is bounded by physical cores under CPU-heavy work.** Adding workers past `cores * 1` for Argon2-bound paths makes things worse.
2. **Spawn rate matters in load tests.** Original baseline used `--spawn-rate 1` (50s ramp), spreading login over time. The 4-worker test used `--spawn-rate 5` (10s ramp), bunching logins. Bunching is more honest for measuring auth headroom; the original baseline's 1300ms login figure was an under-estimate.
3. **The right fix for `tasks:status` RemoteDisconnected is probably not more workers.** Could be `keepalive` timeout, gthread vs gevent, or accepting it as expected under burst load.

## Suggested follow-ups (not in this commit)

- Try `--worker-class gevent` (async) for IO-bound polling endpoints
- Investigate Argon2 parameters — Django's defaults are conservative for security and can be too slow for high-concurrency login
- Move bcrypt/Argon2 to a dedicated `auth` worker pool that's allowed to saturate without affecting other endpoints
