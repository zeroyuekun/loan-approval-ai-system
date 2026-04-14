# Stress Test and Data-Driven Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible Locust stress-test suite against the Django+Celery stack, produce baseline and breakpoint metric reports, then apply up to three measured performance fixes.

**Architecture:** Locust virtual users exercise two real traffic patterns (quick score vs full orchestrated application) against a `docker compose` stack. A side sampler script collects Celery queue depth, Postgres connection count, and docker stats. Phase 2 fixes are gated on Phase 1 data.

**Tech Stack:** Locust, Django + DRF, Celery + Redis, Postgres, docker compose.

**Spec:** `docs/superpowers/specs/2026-04-14-stress-test-and-fixes-design.md`

---

## Real endpoints (verified from codebase 2026-04-14)

- Auth login: `POST /api/v1/auth/login/`
- Create loan: `POST /api/v1/loans/` (ViewSet)
- ML predict: `POST /api/v1/ml/predict/<uuid:loan_id>/`
- Orchestrate pipeline: `POST /api/v1/agents/orchestrate/<uuid:loan_id>/`
- Task status poll: `GET /api/v1/tasks/<task_id>/status/`
- Health check: `GET /api/v1/health/`

## File structure

```
tests/load/
  __init__.py
  locustfile.py          — Locust entry point, imports user classes
  users.py               — QuickScoreUser, FullApplicationUser
  payloads.py            — synthetic loan payload helpers
  auth.py                — login helper
  metrics_sampler.py     — side sampler for queue/db/docker metrics
  README.md              — run instructions

docs/load/
  baseline-2026-04-14.md
  breakpoint-2026-04-14.md
```

---

## Task 1: Add locust to dev dependencies

**Files:**
- Modify: `backend/requirements-dev.txt` (confirm path; fall back to `backend/requirements.txt` if no dev file exists)

- [ ] **Step 1: Locate the dev requirements file**

Run:
```bash
ls backend/requirements*.txt
```
Expected: at least one file listed. Use the one named `dev` if present, else `backend/requirements.txt`.

- [ ] **Step 2: Append locust pin**

Append one line to the file (replace `<path>` with the file found above):
```
locust==2.32.1
```

- [ ] **Step 3: Verify install in a throwaway venv**

Run:
```bash
python -m pip install --dry-run locust==2.32.1
```
Expected: "Would install locust-2.32.1"; no resolver error.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements-dev.txt
git commit -m "chore(deps): add locust for load testing"
```

---

## Task 2: Scaffold the load test directory

**Files:**
- Create: `tests/load/__init__.py` (empty)
- Create: `tests/load/README.md`

- [ ] **Step 1: Create directory and empty init**

Run:
```bash
mkdir -p tests/load && : > tests/load/__init__.py
```

- [ ] **Step 2: Write README with run instructions**

Create `tests/load/README.md` with content:
```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add tests/load/__init__.py tests/load/README.md
git commit -m "test(load): scaffold load test directory with README"
```

---

## Task 3: Implement auth helper

**Files:**
- Create: `tests/load/auth.py`

- [ ] **Step 1: Write the auth helper**

Create `tests/load/auth.py`:
```python
"""Login helper for load-test virtual users.

Reads credentials from env vars so no secrets end up in the repo.
"""
import os

LOGIN_PATH = "/api/v1/auth/login/"


def get_credentials() -> tuple[str, str]:
    user = os.environ.get("LOAD_TEST_USER")
    password = os.environ.get("LOAD_TEST_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "Set LOAD_TEST_USER and LOAD_TEST_PASSWORD env vars. "
            "Seed a test user via: docker compose exec backend python manage.py "
            "createsuperuser (or a dedicated management command)."
        )
    return user, password


