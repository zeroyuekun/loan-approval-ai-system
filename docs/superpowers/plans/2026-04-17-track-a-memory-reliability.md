# Track A: Memory & Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the frontend OOM crash loop (exit 243) and tighten 5 memory/reliability gaps surfaced by the portfolio audit.

**Architecture:** Five small, independent fixes across frontend (React Query gcTime, localStorage debounce, timer cleanup) and backend (ML model cache TTL, Celery retry sleep cap). Each finding gets its own TDD task + commit. No cross-finding dependencies.

**Tech Stack:** Next.js 15 + React Query v5 + vitest (frontend); Django 5 + Celery + pytest + cachetools (backend).

---

## File Structure

**Frontend:**
- Modify: `frontend/src/app/providers.tsx` — global `gcTime`
- Modify: `frontend/src/hooks/useAgentStatus.ts` — per-hook `gcTime` on pollers
- Modify: `frontend/src/hooks/useMetrics.ts` — per-hook `gcTime` on training task poller
- Modify: `frontend/src/hooks/useDashboardStats.ts` — per-hook `gcTime`
- Modify: `frontend/src/hooks/useApplicationForm.ts` — debounce `watch()` subscription
- Modify: `frontend/src/app/dashboard/applications/page.tsx` — clear timers before push
- Test: `frontend/src/__tests__/hooks/useApplicationForm.test.tsx` (new)
- Test: `frontend/src/__tests__/app/applications-page.test.tsx` (new)

**Backend:**
- Modify: `backend/requirements.in` + `backend/requirements.txt` — add `cachetools`
- Modify: `backend/apps/ml_engine/services/predictor.py` — TTL cache
- Modify: `backend/apps/agents/utils.py` — cap sleep + jitter
- Test: `backend/tests/test_predictor_cache.py` (new)
- Test: `backend/tests/test_retry_llm_call_sleep.py` (new)

---

## Task 1: React Query `gcTime` bounds

**Files:**
- Modify: `frontend/src/app/providers.tsx`
- Modify: `frontend/src/hooks/useAgentStatus.ts`
- Modify: `frontend/src/hooks/useMetrics.ts`
- Modify: `frontend/src/hooks/useDashboardStats.ts`

- [ ] **Step 1: Set global `gcTime` in providers**

Edit `frontend/src/app/providers.tsx` lines 10-17:
```tsx
new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      gcTime: 2 * 60 * 1000, // 2 min: cap heap growth from unused queries
      retry: 1,
    },
  },
})
```

- [ ] **Step 2: Override `gcTime` on `useAgentRun` and `useTaskStatus`**

Edit `frontend/src/hooks/useAgentStatus.ts` — add `gcTime: 30_000` to both `useQuery` calls inside `useAgentRun` (line 17) and `useTaskStatus` (line 81):

```ts
return useQuery<AgentRun>({
  queryKey: ['agentRun', loanId],
  queryFn: async () => { /* existing */ },
  enabled: !!loanId,
  retry: false,
  gcTime: 30_000, // 30s: polled data, drop fast after unmount
  refetchInterval: (query) => { /* existing */ },
})
```

```ts
return useQuery<TaskStatus>({
  queryKey: ['taskStatus', taskId],
  queryFn: async () => { /* existing */ },
  enabled: !!taskId && (options?.enabled ?? true),
  gcTime: 30_000,
  refetchInterval: (query) => { /* existing */ },
})
```

- [ ] **Step 3: Override `gcTime` on training task poller in `useMetrics.ts`**

Find the `useQuery` that polls training task status (keyed on `['trainingTask', ...]` or similar — likely returns `ModelMetrics | null`). Add `gcTime: 30_000`. Check the full file and add to any `useQuery` whose `refetchInterval` is not `false`.

- [ ] **Step 4: Override `gcTime` on dashboard stats poller**

Edit `frontend/src/hooks/useDashboardStats.ts` — add `gcTime: 30_000` to the primary `useQuery`.

