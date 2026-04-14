# Stress Test and Data-Driven Fixes — Design

**Date:** 2026-04-14
**Sub-project:** C (of A→B→C sequence)
**Feeds:** Future sub-projects; baseline metrics become the regression reference for any subsequent performance work.
**Out of scope:** UX additions from sub-project A's `[→ C]` recommendations (soft-pull endpoint, rate-factor disclosure, documents checklist, borrowing estimator, fee-tier support) — those are a separate sub-project. Production-tier infrastructure changes (autoscaling, read replicas). Frontend rendering performance.

## Goal

Measure the current system's performance under realistic load, identify the true bottlenecks, then fix up to three of them with measured before/after evidence. Deliver a reproducible Locust scenario suite and two committed metric snapshots so future work has a baseline to compare against.

## Two phases

**Phase 1 — Stress test.** Run Locust against a local `docker compose` stack. Produce a baseline run (50 users, 10 min steady) and a breakpoint run (ramp 10 → 500 users, stop at degradation). Commit both reports.

**Phase 2 — Data-driven fixes.** Gated on Phase 1 output. Pick the top 1–3 bottlenecks from the measured metrics, not from guessing. Each fix is a self-contained commit: before-number, code change, after-number. Cap at three fixes; anything bigger becomes its own brainstorm.

## Tool

Locust (Python). Stays in-stack, readable by the team, supports multi-step user flows that the orchestrator pipeline needs. Installed as a dev dependency in `backend/requirements-dev.txt` (or the project's equivalent dev requirements file — discover during implementation).

## User classes and traffic mix

Two classes, both authenticated via a login warm-up step at user start (one-time token acquisition; token reused across iterations).

### `QuickScoreUser` (70% of virtual users)

Represents a borrower requesting a rate quote.

- On start: authenticate (`POST /api/auth/token/` or the project's equivalent — discover during implementation), store bearer token.
- Task loop: `POST` the synchronous ML scoring endpoint (discover real endpoint name in `backend/apps/ml_engine/` or `backend/apps/loans/views.py`; likely `/api/loans/quick-score/`, `/api/ml/predict/`, or similar). Submit a realistic synthetic payload generated from the same distributions as `data_generator.py` but trimmed to the endpoint's input schema.
- Think time: 1–3 seconds between requests.

### `FullApplicationUser` (30% of virtual users)

Represents a borrower submitting a full application.

- On start: authenticate, store token.
- Task loop:
  1. `POST /api/loans/applications/` (or equivalent) with a full application payload.
  2. Poll `/api/tasks/{id}/status/` every 2 seconds until status is terminal (approved / denied / failed).
  3. Optionally `GET` the final result resource.
- Think time: 5–10 seconds after terminal.

## Test runs

Both runs target a `docker compose up` local stack on the developer's machine.

### Baseline

- Concurrency: 50 users (ramp 1 user/sec for 50 seconds, then steady).
- Duration: 10 minutes steady after ramp.
- Targets (documented, not gates):
  - ML scoring p95 < 500 ms
  - Full-pipeline time-to-terminal p95 < 30 s
  - Error rate 0
- Output committed to `docs/load/baseline-2026-04-14.md` with metric table, Locust HTML summary excerpt, and notes on any anomalies.

### Breakpoint

- Concurrency: ramp 10 → 500 users over 20 minutes.
- Stop condition: error rate exceeds 1% OR median latency of any critical endpoint degrades more than 3× vs baseline median. Locust's `stop_timeout` handles graceful shutdown.
- Output committed to `docs/load/breakpoint-2026-04-14.md`: concurrency at breakpoint, which metric tripped the stop condition, latency/error curves.

## Metrics captured per run

For each run, record:

- Per-endpoint p50 / p95 / p99 latency
- Requests per second
- Error rate per endpoint
- Celery queue depth across the three queues (`ml`, `email`, `agents`) — sampled from Redis every 5 s via a side script, not Locust
- Postgres active connection count — sampled every 5 s via `psql -c "SELECT count(*) FROM pg_stat_activity"` or equivalent
- Container CPU and memory — sampled from `docker stats --no-stream` every 10 s

The sampling side script lives at `tests/load/metrics_sampler.py` and writes a CSV that the report generator ingests.

## Phase 2: fix selection and execution

After Phase 1, review both reports. Pick up to three bottlenecks that meet all of:

1. Measurable — has a named metric (latency, queue depth, connection count) that will move if fixed.
2. Plausible local fix — configuration change, indexed column, Celery prefetch/concurrency tweak, serializer N+1, repeated model-artifact load, cache miss. Not an architectural rework.
3. Low blast radius — the fix does not touch the trained ML model artefacts, does not alter approval decisioning, and is reversible via `git revert`.

Each fix becomes a separate commit with this structure in the commit body:

```
Before: <metric>=<value> (from baseline or breakpoint run)
Change: <one-line description>
After:  <metric>=<value> (from rerun of the same Locust scenario at the same concurrency)
```

Rerun the relevant scenario at the same concurrency after each fix. If the after-number does not improve (or regresses another metric), revert the commit.

Stop at three fixes. Larger-than-config-change work (refactors, new caches, autoscaling) is out of scope and becomes a future sub-project.

## Testing and verification

- `tests/load/locustfile.py` imports in isolation (`python -c "import tests.load.locustfile"`) — catches syntax and import-path issues cheaply.
- A "smoke" Locust run with 2 users for 30 seconds must pass with 0 errors before either full run is considered valid. Documented in `tests/load/README.md`.
- Each Phase-2 fix commit is accompanied by a rerun of at least the affected scenario at the baseline concurrency (50 users, 10 min) — not necessarily both scenarios.

## Deliverables

- Created: `tests/load/locustfile.py`
- Created: `tests/load/users.py` — user class modules (if locustfile is thin)
- Created: `tests/load/payloads.py` — synthetic request payload helpers
- Created: `tests/load/metrics_sampler.py` — Celery/Postgres/docker-stats sampler
- Created: `tests/load/README.md` — run instructions
- Created: `docs/load/baseline-2026-04-14.md`
- Created: `docs/load/breakpoint-2026-04-14.md`
- Modified: `backend/requirements-dev.txt` (add `locust`)
- Up to 3 fix commits (content determined by Phase 1 data)

## Success criteria

- Locust suite runs reproducibly on `docker compose up` stack with a single documented command.
- Baseline and breakpoint reports committed and readable — anyone new to the project can see current performance.
- If Phase 2 fixes are applied: each has measured before/after numbers, each is individually revertable, none alter approval decisioning or ML artefacts.
- No test in the existing test suite regresses as a result of Phase 2 fixes.