def login(client) -> str:
    """POST login and return the bearer token. Raises on non-200."""
    user, password = get_credentials()
    resp = client.post(
        LOGIN_PATH,
        json={"username": user, "password": password},
        name="auth:login",
    )
    if resp.status_code != 200:
        raise RuntimeError(f"login failed: {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    # Accept either {access: ...} (SimpleJWT) or {token: ...}
    token = body.get("access") or body.get("token")
    if not token:
        raise RuntimeError(f"login returned no token: {body}")
    return token
```

- [ ] **Step 2: Verify import**

Run:
```bash
python -c "from tests.load.auth import login, get_credentials; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add tests/load/auth.py
git commit -m "test(load): add auth helper for load-test virtual users"
```

---

## Task 4: Implement synthetic payload helper

**Files:**
- Create: `tests/load/payloads.py`

- [ ] **Step 1: Inspect the real LoanApplication serializer**

Run:
```bash
grep -rn "class LoanApplicationSerializer\|class LoanApplicationCreateSerializer" backend/apps/loans/
```
Note the required fields from the serializer. The payload below covers the common AU loan fields — adjust during implementation if the serializer rejects any.

- [ ] **Step 2: Write the payload helper**

Create `tests/load/payloads.py`:
```python
"""Synthetic loan payloads for load testing.

Values are chosen from realistic AU ranges (matching ml_engine data_generator
distributions at a coarse level). Distributions are uniform — variance is not
the point here; throughput is.
"""
import random
import uuid


def loan_application_payload() -> dict:
    """A minimal-but-valid LoanApplication payload. Adjust to match serializer."""
    return {
        "loan_amount": random.choice([10000, 25000, 50000, 100000, 250000, 500000]),
        "loan_term_months": random.choice([12, 24, 36, 60, 84, 120, 240, 360]),
        "loan_purpose": random.choice(["car", "home", "personal", "debt_consolidation"]),
        "annual_income": random.randint(45000, 180000),
        "employment_type": random.choice(
            ["payg_permanent", "payg_casual", "self_employed", "contract"]
        ),
        "employment_length": random.randint(0, 25),
        "credit_score": random.randint(400, 850),
        "monthly_expenses": random.randint(1500, 6000),
        "existing_credit_card_limit": random.choice([0, 5000, 10000, 20000]),
        "number_of_dependants": random.choice([0, 0, 1, 2, 3]),
        "home_ownership": random.choice(["rent", "mortgage", "own"]),
        "state": random.choice(["NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"]),
        # Idempotency / uniqueness marker
        "client_ref": f"load-{uuid.uuid4().hex[:12]}",
    }
```

- [ ] **Step 3: Verify import**

Run:
```bash
python -c "from tests.load.payloads import loan_application_payload; print(loan_application_payload())"
```
Expected: a dict prints with the fields above.

- [ ] **Step 4: Commit**

```bash
git add tests/load/payloads.py
git commit -m "test(load): add synthetic loan payload helper"
```

---

## Task 5: Implement QuickScoreUser and FullApplicationUser

**Files:**
- Create: `tests/load/users.py`

- [ ] **Step 1: Write the user classes**

Create `tests/load/users.py`:
```python
"""Locust user classes for the two dominant traffic patterns."""
import time

from locust import HttpUser, between, task

from tests.load.auth import login
from tests.load.payloads import loan_application_payload

TERMINAL_STATES = {"SUCCESS", "FAILURE", "approved", "denied", "failed"}


class _AuthedUser(HttpUser):
    abstract = True

    def on_start(self):
        token = login(self.client)
        self.client.headers["Authorization"] = f"Bearer {token}"


class QuickScoreUser(_AuthedUser):
    """70% of load. Creates a loan then hits the synchronous predict endpoint."""

    wait_time = between(1, 3)
    weight = 7

    @task
    def quick_score(self):
        create = self.client.post(
            "/api/v1/loans/",
            json=loan_application_payload(),
            name="loans:create",
        )
        if create.status_code not in (200, 201):
            return
        loan_id = create.json().get("id")
        if not loan_id:
            return
        self.client.post(
            f"/api/v1/ml/predict/{loan_id}/",
            name="ml:predict",
        )


class FullApplicationUser(_AuthedUser):
    """30% of load. Submits application, orchestrates, polls to terminal."""

    wait_time = between(5, 10)
    weight = 3

    @task
    def full_application(self):
        create = self.client.post(
            "/api/v1/loans/",
            json=loan_application_payload(),
            name="loans:create",
        )
        if create.status_code not in (200, 201):
            return
        loan_id = create.json().get("id")
        if not loan_id:
            return

        orchestrate = self.client.post(
            f"/api/v1/agents/orchestrate/{loan_id}/",
            name="agents:orchestrate",
        )
        if orchestrate.status_code not in (200, 202):
            return
        task_id = orchestrate.json().get("task_id") or orchestrate.json().get("id")
        if not task_id:
            return

        deadline = time.time() + 120  # hard cap per iteration
        while time.time() < deadline:
            status_resp = self.client.get(
                f"/api/v1/tasks/{task_id}/status/",
                name="tasks:status",
            )
            if status_resp.status_code != 200:
                return
            state = status_resp.json().get("status") or status_resp.json().get("state")
            if state in TERMINAL_STATES:
                return
            time.sleep(2)
```

- [ ] **Step 2: Verify import**

Run:
```bash
python -c "from tests.load.users import QuickScoreUser, FullApplicationUser; print('ok')"
```
Expected: `ok` (locust must be installed first — from Task 1).

- [ ] **Step 3: Commit**

```bash
git add tests/load/users.py
git commit -m "test(load): add QuickScoreUser and FullApplicationUser classes"
```

---

## Task 6: Implement locustfile entry point

**Files:**
- Create: `tests/load/locustfile.py`

- [ ] **Step 1: Write locustfile**

Create `tests/load/locustfile.py`:
```python
"""Locust entry point. Imports the user classes; Locust picks them up."""
from tests.load.users import FullApplicationUser, QuickScoreUser

__all__ = ["QuickScoreUser", "FullApplicationUser"]
```

- [ ] **Step 2: Verify locustfile loads**

Run:
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000 --headless --users 1 --spawn-rate 1 --run-time 2s --only-summary
```
Expected: locust starts, runs 2 seconds, prints a summary (errors are fine — host may not be up yet; we just want no import errors).

- [ ] **Step 3: Commit**

```bash
git add tests/load/locustfile.py
git commit -m "test(load): add locustfile entry point"
```

---

## Task 7: Implement metrics sampler

**Files:**
- Create: `tests/load/metrics_sampler.py`

- [ ] **Step 1: Write the sampler**

Create `tests/load/metrics_sampler.py`:
```python
"""Side sampler for stack metrics during a Locust run.

Samples every 5 seconds:
- Celery queue depth (ml, email, agents) via Redis LLEN
- Postgres active connection count
- Docker stats (CPU, mem) per core container

Writes CSV to --out. Stop with Ctrl+C.
"""
import argparse
import csv
import shutil
import subprocess
import time
from datetime import datetime, timezone


def redis_llen(queue: str) -> int:
    try:
        out = subprocess.run(
            ["docker", "compose", "exec", "-T", "redis", "redis-cli", "LLEN", queue],
            capture_output=True, text=True, timeout=5,
        )
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def pg_active_connections() -> int:
    try:
        out = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres",
             "-tAc", "SELECT count(*) FROM pg_stat_activity;"],
            capture_output=True, text=True, timeout=5,
        )
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def docker_stats() -> dict[str, tuple[str, str]]:
    if not shutil.which("docker"):
        return {}
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return {}
    stats = {}
    for line in out.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) == 3:
            stats[parts[0]] = (parts[1], parts[2])
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ts_utc", "ml_q", "email_q", "agents_q", "pg_conns", "docker_stats_json",
        ])
        try:
            while True:
                ts = datetime.now(timezone.utc).isoformat()
                ml = redis_llen("ml")
                em = redis_llen("email")
                ag = redis_llen("agents")
                pg = pg_active_connections()
                ds = docker_stats()
                w.writerow([ts, ml, em, ag, pg, str(ds)])
                f.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script runs for one interval**

Run:
```bash
python tests/load/metrics_sampler.py --out /tmp/sampler-test.csv --interval 1 &
SAMPLER_PID=$!; sleep 2; kill $SAMPLER_PID 2>/dev/null; head /tmp/sampler-test.csv
```
Expected: a CSV with at least one data row.

- [ ] **Step 3: Commit**

```bash
git add tests/load/metrics_sampler.py
git commit -m "test(load): add metrics sampler for queue/db/docker stats"
```

---

## Task 8: Seed a load-test user and document env vars

**Files:**
- Modify: `tests/load/README.md` (append seed instructions)

- [ ] **Step 1: Verify you can create a test user via the existing management shell**

Run:
```bash
docker compose up -d
docker compose exec backend python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
u, created = U.objects.get_or_create(username='loadtest', defaults={'email': 'loadtest@example.com'})
u.set_password('loadtest-change-me')
u.is_active = True
u.save()
print('created' if created else 'updated', u.username)
"
```
Expected: `created loadtest` or `updated loadtest`.

- [ ] **Step 2: Export env vars for the current shell**

Run:
```bash
export LOAD_TEST_USER=loadtest
export LOAD_TEST_PASSWORD=loadtest-change-me
```

- [ ] **Step 3: Append seed instructions to README**

Append to `tests/load/README.md`:
```markdown
## Seeding the load-test user

```bash
docker compose up -d
docker compose exec backend python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
u, _ = U.objects.get_or_create(username='loadtest', defaults={'email': 'loadtest@example.com'})
u.set_password('loadtest-change-me')
u.is_active = True
u.save()
"
export LOAD_TEST_USER=loadtest
export LOAD_TEST_PASSWORD=loadtest-change-me
```
```

- [ ] **Step 4: Commit**

```bash
git add tests/load/README.md
git commit -m "docs(load): document load-test user seed and env vars"
```

---

## Task 9: Run the smoke test

**Files:** none — this is a verification task.

- [ ] **Step 1: Ensure stack is up**

Run:
```bash
docker compose up -d
docker compose ps
```
Expected: all core containers (backend, postgres, redis, celery-ml, celery-email, celery-agents) are `Up (healthy)` or `Up`.

- [ ] **Step 2: Run 30-second smoke Locust**

Run:
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 2 --spawn-rate 1 --run-time 30s --headless --only-summary
```
Expected: `Failures` column reads 0. If not, diagnose before proceeding.

- [ ] **Step 3: If failures, iterate**

Likely causes:
- Serializer rejects a payload field → adjust `tests/load/payloads.py` to match the real serializer
- `task_id`/`state` field names differ → adjust `tests/load/users.py` accordingly
- Auth token field differs → adjust `tests/load/auth.py` branch for `access` vs `token`

Fix, re-run until 0 failures. Each fix is its own small commit.

---

## Task 10: Run the baseline and commit the report

**Files:**
- Create: `docs/load/baseline-2026-04-14.md`
- Create: `reports/` directory (gitignored or committed per project convention — check with `cat .gitignore`)

- [ ] **Step 1: Create reports dir**

Run:
```bash
mkdir -p reports docs/load
```

- [ ] **Step 2: Start the metrics sampler in the background**

Run:
```bash
python tests/load/metrics_sampler.py --out reports/baseline-sampler.csv &
SAMPLER_PID=$!
echo $SAMPLER_PID > /tmp/sampler.pid
```

- [ ] **Step 3: Run the baseline Locust scenario**

Run:
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 50 --spawn-rate 1 --run-time 10m --headless \
  --html reports/baseline.html --csv reports/baseline --only-summary
```
Expected: runs 10 minutes, summary printed. Copy key metrics (p50/p95/p99, RPS, error count per endpoint) from stdout.

- [ ] **Step 4: Stop the sampler**

Run:
```bash
kill $(cat /tmp/sampler.pid) 2>/dev/null || true
```

- [ ] **Step 5: Write the baseline report**

Create `docs/load/baseline-2026-04-14.md` with:
- Run configuration (50 users, 10 min, host)
- Per-endpoint metrics table (pull from `reports/baseline_stats.csv`)
- Queue depth peaks (from `reports/baseline-sampler.csv` — max ml_q, email_q, agents_q)
- Postgres peak connection count
- Notable anomalies or hot containers from `docker stats`
- Targets-vs-actuals table (use targets from spec: ML p95 < 500ms, full-pipeline p95 < 30s, 0 errors)
- Attach `reports/baseline.html` summary table excerpt

Format example:
```markdown
# Baseline Load Test — 2026-04-14

Config: 50 concurrent users, 10 min steady, `docker compose up` local stack.

## Per-endpoint latency

| Endpoint | p50 ms | p95 ms | p99 ms | RPS | Errors |
|---|---|---|---|---|---|
| auth:login | ... | ... | ... | ... | 0 |
| loans:create | ... | ... | ... | ... | 0 |
| ml:predict | ... | ... | ... | ... | 0 |
| agents:orchestrate | ... | ... | ... | ... | 0 |
| tasks:status | ... | ... | ... | ... | 0 |

## Stack pressure

| Metric | Peak | Avg |
|---|---|---|
| ml queue depth | ... | ... |
| email queue depth | ... | ... |
| agents queue depth | ... | ... |
| pg active conns | ... | ... |

## Targets vs actuals

| Target | Actual | Pass/Fail |
|---|---|---|
| ML predict p95 < 500 ms | ... | ... |
| Full-pipeline p95 < 30 s | ... | ... |
| Error rate = 0 | ... | ... |
```

- [ ] **Step 6: Commit the baseline**

```bash
git add docs/load/baseline-2026-04-14.md
git commit -m "docs(load): add baseline stress-test report (50 users, 10 min)"
```

(Do NOT commit `reports/` unless the project convention says so — the `.csv` and `.html` files are ephemeral artefacts.)

---

## Task 11: Run the breakpoint and commit the report

**Files:**
- Create: `docs/load/breakpoint-2026-04-14.md`

- [ ] **Step 1: Start the sampler**

Run:
```bash
python tests/load/metrics_sampler.py --out reports/breakpoint-sampler.csv &
SAMPLER_PID=$!
echo $SAMPLER_PID > /tmp/sampler.pid
```

- [ ] **Step 2: Run the breakpoint ramp**

Run:
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 500 --spawn-rate 0.4 --run-time 20m --headless \
  --html reports/breakpoint.html --csv reports/breakpoint --only-summary
```
Watch the live summary. Stop manually (Ctrl+C) when:
- Error rate exceeds 1%, OR
- Median latency of any critical endpoint exceeds 3× its baseline median

Record the concurrency level at which the stop condition tripped.

- [ ] **Step 3: Stop the sampler**

Run:
```bash
kill $(cat /tmp/sampler.pid) 2>/dev/null || true
```

- [ ] **Step 4: Write the breakpoint report**

Create `docs/load/breakpoint-2026-04-14.md`:
```markdown
# Breakpoint Load Test — 2026-04-14

Config: ramp 10 → 500 users over 20 min, stopped when error rate > 1% or median latency > 3× baseline.

## Breakpoint

- Concurrency at stop: N users
- Tripping metric: (endpoint) median went from X ms (baseline) to Y ms
- Error rate at stop: Z%

## Degradation curve

| Concurrency | ml:predict p95 | agents:orchestrate p95 | Error rate |
|---|---|---|---|
| 50 | ... | ... | ... |
| 100 | ... | ... | ... |
| 200 | ... | ... | ... |
| 400 | ... | ... | ... |
| breakpoint | ... | ... | ... |

## Resource pressure at breakpoint

| Metric | Value |
|---|---|
| peak queue depth (ml/email/agents) | .../.../.../ |
| peak pg active conns | ... |
| peak container CPU | ... (container=...) |
| peak container mem | ... (container=...) |

## Top suspected bottlenecks (for Phase 2)

1. ...
2. ...
3. ...
```

- [ ] **Step 5: Commit the breakpoint**

```bash
git add docs/load/breakpoint-2026-04-14.md
git commit -m "docs(load): add breakpoint stress-test report (ramp to 500)"
```

---

## Task 12: Phase 2 — pick top 1–3 bottlenecks

**Files:** none — analysis task.

- [ ] **Step 1: Review both reports**

Read `docs/load/baseline-2026-04-14.md` and `docs/load/breakpoint-2026-04-14.md` side by side. List candidate bottlenecks that meet the spec criteria: measurable, plausible local fix (config/index/prefetch/cache), low blast radius (no ML model or approval logic changes).

- [ ] **Step 2: Write a short selection memo (in this task's commit message, not a file)**

For each candidate, note:
- Name and one-line description
- Measured metric and value
- Proposed local fix (one sentence)
- Expected effect

- [ ] **Step 3: Pick top 1–3**

Stop at 3. If fewer than 3 have both a clear fix and a clear measured value, proceed with fewer.

- [ ] **Step 4: Commit the selection**

```bash
git commit --allow-empty -m "chore(load): Phase 2 bottleneck selection

Picks (based on docs/load/breakpoint-2026-04-14.md):
1. <name> — <metric>=<value>, fix: <one line>
2. ...
3. ...
"
```

---

## Task 13–15 (template, one per selected fix)

Each fix repeats the same structure. Task 13 is the first fix, Task 14 the second, Task 15 the third. If fewer than 3 fixes were selected in Task 12, skip the unused tasks.

### Task 13 (and 14, 15): apply fix N

**Files:** depends on the fix. Common shapes:
- `docker-compose.yml` — Celery worker concurrency, Postgres connection pool size
- `backend/config/celery.py` — prefetch multiplier, acks_late
- `backend/config/settings*.py` — DB `CONN_MAX_AGE`, cache config
- `backend/apps/<app>/views.py` or `serializers.py` — `select_related`/`prefetch_related` to kill N+1
- A new migration to add a DB index

- [ ] **Step 1: Capture the BEFORE number**

Run the baseline scenario again (same 50 users, 10 min) if the before number isn't already in `docs/load/baseline-2026-04-14.md`. Record the exact metric value that this fix targets (e.g. `ml:predict p95 = 812 ms`).

- [ ] **Step 2: Apply the minimal code/config change**

Make the single targeted change. No unrelated cleanup.

- [ ] **Step 3: Run tests**

Run:
```bash
cd backend && pytest -x --timeout 60
```
Expected: no failures. If tests fail that aren't related to the fix, the fix may be out-of-scope; revert and reselect.

- [ ] **Step 4: Capture the AFTER number**

Run the same 50-user 10-min baseline scenario. Record the new metric value.

- [ ] **Step 5: Decide**

If the target metric improved AND no other metric regressed (check the per-endpoint p95 table), keep the change.
If not, revert:
```bash
git checkout -- <changed files>
```
Document the null result in the commit message of Task 12's selection memo if you like.

- [ ] **Step 6: Commit**

```bash
git add <files>
git commit -m "perf(<area>): <one-line what>

Before: <metric>=<value> (source: docs/load/baseline-2026-04-14.md)
Change: <what and why in one sentence>
After:  <metric>=<value> (fresh 50-user 10-min rerun)
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Final verification

**Files:** none.

- [ ] **Step 1: Rerun the baseline one more time with all fixes applied**

Run:
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --users 50 --spawn-rate 1 --run-time 10m --headless \
  --html reports/post-fix.html --csv reports/post-fix --only-summary
```

- [ ] **Step 2: Append a "post-fix" section to the baseline report**

Append to `docs/load/baseline-2026-04-14.md`:
```markdown
## Post-fix rerun — <date>

| Metric | Original baseline | Post-fix | Delta |
|---|---|---|---|
| ml:predict p95 | ... | ... | ... |
| agents:orchestrate p95 | ... | ... | ... |
| error rate | ... | ... | ... |
```

- [ ] **Step 3: Run existing test suite**

Run:
```bash
cd backend && pytest --timeout 60
```
Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add docs/load/baseline-2026-04-14.md
git commit -m "docs(load): record post-fix baseline rerun"
```

---

## Done criteria

- `tests/load/` suite runs reproducibly via the README commands
- `docs/load/baseline-2026-04-14.md` and `docs/load/breakpoint-2026-04-14.md` committed
- 0 to 3 perf fix commits, each with measured before/after in the commit body
- `backend` test suite passes
- Sub-project C closed. Hand back to user for next steps.