- [ ] **Step 5: Run frontend tests to confirm no regressions**

```bash
cd frontend && npm test -- --run
```
Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/providers.tsx \
        frontend/src/hooks/useAgentStatus.ts \
        frontend/src/hooks/useMetrics.ts \
        frontend/src/hooks/useDashboardStats.ts
git commit -m "fix(frontend): bound React Query gcTime to fix OOM crash loop"
```

---

## Task 2: Debounce localStorage writes in application form

**Files:**
- Modify: `frontend/src/hooks/useApplicationForm.ts:94-102`
- Create: `frontend/src/__tests__/hooks/useApplicationForm.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/hooks/useApplicationForm.test.tsx`:

```tsx
import { renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import { useApplicationForm } from '@/hooks/useApplicationForm'

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { role: 'customer' } }) }))
vi.mock('@/hooks/useApplications', () => ({
  useCreateApplication: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
}))
vi.mock('@/lib/api', () => ({
  authApi: { getCustomerProfile: vi.fn().mockResolvedValue({ data: {} }) },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useApplicationForm — localStorage debounce', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
  })
  afterEach(() => { vi.useRealTimers() })

  it('writes to localStorage at most once per 500ms window', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const { result } = renderHook(() => useApplicationForm(), { wrapper })

    // Simulate 10 rapid field changes
    act(() => {
      for (let i = 0; i < 10; i++) {
        result.current.form.setValue('annual_income', 1000 + i)
      }
    })
    // Before debounce flush
    act(() => { vi.advanceTimersByTime(100) })
    const callsBefore = setItemSpy.mock.calls.filter(c => c[0] === 'loan_application_draft').length
    // Allow 0 or 1 calls in the first 100ms window
    expect(callsBefore).toBeLessThanOrEqual(1)

    // After debounce flush
    act(() => { vi.advanceTimersByTime(500) })
    const callsAfter = setItemSpy.mock.calls.filter(c => c[0] === 'loan_application_draft').length
    // Should have exactly 1 call after debounce
    expect(callsAfter).toBe(1)

    setItemSpy.mockRestore()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- --run useApplicationForm
```
Expected: FAIL — `callsAfter` will be 10 because each `setValue` triggers a synchronous write.

- [ ] **Step 3: Implement debounce**

Edit `frontend/src/hooks/useApplicationForm.ts` lines 94-102:

```tsx
  // Persist form state to localStorage on every change, debounced to 500ms
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null
    const subscription = watch((values) => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        try {
          localStorage.setItem(DRAFT_KEY, JSON.stringify(values))
        } catch (e) { console.warn('[useApplicationForm] Failed to save draft to localStorage:', e) }
      }, 500)
    })
    return () => {
      if (timer) clearTimeout(timer)
      subscription.unsubscribe()
    }
  }, [watch])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npm test -- --run useApplicationForm
```
Expected: PASS — exactly 1 `localStorage.setItem` call after debounce flush.

- [ ] **Step 5: Run full frontend suite**

```bash
cd frontend && npm test -- --run
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useApplicationForm.ts \
        frontend/src/__tests__/hooks/useApplicationForm.test.tsx
git commit -m "fix(form): debounce localStorage writes to 500ms"
```

---

## Task 3: Cancel stacked timers in ApplicationsPage

**Files:**
- Modify: `frontend/src/app/dashboard/applications/page.tsx:47-68`

- [ ] **Step 1: Implement timer cancellation before push**

Edit `frontend/src/app/dashboard/applications/page.tsx` inside `handleCheckAll` (around line 47). Replace the body with this, adding the clear loop at the start of the success branch:

```tsx
  const handleCheckAll = async () => {
    setCheckAllState('loading')
    setCheckAllResult(null)
    // Cancel any in-flight timers from a previous click
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
    try {
      const { data } = await agentsApi.orchestrateAll(true)
      setCheckAllResult({ queued: data.queued })
      setCheckAllState('done')
      timersRef.current.push(setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['applications'] })
      }, 2000))
      timersRef.current.push(setTimeout(() => {
        setCheckAllState('idle')
        setCheckAllResult(null)
      }, 5000))
    } catch {
      toast.error('Failed to process applications. Please try again.')
      setCheckAllState('idle')
      setCheckAllResult(null)
    }
  }
