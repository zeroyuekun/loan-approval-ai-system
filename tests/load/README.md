# Load Tests

Locust scenarios against the Django+Celery stack.

## Prerequisites
- `docker compose up` must be running (all 8 core containers healthy)
- `pip install -r backend/requirements-dev.txt` in your Python env

## Smoke (30 s, 2 users) — MUST pass before any full run
```
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 2 --spawn-rate 1 --run-time 30s --headless
```
Expected: 0 errors.

## Baseline (10 min, 50 users)
```
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 50 --spawn-rate 1 --run-time 10m --headless \
  --html reports/baseline.html --csv reports/baseline
```
In a second terminal: `python tests/load/metrics_sampler.py --out reports/baseline-sampler.csv`
Stop the sampler with Ctrl+C when Locust finishes.

## Breakpoint (20 min ramp, 10 → 500 users)
```
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 500 --spawn-rate 0.4 --run-time 20m --headless \
  --html reports/breakpoint.html --csv reports/breakpoint
```
Stop manually (Ctrl+C) when error rate > 1% or median latency > 3× baseline.

## Test user
Requires a seeded account. Default creds are read from env vars
`LOAD_TEST_USER` and `LOAD_TEST_PASSWORD`. Seed via:
```
docker compose exec backend python manage.py shell -c "..."
```
(specific seed snippet documented in `tests/load/auth.py`).
