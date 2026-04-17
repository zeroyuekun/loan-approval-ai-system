# Track A: Memory & Reliability — Design Spec

**Date:** 2026-04-17
**Status:** Approved
**Branch:** `fix/memory-reliability-track-a`

## Goal

Eliminate the frontend OOM crash loop (exit-243) and tighten memory/reliability patterns across the stack. Five targeted fixes, each independently testable.

## Problem

A portfolio-wide efficiency + production-readiness audit surfaced 24 findings. Track A bundles the five highest impact × ease fixes:

1. **React Query `gcTime` unbounded** — likely root cause of frontend container OOM crash loop
2. **localStorage thrashing on form keystrokes** — main-thread blocking
3. **Timer ref leaks** in applications page
4. **ML model cache no TTL/LRU** — unbounded growth, stale predictions
5. **`time.sleep()` inside Celery retry decorator** — worker pool starvation

All other audit findings (Tracks B–F) are out of scope and deferred to follow-up PRs.

## Scope

### In scope

- `frontend/src/app/providers.tsx` — set global `gcTime`
- `frontend/src/hooks/useAgentStatus.ts`, `useMetrics.ts`, `useDashboardStats.ts` — per-hook `gcTime`, cleanup pollCountRef
- `frontend/src/hooks/useApplicationForm.ts` — debounce localStorage writes
- `frontend/src/app/dashboard/applications/page.tsx` — cancel timers before push, cleanup on unmount
- `backend/apps/ml_engine/services/predictor.py` — swap dict cache for `cachetools.TTLCache`
- `backend/apps/agents/utils.py` (or wherever `retry_llm_call` lives) — replace `time.sleep` with `self.retry(countdown=)`

### Out of scope

- Any finding not in the five above
- Rewriting React Query overall caching strategy
- Prometheus metrics redesign
- Exception handler refactor (Track B)
- Bundle optimization (Track C)
- Security hardening (Track D)

## Approach — Per Finding

### 1. React Query `gcTime`

Global default in `providers.tsx` sets `gcTime: 2 * 60 * 1000` (2 min). Pollers that refetch every few seconds override to `30_000` (30s) so polled data doesn't accumulate. Hooks touched: `useAgentStatus`, `useMetrics`, `useDashboardStats`.

**Why:** React Query defaults to 5-minute `gcTime`. With 10+ polling hooks active simultaneously over a long session, heap grows linearly. Dropping to 2 minutes (30s for pollers) trades negligible re-fetch cost for bounded memory.

### 2. localStorage debounce

Wrap the `watch()` subscription in `useApplicationForm.ts` with a 500ms debounce. Use `lodash.debounce` (already transitively available via shadcn/react-query) or a hand-rolled `useDebouncedCallback`.

**Test:** simulate 10 rapid keystrokes, assert `localStorage.setItem` called ≤1 time within the debounce window.

### 3. Timer cleanup in applications page

Inside the "Check All" handler, before pushing a new timer:
```
timersRef.current.forEach(clearTimeout);
timersRef.current = [];
```
On unmount (existing cleanup), same pattern.

**Test:** React Testing Library — click Check All twice quickly, assert only one timer active.

### 4. ML model cache TTL

Replace module-level `_model_cache: dict` with `cachetools.TTLCache(maxsize=3, ttl=3600)`. Keep the Prometheus hit/miss counters. Add `cachetools` to `backend/requirements/base.txt` if not already present.

**Test:** unit test mocking model loading; fill cache, sleep past TTL (monkeypatch `time.time`), verify re-load.

### 5. Celery retry — no `time.sleep`

`retry_llm_call` decorator currently blocks the worker with `time.sleep(2**n)`. Refactor to raise `self.retry(countdown=backoff_seconds, max_retries=N)` from inside the wrapped task. If the caller isn't a bound task, fall back to raising a custom `TransientLLMError` the caller can re-raise via Celery's native retry.

**Test:** unit test that `time.sleep` is NOT called; mock `self.retry` and assert called with correct countdown.

## Testing Strategy

- Each finding gets a dedicated test or test update.
- Frontend: vitest + React Testing Library (already set up).
- Backend: pytest (unit-level, no Docker required).
- No DB-dependent tests added — the 5 fixes are all testable with mocks.
- Run affected existing test suites to catch regressions.

## Out of Scope for This Spec

- Refactoring the broader React Query caching strategy (e.g. switching to SWR)
- Upgrading Celery version
- Replacing `cachetools` with Django's cache framework (considered but `cachetools` is lighter, already process-local, and this is module-level caching)
- Accessibility, type hints, security — all deferred

## Branch & Commit Plan

- Branch: `fix/memory-reliability-track-a` (off master)
- 5 commits, one per finding, TDD style (test → impl → green → commit)
- PR title: `fix: resolve frontend OOM + tighten memory/reliability (Track A)`
- Tests run before each commit

## Risks

- **gcTime too aggressive** could cause extra backend load from refetches. Mitigation: start with 2min global, measure, tune per-hook.
- **cachetools is a new dep** — minor; widely used and maintained.
- **Celery retry refactor** could change semantics for callers that relied on blocking. Mitigation: preserve raise-on-exhausted contract; add regression test.

## Success Criteria

- Frontend container survives a 30-minute soak test without OOM (manual validation after merge).
- All existing tests still pass.
- Five new/updated tests covering each fix pass.
- `cachetools` added to dependencies.