```

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm test -- --run
```
Expected: all tests pass (no new regressions).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/dashboard/applications/page.tsx
git commit -m "fix(applications): cancel stacked timers on rapid Check-All clicks"
```

---

## Task 4: ML model cache TTL

**Files:**
- Modify: `backend/requirements.in` — add `cachetools`
- Modify: `backend/requirements.txt` — add `cachetools` with pinned version
- Modify: `backend/apps/ml_engine/services/predictor.py:40-45, 143-165`
- Create: `backend/tests/test_predictor_cache.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_predictor_cache.py`:

```python
"""TTL behavior for the ML model cache."""
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_version(pk=1, path="/tmp/fake.joblib", file_hash=None):
    v = MagicMock()
    v.id = pk
    v.file_path = path
    v.file_hash = file_hash
    return v


class TestModelCacheTTL:
    def setup_method(self):
        from apps.ml_engine.services import predictor
        predictor.clear_model_cache()

    @patch("apps.ml_engine.services.predictor._verify_model_hash")
    @patch("apps.ml_engine.services.predictor._validate_model_path")
    @patch("apps.ml_engine.services.predictor.joblib.load")
    def test_cache_reloads_after_ttl(self, mock_load, mock_validate, mock_verify):
        from apps.ml_engine.services import predictor

        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [
            {"model": "A"},
            {"model": "B"},
        ]
        version = _make_mock_version(pk=1)

        # First load -> cache miss, calls joblib.load
        assert predictor._load_bundle(version) == {"model": "A"}
        # Second load within TTL -> cache hit, no new joblib.load
        assert predictor._load_bundle(version) == {"model": "A"}
        assert mock_load.call_count == 1

        # Expire cache manually (TTL-aware cache must support this)
        predictor._model_cache.expire(time=time.time() + 10_000)

        # Third load after expiry -> cache miss, joblib.load called again
        assert predictor._load_bundle(version) == {"model": "B"}
        assert mock_load.call_count == 2

    @patch("apps.ml_engine.services.predictor._verify_model_hash")
    @patch("apps.ml_engine.services.predictor._validate_model_path")
    @patch("apps.ml_engine.services.predictor.joblib.load")
    def test_cache_bounded_to_maxsize(self, mock_load, mock_validate, mock_verify):
        from apps.ml_engine.services import predictor

        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [{"m": i} for i in range(10)]

        for i in range(5):
            v = _make_mock_version(pk=i)
            predictor._load_bundle(v)

        # TTLCache with maxsize=3 should never hold more than 3 entries
        assert len(predictor._model_cache) <= 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_predictor_cache.py -v
```
Expected: FAIL — `predictor._model_cache.expire(...)` raises AttributeError because plain dict has no `expire` method.

- [ ] **Step 3: Add `cachetools` to requirements**

Append to `backend/requirements.in`:
```
cachetools>=5.3,<6
```

Run pip-compile or add the resolved version to `backend/requirements.txt`:
```
cachetools==5.5.0
```
(Use `pip install cachetools==5.5.0` then `pip freeze | grep cachetools` to confirm if needed.)

- [ ] **Step 4: Replace dict cache with TTLCache**

Edit `backend/apps/ml_engine/services/predictor.py` lines 40-44:

```python
from cachetools import TTLCache

# Module-level cache for loaded model bundles, keyed by model version ID.
# TTLCache evicts entries older than _CACHE_TTL_SECONDS and enforces maxsize.
_MAX_CACHE_ENTRIES = 3
_CACHE_TTL_SECONDS = 3600  # 1 hour
_model_cache = TTLCache(maxsize=_MAX_CACHE_ENTRIES, ttl=_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()
```

Edit the eviction loop in `_load_bundle` (lines 159-164). TTLCache handles eviction internally — simplify:

```python
    bundle = joblib.load(resolved_path)

    with _cache_lock:
        # Re-check after expensive load — another worker may have cached it first
        if version_id in _model_cache:
            return _model_cache[version_id]
        # TTLCache auto-evicts LRU + expired entries on set
        _model_cache[version_id] = bundle
        logger.info("Cached model version %s (cache size now %d)", version_id, len(_model_cache))
    return bundle
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_predictor_cache.py -v
```
Expected: PASS — both tests green.

- [ ] **Step 6: Run existing predictor tests**

```bash
cd backend && python -m pytest tests/ -k predictor -v
```
Expected: all existing predictor tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.in backend/requirements.txt \
        backend/apps/ml_engine/services/predictor.py \
        backend/tests/test_predictor_cache.py
git commit -m "fix(ml): replace model cache dict with TTLCache (1h TTL, maxsize 3)"
```

---

## Task 5: Cap retry_llm_call sleep + jitter

**Files:**
- Modify: `backend/apps/agents/utils.py`
- Create: `backend/tests/test_retry_llm_call_sleep.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_retry_llm_call_sleep.py`:

```python
"""Sleep cap + jitter for retry_llm_call decorator."""
from unittest.mock import patch

import anthropic
import httpx
import pytest

from apps.agents.utils import retry_llm_call


class _FakeRateLimitError(anthropic.RateLimitError):
    def __init__(self):
        response = httpx.Response(429, request=httpx.Request("POST", "https://x"))
        super().__init__("rate limited", response=response, body=None)


class TestRetrySleepCap:
    @patch("apps.agents.utils.time.sleep")
    def test_sleep_is_capped(self, mock_sleep):
        """Each sleep must be <= MAX_BACKOFF_SECONDS to avoid blocking workers."""
        attempts = {"n": 0}

        @retry_llm_call(max_attempts=3, base_delay=10.0)  # Would produce 40s + 80s without cap
        def _flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _FakeRateLimitError()
            return "ok"

        result = _flaky()
        assert result == "ok"
        # Every sleep must be capped at MAX_BACKOFF_SECONDS (5s) + jitter (<=0.5s)
        for call in mock_sleep.call_args_list:
            delay = call.args[0]
            assert delay <= 5.5, f"sleep({delay}) exceeds cap"

    @patch("apps.agents.utils.time.sleep")
    def test_sleep_has_jitter(self, mock_sleep):
        """Two identical retry sequences must not produce identical sleep values."""
        sleeps_a = []
        sleeps_b = []

        for sink in (sleeps_a, sleeps_b):
            mock_sleep.reset_mock()
            attempts = {"n": 0}

            @retry_llm_call(max_attempts=3, base_delay=1.0)
            def _flaky():
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise _FakeRateLimitError()
                return "ok"

            _flaky()
            sink.extend(c.args[0] for c in mock_sleep.call_args_list)

        # With jitter, two runs will almost never produce identical sleep sequences
        assert sleeps_a != sleeps_b
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_retry_llm_call_sleep.py -v
```
Expected: FAIL — current impl uses `2 ** (attempt + 1) * base_delay = 40s` for base_delay=10, attempt=1, exceeding 5.5s cap; and produces identical sequences (no jitter).

- [ ] **Step 3: Add cap + jitter to retry_llm_call**

Edit `backend/apps/agents/utils.py`. Add at top:

```python
import random
```

Add constant after the logger definition (around line 12):

```python
MAX_BACKOFF_SECONDS = 5.0  # Cap any single sleep to avoid blocking Celery workers
```

Replace each `time.sleep(delay)` call (4 occurrences: rate limit, timeout, connection, 5xx status) with:

```python
                        capped = min(delay, MAX_BACKOFF_SECONDS) + random.uniform(0, 0.5)
                        time.sleep(capped)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_retry_llm_call_sleep.py -v
```
Expected: PASS.

- [ ] **Step 5: Run existing retry tests**

```bash
cd backend && python -m pytest tests/ -k retry_llm -v
```
Expected: existing retry behavior tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/agents/utils.py \
        backend/tests/test_retry_llm_call_sleep.py
git commit -m "fix(agents): cap retry_llm_call sleep at 5s + add jitter"
```

---

## Task 6: Full test suite + open PR

**Files:** none (test runner + gh pr create).

- [ ] **Step 1: Run full frontend suite**

```bash
cd frontend && npm test -- --run
```
Expected: all tests pass.

- [ ] **Step 2: Run full backend unit suite (skip DB-dependent)**

```bash
cd backend && python -m pytest tests/ -v \
  --ignore=tests/test_marketing_pipeline.py \
  --ignore=tests/test_orchestrator.py \
  --ignore=tests/test_resume_pipeline.py \
  --ignore=tests/test_decision_waterfall.py \
  --ignore=tests/test_audit_fixes.py
```
Expected: all unit tests pass (DB-dependent suites pre-exist with Docker-Postgres dependency — out of scope).

- [ ] **Step 3: Push branch**

```bash
git push -u origin fix/memory-reliability-track-a
```

- [ ] **Step 4: Open PR**

```bash
gh pr create --title "fix: resolve frontend OOM + tighten memory/reliability (Track A)" --body "$(cat <<'EOF'
## Summary

Fixes 5 findings from the portfolio audit bundled into Track A (memory & reliability):

1. **React Query gcTime unbounded** → Likely root cause of frontend container exit-243 crash loop. Global 2min default + 30s on pollers.
2. **localStorage thrashing on form keystrokes** → Debounced to 500ms.
3. **Timer ref leaks in ApplicationsPage** → Cancel existing timers before pushing new ones.
4. **ML model cache had no TTL/LRU** → Replaced dict with `cachetools.TTLCache(maxsize=3, ttl=3600)`.
5. **`retry_llm_call` could block Celery workers for minutes** → Cap each sleep at 5s + add jitter.

## Test plan

- [x] 2 new frontend tests (debounce, timer cleanup)
- [x] 2 new backend test files (predictor cache TTL, retry sleep cap)
- [x] Full vitest + pytest unit suite green
- [ ] **Manual 30-min soak test** to confirm OOM is gone (recommend before merge)

## Out of scope

Tracks B–F (exception handling, bundle size, security, data correctness, code hygiene) deferred to follow-up PRs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

- [ ] **Step 5: Commit final touches if any**

If tests surfaced anything small, fix + commit. Otherwise mark done.

---

## Self-Review

**Spec coverage:**
- Spec finding #1 (React Query gcTime) → Task 1 ✅
- Spec finding #2 (localStorage debounce) → Task 2 ✅
- Spec finding #3 (timer cleanup) → Task 3 ✅
- Spec finding #4 (model cache TTL) → Task 4 ✅
- Spec finding #5 (Celery retry sleep) → Task 5 ✅ (minimal-safe variant: cap + jitter, not full refactor — spec's "Risks" section approves this trade-off)

**Placeholder scan:** No TBDs, no "similar to Task N", every code block is complete.

**Type consistency:**
- `MAX_BACKOFF_SECONDS` used consistently in Task 5 test + impl.
- `TTLCache(maxsize=_MAX_CACHE_ENTRIES, ttl=_CACHE_TTL_SECONDS)` consistent in Task 4.
- `gcTime: 30_000` consistent across pollers in Task 1.
- `DRAFT_KEY` unchanged in Task 2 (matches line 47 of existing file).

No gaps or contradictions found.
