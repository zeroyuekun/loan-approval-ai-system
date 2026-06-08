# Dashboard refit PR-1 — real latency + LLM spend tiles

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `avgProcessingTime="2.3s"` on the dashboard home with two real, data-derived tiles — "Today's Decisions" (count + p95 latency from `AgentRun.total_time_ms` over the rolling 24h) and "LLM Spend" (today's $ vs $5 cap from `ApiBudgetGuard`). Drop the "Active Model" tile (will live on the future Model Health page from PR-4).

**Architecture:** Extend the existing `DashboardStatsView` (`backend/apps/loans/views.py:183`) with five new fields. Add a `useDashboardStats` React Query hook (the endpoint and `loansApi.getDashboardStats` client method already exist; the page just doesn't use them yet). Refactor `StatsCards` to support optional subtitle + progress-bar rendering. Wire the dashboard page to call the new hook and drop the bogus literal.

**Tech Stack:** Django 5 / DRF, NumPy (already a dep — used for the percentile compute), TanStack Query (existing), Vitest + React Testing Library + MSW (existing test stack), pytest-django.

**Source spec:** [`docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md`](../specs/2026-05-25-dashboard-persona-refit-design.md) — this plan is scoped to **PR-1 (Change 1) only**. PR-2, PR-3, PR-4 each get their own plan when their turn comes.

---

## File map

**Backend — modify:**
- `backend/apps/loans/views.py` — `DashboardStatsView._compute_stats()` (lines 193-277): add 7 new fields (`decision_latency_p50_ms_24h`, `decision_latency_p95_ms_24h`, `decisions_24h_count`, `llm_spend_today_usd`, `llm_spend_cap_usd`, `approved_count`, `denied_count`).

**Backend — create:**
- `backend/apps/loans/tests/test_dashboard_stats.py` — new test file covering the extended response shape, with one happy-path test and one Redis-unavailable test.

**Frontend — modify:**
- `frontend/src/types/index.ts` — add `DashboardStats` interface near other API response types (after line 474 region where `PaginatedResponse` is defined is a good neighbour).
- `frontend/src/components/dashboard/StatsCards.tsx` — change `StatsCardsProps`; render optional subtitle + progress bar.
- `frontend/src/__tests__/components/StatsCards.test.tsx` — update fixtures + assertions for the new prop shape.
- `frontend/src/app/dashboard/page.tsx` — wire `useDashboardStats`, drop hardcoded `"2.3s"`, eliminate the `useApplications({status: 'approved'})` and `useApplications({status: 'denied'})` redundant queries (counts now come from `dashboard-stats`).
- `frontend/src/__tests__/pages/DashboardPage.test.tsx` — add MSW handler for `/loans/dashboard-stats/`; update existing assertions.

**Frontend — create:**
- `frontend/src/hooks/useDashboardStats.ts` — small `useQuery` wrapper around `loansApi.getDashboardStats()`.
- `frontend/src/__tests__/hooks/useDashboardStats.test.tsx` — hook test with MSW.

**Total:** 4 modified backend files (1 source + 1 new test file), 7 frontend touchpoints (3 modified + 2 created sources, 2 modified + 1 created tests). All within the dashboard tile slice — no churn elsewhere.

---

## Task 1: Backend — extend `DashboardStatsView` with latency percentiles + LLM spend + raw approved/denied counts

**Files:**
- Modify: `backend/apps/loans/views.py` (lines 193-277)
- Create: `backend/apps/loans/tests/test_dashboard_stats.py`

- [ ] **Step 1.1: Write the failing test (full file content)**

Create `backend/apps/loans/tests/test_dashboard_stats.py`:

```python
"""Tests for DashboardStatsView — covers the PR-1 extension fields
(p50/p95 decision latency, 24h decision count, LLM spend, raw
approved/denied counts).
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.loans.models import LoanApplication

User = get_user_model()


@pytest.fixture
def officer_user(db):
    return User.objects.create_user(
        username="officer_dashstats",
        password="test1234",
        email="officer@aussieloanai.test",
        role="officer",
    )


@pytest.fixture
def api_client(officer_user):
    client = APIClient()
    client.force_authenticate(user=officer_user)
    return client


def _make_decided_app(applicant, status, loan_amount=Decimal("25000")):
    return LoanApplication.objects.create(
        applicant=applicant,
        annual_income=Decimal("85000"),
        credit_score=700,
        loan_amount=loan_amount,
        loan_term_months=36,
        debt_to_income=Decimal("0.30"),
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
        status=status,
    )


def _make_run(application, total_time_ms, created_at=None, status="completed"):
    run = AgentRun.objects.create(
        application=application,
        status=status,
        total_time_ms=total_time_ms,
    )
    if created_at is not None:
        # auto_now_add prevents direct assignment on create
        AgentRun.objects.filter(pk=run.pk).update(created_at=created_at)
        run.refresh_from_db()
    return run


class TestDashboardStatsExtensions:
    """Verify the new PR-1 fields are present, typed, and computed correctly."""

    @pytest.mark.django_db
    @patch("apps.loans.views.ApiBudgetGuard")
    def test_response_includes_all_new_fields(
        self, mock_budget_class, api_client, officer_user
    ):
        # Arrange: budget stub returns known spend
        mock_budget_class.return_value.get_daily_stats.return_value = {
            "calls": 12,
            "tokens": 4500,
            "cost_usd": 1.23,
            "budget_limit_usd": 5.0,
            "call_limit": 500,
            "circuit_breaker_open": False,
        }
        # 5 completed AgentRuns inside the 24h window with known latencies
        app = _make_decided_app(officer_user, status="approved")
        for ms in (1000, 2000, 3000, 4000, 5000):
            _make_run(app, total_time_ms=ms)
        # One older run that must be excluded from the 24h percentiles
        _make_run(app, total_time_ms=999999, created_at=timezone.now() - timedelta(hours=48))

        # Act
        resp = api_client.get(reverse("dashboard-stats"))

        # Assert
        assert resp.status_code == 200
        data = resp.json()

        # New fields present
        assert "decision_latency_p50_ms_24h" in data
        assert "decision_latency_p95_ms_24h" in data
        assert "decisions_24h_count" in data
        assert "llm_spend_today_usd" in data
        assert "llm_spend_cap_usd" in data
        assert "approved_count" in data
        assert "denied_count" in data

        # Percentiles computed over the 24h window only (5 in-window samples;
        # the 999999 outlier from 48h ago must NOT pull p95 up)
        assert data["decisions_24h_count"] == 5
        assert data["decision_latency_p50_ms_24h"] == 3000
        # numpy default percentile interpolation puts p95 between 4000 and 5000;
        # exact value with linear interpolation on 5 samples is 4800
        assert 4500 <= data["decision_latency_p95_ms_24h"] <= 5000

        # LLM spend pulled from stubbed budget
        assert data["llm_spend_today_usd"] == 1.23
        assert data["llm_spend_cap_usd"] == 5.0

        # Approved / denied raw counts (1 approved app created above; 0 denied)
        assert data["approved_count"] == 1
        assert data["denied_count"] == 0

    @pytest.mark.django_db
    @patch("apps.loans.views.ApiBudgetGuard")
    def test_handles_no_runs_in_window(
        self, mock_budget_class, api_client, officer_user
    ):
        mock_budget_class.return_value.get_daily_stats.return_value = {
            "calls": 0, "tokens": 0, "cost_usd": 0.0,
            "budget_limit_usd": 5.0, "call_limit": 500,
            "circuit_breaker_open": False,
        }
        # No AgentRuns at all
        resp = api_client.get(reverse("dashboard-stats"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["decisions_24h_count"] == 0
        assert data["decision_latency_p50_ms_24h"] is None
        assert data["decision_latency_p95_ms_24h"] is None
        assert data["llm_spend_today_usd"] == 0.0

    @pytest.mark.django_db
    @patch("apps.loans.views.ApiBudgetGuard")
    def test_handles_budget_guard_failure_gracefully(
        self, mock_budget_class, api_client, officer_user
    ):
        # Budget call blows up (e.g. Redis truly broken).
        # The view must still return a 200 with zeroed spend, not 500.
        mock_budget_class.return_value.get_daily_stats.side_effect = Exception("redis dead")
        resp = api_client.get(reverse("dashboard-stats"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_spend_today_usd"] == 0.0
        assert data["llm_spend_cap_usd"] == 5.0  # safe default
```

- [ ] **Step 1.2: Run the test to verify it fails**

Run:
```bash
docker compose exec backend pytest apps/loans/tests/test_dashboard_stats.py -v
```

Expected: 3 tests, all fail. Most likely failure mode: `KeyError: 'decision_latency_p50_ms_24h'` (the new keys don't exist in the response yet). If `ApiBudgetGuard` import path patch fails, that's also expected — fixed in Step 1.3 when we add the import to `views.py`.

- [ ] **Step 1.3: Implement the backend changes**

Edit `backend/apps/loans/views.py`. The `_compute_stats` method (current lines 193-277) needs:

1. A new import at the top of the file (after existing imports, around line 14):

```python
from apps.agents.services.api_budget import ApiBudgetGuard
```

2. A new import for `numpy` inside `_compute_stats` (lazy-imported to keep startup fast — there are precedents in this codebase for lazy ML imports). Add near the existing inline imports (after the `from django.utils import timezone` line):

```python
import numpy as np
```

3. Replace the entire `_compute_stats` method body to add the new computations. Show the full replacement method (this preserves all existing fields AND adds the 7 new ones):

```python
    def _compute_stats(self):
        from datetime import timedelta

        import numpy as np
        from django.db.models import Avg, Count, Q
        from django.db.models.functions import TruncDate
        from django.utils import timezone

        from apps.agents.models import AgentRun
        from apps.ml_engine.models import ModelVersion

        now = timezone.now()
        last_24h = now - timedelta(hours=24)

        # Total applications
        total = LoanApplication.objects.count()

        # Approval rate (lifetime) — and raw counts for the donut chart
        decided = LoanApplication.objects.filter(status__in=["approved", "denied"])
        decided_count = decided.count()
        approved_count = decided.filter(status="approved").count()
        denied_count = decided_count - approved_count
        approval_rate = round(approved_count / decided_count * 100, 1) if decided_count > 0 else 0

        # Lifetime average processing time (kept for back-compat with any
        # current callers — new tiles use the 24h window below).
        avg_time = AgentRun.objects.filter(status="completed", total_time_ms__isnull=False).aggregate(
            avg=Avg("total_time_ms")
        )["avg"]
        avg_processing_seconds = round(avg_time / 1000, 1) if avg_time else None

        # 24h rolling decision latency window
        latencies_ms_24h = list(
            AgentRun.objects.filter(
                status="completed",
                total_time_ms__isnull=False,
                created_at__gte=last_24h,
            ).values_list("total_time_ms", flat=True)
        )
        decisions_24h_count = len(latencies_ms_24h)
        if latencies_ms_24h:
            p50_ms_24h, p95_ms_24h = (
                int(x) for x in np.percentile(latencies_ms_24h, [50, 95])
            )
        else:
            p50_ms_24h = None
            p95_ms_24h = None

        # LLM spend — safe-defaults if the budget guard cannot reach Redis
        # at all (already returns zeros on Redis error per
        # api_budget.py:234, but defend against the rare case where
        # ApiBudgetGuard itself raises during construction).
        try:
            budget_stats = ApiBudgetGuard().get_daily_stats()
            llm_spend_today_usd = float(budget_stats.get("cost_usd", 0.0))
            llm_spend_cap_usd = float(budget_stats.get("budget_limit_usd", 5.0))
        except Exception:
            llm_spend_today_usd = 0.0
            llm_spend_cap_usd = 5.0

        # Active model
        active_model = ModelVersion.objects.filter(is_active=True).first()

        # Daily application volume (last 30 days)
        thirty_days_ago = now - timedelta(days=30)
        daily_volume = list(
            LoanApplication.objects.filter(created_at__gte=thirty_days_ago)
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(count=Count("id"))
            .order_by("date")
        )

        # Daily approval rate (last 30 days)
        daily_approvals = list(
            LoanApplication.objects.filter(created_at__gte=thirty_days_ago, status__in=["approved", "denied"])
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total=Count("id"), approved=Count("id", filter=models.Q(status="approved")))
            .order_by("date")
        )
        approval_trend = [
            {"date": str(d["date"]), "rate": round(d["approved"] / d["total"] * 100, 1) if d["total"] > 0 else 0}
            for d in daily_approvals
        ]

        # Pipeline stats (single query instead of 4)
        pipeline_stats = AgentRun.objects.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            failed=Count("id", filter=Q(status="failed")),
            escalated=Count("id", filter=Q(status="escalated")),
        )
        pipeline_total = pipeline_stats["total"]
        pipeline_completed = pipeline_stats["completed"]
        pipeline_failed = pipeline_stats["failed"]
        pipeline_escalated = pipeline_stats["escalated"]

        return {
            "total_applications": total,
            "approval_rate": approval_rate,
            "approved_count": approved_count,
            "denied_count": denied_count,
            "avg_processing_seconds": avg_processing_seconds,
            "decision_latency_p50_ms_24h": p50_ms_24h,
            "decision_latency_p95_ms_24h": p95_ms_24h,
            "decisions_24h_count": decisions_24h_count,
            "llm_spend_today_usd": llm_spend_today_usd,
            "llm_spend_cap_usd": llm_spend_cap_usd,
            "active_model": {
                "name": f"{active_model.algorithm} v{active_model.version}" if active_model else None,
                "auc": float(active_model.auc_roc) if active_model and active_model.auc_roc else None,
            }
            if active_model
            else None,
            "daily_volume": [{"date": str(d["date"]), "count": d["count"]} for d in daily_volume],
            "approval_trend": approval_trend,
            "pipeline": {
                "total": pipeline_total,
                "completed": pipeline_completed,
                "failed": pipeline_failed,
                "escalated": pipeline_escalated,
                "success_rate": round(pipeline_completed / pipeline_total * 100, 1) if pipeline_total > 0 else 0,
            },
        }
```

- [ ] **Step 1.4: Run the tests to verify they pass**

Run:
```bash
docker compose exec backend pytest apps/loans/tests/test_dashboard_stats.py -v
```

Expected: all 3 tests pass.

Also run the wider stats suite to make sure nothing existing broke:

```bash
docker compose exec backend pytest apps/loans/tests/ -v
```

Expected: all green.

- [ ] **Step 1.5: Cache-bust check**

`DashboardStatsView.get()` caches the response for 30s under key `"dashboard_stats"`. The new fields will not appear in any in-flight cached payload — the test above force-reaches `_compute_stats` because it runs in a fresh test DB with no warm cache, so this is informational only. Note in the commit body that operators may need to wait up to 30s after deploy for new fields to appear, or restart Redis.

- [ ] **Step 1.6: Commit**

```bash
git add backend/apps/loans/views.py backend/apps/loans/tests/test_dashboard_stats.py
git commit -m "$(cat <<'EOF'
feat(dashboard): extend stats endpoint with 24h latency + LLM spend

Adds 7 fields to /api/v1/loans/dashboard-stats/:
- decision_latency_p50_ms_24h / decision_latency_p95_ms_24h
- decisions_24h_count
- llm_spend_today_usd / llm_spend_cap_usd
- approved_count / denied_count

Percentiles computed via numpy over AgentRun.total_time_ms from the
rolling 24h window. LLM spend reads ApiBudgetGuard.get_daily_stats()
with a defensive fallback if the guard raises. Existing fields
(avg_processing_seconds, pipeline, daily_volume, etc.) preserved.

Backend half of PR-1 of the dashboard persona refit
(docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md).
30s cache TTL on the endpoint is unchanged — new fields will
materialise within one cache window after deploy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: TypeScript — add `DashboardStats` interface

**Files:**
- Modify: `frontend/src/types/index.ts` (add new interface near line 474 where `PaginatedResponse` lives)

- [ ] **Step 2.1: Add the type**

Append this block to `frontend/src/types/index.ts` (placement: after the `PaginatedResponse` interface; if the file ends with a newline before EOF, insert just before that newline):

```typescript
// Dashboard stats — response shape of GET /loans/dashboard-stats/.
// Fields added in PR-1 of the dashboard persona refit are marked.
export interface DashboardStats {
  total_applications: number
  approval_rate: number
  // PR-1 additions:
  approved_count: number
  denied_count: number
  avg_processing_seconds: number | null
  decision_latency_p50_ms_24h: number | null
  decision_latency_p95_ms_24h: number | null
  decisions_24h_count: number
  llm_spend_today_usd: number
  llm_spend_cap_usd: number
  // end PR-1 additions
  active_model: {
    name: string | null
    auc: number | null
  } | null
  daily_volume: Array<{ date: string; count: number }>
  approval_trend: Array<{ date: string; rate: number }>
  pipeline: {
    total: number
    completed: number
    failed: number
    escalated: number
    success_rate: number
  }
}
```

- [ ] **Step 2.2: Type-check passes**

Run:
```bash
docker compose exec frontend npx tsc --noEmit
```

(If you don't have a running `frontend` container, run from a host shell inside `frontend/`: `npx tsc --noEmit`.)

Expected: no new TS errors. (Pre-existing errors unrelated to this change can be ignored, but note them in the commit body so they're not surprising.)

- [ ] **Step 2.3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "$(cat <<'EOF'
feat(types): add DashboardStats interface for refit hook

Mirrors backend DashboardStatsView response shape including the
seven fields added in the PR-1 backend change. Inline comments mark
which fields are PR-1 additions vs. pre-existing for future readers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Frontend hook — `useDashboardStats`

**Files:**
- Create: `frontend/src/hooks/useDashboardStats.ts`
- Create: `frontend/src/__tests__/hooks/useDashboardStats.test.tsx`

- [ ] **Step 3.1: Write the failing test (full file content)**

Create `frontend/src/__tests__/hooks/useDashboardStats.test.tsx`:

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { useDashboardStats } from '@/hooks/useDashboardStats'

const API_URL = 'http://localhost:8000/api/v1'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useDashboardStats', () => {
  it('returns stats payload on success', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () =>
        HttpResponse.json({
          total_applications: 42,
          approval_rate: 70.5,
          approved_count: 30,
          denied_count: 12,
          avg_processing_seconds: 2.4,
          decision_latency_p50_ms_24h: 1800,
          decision_latency_p95_ms_24h: 4200,
          decisions_24h_count: 17,
          llm_spend_today_usd: 1.23,
          llm_spend_cap_usd: 5.0,
          active_model: { name: 'xgb v3', auc: 0.87 },
          daily_volume: [],
          approval_trend: [],
          pipeline: { total: 0, completed: 0, failed: 0, escalated: 0, success_rate: 0 },
        })
      )
    )

    const { result } = renderHook(() => useDashboardStats(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.decisions_24h_count).toBe(17)
    expect(result.current.data?.llm_spend_today_usd).toBe(1.23)
    expect(result.current.data?.decision_latency_p95_ms_24h).toBe(4200)
  })

  it('surfaces error state on 500', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () =>
        new HttpResponse(null, { status: 500 })
      )
    )

    const { result } = renderHook(() => useDashboardStats(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
```

- [ ] **Step 3.2: Run test to verify it fails**

Run:
```bash
docker compose exec frontend npm test -- src/__tests__/hooks/useDashboardStats.test.tsx
```

Expected: FAIL with `Cannot find module '@/hooks/useDashboardStats'` (the hook doesn't exist yet).

- [ ] **Step 3.3: Implement the hook (full file content)**

Create `frontend/src/hooks/useDashboardStats.ts`:

```typescript
'use client'

import { useQuery } from '@tanstack/react-query'
import { loansApi } from '@/lib/api'
import type { DashboardStats } from '@/types'

/**
 * Fetches the operator-grade dashboard stats payload from
 * /api/v1/loans/dashboard-stats/. Includes the rolling-24h decision
 * latency percentiles and today's LLM spend, both added in PR-1 of
 * the dashboard persona refit.
 *
 * Cached for 30 seconds server-side (DashboardStatsView), so a 30s
 * staleTime on the client side avoids redundant fetches.
 */
export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const { data } = await loansApi.getDashboardStats()
      return data
    },
    staleTime: 30 * 1000,
  })
}
```

- [ ] **Step 3.4: Run test to verify it passes**

Run:
```bash
docker compose exec frontend npm test -- src/__tests__/hooks/useDashboardStats.test.tsx
```

Expected: both tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add frontend/src/hooks/useDashboardStats.ts frontend/src/__tests__/hooks/useDashboardStats.test.tsx
git commit -m "$(cat <<'EOF'
feat(hooks): add useDashboardStats hook for the refit

Thin TanStack Query wrapper around the pre-existing
loansApi.getDashboardStats() client. 30s client staleTime matches
the server-side 30s cache on DashboardStatsView. Returns the typed
DashboardStats payload added in the prior commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Refactor `StatsCards` component to support subtitle + progress-bar tiles

**Files:**
- Modify: `frontend/src/components/dashboard/StatsCards.tsx`
- Modify: `frontend/src/__tests__/components/StatsCards.test.tsx`

- [ ] **Step 4.1: Update the test first (failing — full file content)**

Replace `frontend/src/__tests__/components/StatsCards.test.tsx` with:

```tsx
import { render, screen } from '@testing-library/react'
import { StatsCards } from '@/components/dashboard/StatsCards'

describe('StatsCards', () => {
  const defaultProps = {
    totalApplications: 1500,
    approvalRate: 68.5,
    todayDecisions: { count: 17, p95LatencyMs: 4200 },
    llmSpend: { spentUsd: 1.23, capUsd: 5.0 },
  }

  it('renders all four stat cards', () => {
    render(<StatsCards {...defaultProps} />)

    expect(screen.getByText('Total Applications')).toBeInTheDocument()
    expect(screen.getByText('Approval Rate')).toBeInTheDocument()
    expect(screen.getByText("Today's Decisions")).toBeInTheDocument()
    expect(screen.getByText('LLM Spend')).toBeInTheDocument()
  })

  it('formats total applications with locale separator', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('1,500')).toBeInTheDocument()
  })

  it('formats approval rate with one decimal', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('68.5%')).toBeInTheDocument()
  })

  it('shows today’s decision count and p95 latency in seconds', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('17')).toBeInTheDocument()
    // 4200ms → "p95 4.2s"
    expect(screen.getByText(/p95 4\.2s/i)).toBeInTheDocument()
  })

  it('shows LLM spend as dollars vs cap with progress', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('$1.23')).toBeInTheDocument()
    expect(screen.getByText(/\/ \$5\.00 cap/i)).toBeInTheDocument()
    // Progress bar present
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
  })

  it('renders fallback when p95 latency is null (no 24h decisions yet)', () => {
    render(
      <StatsCards
        {...defaultProps}
        todayDecisions={{ count: 0, p95LatencyMs: null }}
      />
    )
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText(/no decisions yet/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 4.2: Run test to verify it fails**

Run:
```bash
docker compose exec frontend npm test -- src/__tests__/components/StatsCards.test.tsx
```

Expected: FAIL — props mismatch (the old component still expects `avgProcessingTime`, `activeModel`).

- [ ] **Step 4.3: Implement the new component (full file replacement)**

Replace `frontend/src/components/dashboard/StatsCards.tsx` with:

```tsx
'use client'

import { FileText, CheckCircle, Clock, DollarSign } from 'lucide-react'

interface TodayDecisions {
  count: number
  p95LatencyMs: number | null
}

interface LlmSpend {
  spentUsd: number
  capUsd: number
}

interface StatsCardsProps {
  totalApplications: number
  approvalRate: number
  todayDecisions: TodayDecisions
  llmSpend: LlmSpend
}

function formatLatencySeconds(ms: number | null): string {
  if (ms === null) return 'no decisions yet'
  return `p95 ${(ms / 1000).toFixed(1)}s`
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`
}

export function StatsCards({
  totalApplications,
  approvalRate,
  todayDecisions,
  llmSpend,
}: StatsCardsProps) {
  const spendPct = Math.min(100, (llmSpend.spentUsd / llmSpend.capUsd) * 100)
  const spendWarning = spendPct >= 80

  const stats = [
    {
      kind: 'plain' as const,
      title: 'Total Applications',
      value: totalApplications.toLocaleString('en-AU'),
      subtitle: undefined,
      icon: FileText,
      gradient: 'from-blue-500 via-blue-600 to-indigo-600',
      shadowColor: 'shadow-blue-500/25',
    },
    {
      kind: 'plain' as const,
      title: 'Approval Rate',
      value: `${approvalRate.toFixed(1)}%`,
      subtitle: undefined,
      icon: CheckCircle,
      gradient: 'from-emerald-500 via-emerald-500 to-teal-600',
      shadowColor: 'shadow-emerald-500/25',
    },
    {
      kind: 'plain' as const,
      title: "Today's Decisions",
      value: todayDecisions.count.toLocaleString('en-AU'),
      subtitle: formatLatencySeconds(todayDecisions.p95LatencyMs),
      icon: Clock,
      gradient: 'from-amber-500 via-orange-500 to-red-400',
      shadowColor: 'shadow-amber-500/25',
    },
    {
      kind: 'spend' as const,
      title: 'LLM Spend',
      value: formatUsd(llmSpend.spentUsd),
      subtitle: `/ ${formatUsd(llmSpend.capUsd)} cap`,
      progressPct: spendPct,
      warning: spendWarning,
      icon: DollarSign,
      gradient: spendWarning
        ? 'from-rose-500 via-red-500 to-orange-600'
        : 'from-violet-500 via-purple-600 to-fuchsia-600',
      shadowColor: spendWarning ? 'shadow-rose-500/25' : 'shadow-violet-500/25',
    },
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <div
          key={stat.title}
          className="group relative rounded-xl bg-white p-5 sheen-card gradient-border"
        >
          <div className="flex items-start justify-between">
            <div className="space-y-2 min-w-0">
              <p className="text-sm font-medium text-muted-foreground">{stat.title}</p>
              <p className="text-2xl font-bold tracking-tight">{stat.value}</p>
              {stat.subtitle && (
                <p className="text-xs text-muted-foreground">{stat.subtitle}</p>
              )}
              {stat.kind === 'spend' && (
                <div
                  role="progressbar"
                  aria-valuenow={Math.round(stat.progressPct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 mt-2"
                >
                  <div
                    className={`h-full transition-all ${
                      stat.warning ? 'bg-rose-500' : 'bg-violet-500'
                    }`}
                    style={{ width: `${stat.progressPct}%` }}
                  />
                </div>
              )}
            </div>
            <div
              className={`rounded-xl bg-gradient-to-br ${stat.gradient} p-2.5 shadow-lg ${stat.shadowColor} border border-white/20`}
            >
              <stat.icon className="h-5 w-5 text-white drop-shadow-sm" aria-hidden="true" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run:
```bash
docker compose exec frontend npm test -- src/__tests__/components/StatsCards.test.tsx
```

Expected: all 6 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add frontend/src/components/dashboard/StatsCards.tsx frontend/src/__tests__/components/StatsCards.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): refit StatsCards with today's decisions + LLM spend

Removes the Avg Processing tile (was fed the hardcoded string "2.3s")
and the Active Model tile (will move to Model Health page in PR-4
of the refit). Adds two new tiles:

- Today's Decisions: 24h count + p95 latency in seconds
- LLM Spend: today's $ vs $5 cap with a coloured progress bar that
  turns rose-red when >= 80% of cap

Subtitle and progress bar are conditional so the component remains
small and TDD-friendly. Test coverage extended from 4 cases to 6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wire dashboard page to the new hook + drop the hardcoded literal

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx`
- Modify: `frontend/src/__tests__/pages/DashboardPage.test.tsx`

- [ ] **Step 5.1: Update the page test first (failing — full file content)**

Replace `frontend/src/__tests__/pages/DashboardPage.test.tsx` with:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard',
  useSearchParams: () => new URLSearchParams(),
}))

// Recharts uses ResizeObserver which is not available in jsdom.
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverMock)

import DashboardPage from '@/app/dashboard/page'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider
        value={{
          user: { ...mockUser, role: 'admin' as const },
          isLoading: false,
          login: vi.fn(),
          register: vi.fn(),
          logout: vi.fn(),
        }}
      >
        <DashboardPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

const baseStats = {
  total_applications: 42,
  approval_rate: 70.5,
  approved_count: 30,
  denied_count: 12,
  avg_processing_seconds: 2.4,
  decision_latency_p50_ms_24h: 1800,
  decision_latency_p95_ms_24h: 4200,
  decisions_24h_count: 17,
  llm_spend_today_usd: 1.23,
  llm_spend_cap_usd: 5.0,
  active_model: { name: 'xgb v3', auc: 0.87 },
  daily_volume: [],
  approval_trend: [],
  pipeline: { total: 0, completed: 0, failed: 0, escalated: 0, success_rate: 0 },
}

describe('DashboardPage', () => {
  it('shows loading skeletons initially', () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => new Promise(() => {})),
      http.get(`${API_URL}/loans/dashboard-stats/`, () => new Promise(() => {}))
    )
    renderPage()
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('renders new operator tiles with real numbers when stats load', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () => HttpResponse.json(baseStats)),
      http.get(`${API_URL}/loans/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 'l1',
              status: 'approved',
              applicant: mockUser,
              loan_amount: 25000,
              created_at: '2024-06-01T00:00:00Z',
              updated_at: '2024-06-01T00:00:00Z',
              decision: {
                decision: 'approved',
                confidence: 0.9,
                risk_score: 0.2,
                model_version: 'rf-v2.1',
                reasoning: 'Good',
                created_at: '2024-06-01T00:00:00Z',
              },
            },
          ],
        })
      )
    )
    renderPage()
    // Two of the new tiles should be visible
    await waitFor(() => expect(screen.getByText("Today's Decisions")).toBeInTheDocument())
    expect(screen.getByText('LLM Spend')).toBeInTheDocument()
    // The new p95 latency subtitle is shown
    expect(screen.getByText(/p95 4\.2s/i)).toBeInTheDocument()
    // Hardcoded "2.3s" must NOT appear anywhere
    expect(screen.queryByText('2.3s')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 5.2: Run page test to verify it fails**

Run:
```bash
docker compose exec frontend npm test -- src/__tests__/pages/DashboardPage.test.tsx
```

Expected: FAIL — page still passes the old props (`avgProcessingTime`, `activeModel`), so the new strings ("Today's Decisions", "LLM Spend") will not render.

- [ ] **Step 5.3: Implement the page change (full file replacement)**

Replace `frontend/src/app/dashboard/page.tsx` with:

```tsx
'use client'

import { useApplications } from '@/hooks/useApplications'
import { useDashboardStats } from '@/hooks/useDashboardStats'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { ApprovalRateChart } from '@/components/dashboard/ApprovalRateChart'
import { RecentApplications } from '@/components/dashboard/RecentApplications'
import { Skeleton } from '@/components/ui/skeleton'

export default function DashboardPage() {
  const { data: applicationsData, isLoading: appsLoading } = useApplications({ page_size: 5 })
  const { data: stats, isLoading: statsLoading } = useDashboardStats()

  const applications = applicationsData?.results || []

  if (appsLoading || statsLoading || !stats) {
    return (
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <StatsCards
        totalApplications={stats.total_applications}
        approvalRate={stats.approval_rate}
        todayDecisions={{
          count: stats.decisions_24h_count,
          p95LatencyMs: stats.decision_latency_p95_ms_24h,
        }}
        llmSpend={{
          spentUsd: stats.llm_spend_today_usd,
          capUsd: stats.llm_spend_cap_usd,
        }}
      />

      <div className="grid gap-6 md:grid-cols-2">
        <ApprovalRateChart approved={stats.approved_count} denied={stats.denied_count} />
        <RecentApplications applications={applications} />
      </div>
    </div>
  )
}
```

Key deletions / changes (for the reviewer to recognise in the diff):

- The hardcoded string `avgProcessingTime="2.3s"` is gone.
- The two redundant `useApplications({ page_size: 1, status: 'approved' / 'denied' })` queries are gone — counts now come from `stats.approved_count` / `stats.denied_count`.
- The `useModelMetrics` call is gone (was only used to derive `activeModelName` for the now-removed tile).
- `ApprovalRateChart` is unchanged (PR-2 of the refit removes it; this PR leaves it).

- [ ] **Step 5.4: Run page test to verify it passes**

Run:
```bash
docker compose exec frontend npm test -- src/__tests__/pages/DashboardPage.test.tsx
```

Expected: both tests pass.

- [ ] **Step 5.5: Run the full frontend suite to catch collateral damage**

Run:
```bash
docker compose exec frontend npm test
```

Expected: all tests pass. If anything fails outside `StatsCards`/`DashboardPage`/`useDashboardStats`, investigate before continuing — likely an unrelated regression that should be triaged separately and not bundled into this PR.

- [ ] **Step 5.6: Commit**

```bash
git add frontend/src/app/dashboard/page.tsx frontend/src/__tests__/pages/DashboardPage.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): wire useDashboardStats; remove hardcoded 2.3s literal

Dashboard home now derives all four tile values from the
/loans/dashboard-stats/ endpoint instead of three separate
useApplications queries + a useModelMetrics query + the hardcoded
"2.3s" string.

The donut chart and recent-applications list are unchanged — they
will be touched in PR-2 of the dashboard persona refit (operator-
grade dashboard home with status strip).

Closes PR-1 of docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Smoke test in a real browser

**Files:** none — manual verification step. No commit.

- [ ] **Step 6.1: Start the stack (if not already running)**

```bash
docker compose up -d
```

Wait for `backend` and `frontend` healthchecks to pass (≈30s).

- [ ] **Step 6.2: Seed data and run the pipeline at least once so AgentRun rows exist**

If no seed data exists yet:

```bash
docker compose exec backend bash scripts/init_db.sh
docker compose exec backend bash scripts/seed_data.sh
```

This will create applications and run the pipeline on them, producing `AgentRun` rows with non-null `total_time_ms`.

- [ ] **Step 6.3: Open the dashboard and verify**

Navigate to `http://localhost:3000/dashboard` and login as `admin` / `admin1234`. Verify:

1. The four tiles show: Total Applications (real count), Approval Rate (real %), Today's Decisions (real count + p95 in seconds), LLM Spend ($ value + progress bar against $5.00 cap).
2. **The literal text `2.3s` does not appear anywhere on the page.** (View source / inspect to confirm.)
3. Browser devtools Network tab shows exactly one request to `/api/v1/loans/dashboard-stats/` (and one to `/api/v1/loans/?page_size=5` for the recent-applications panel). The redundant `?status=approved` and `?status=denied` queries are gone.
4. No console errors.
5. If `decisions_24h_count` is 0 (because nothing has been processed in the last 24h after a fresh seed), the Today's Decisions tile shows `0` with subtitle "no decisions yet" rather than crashing.

- [ ] **Step 6.4: If anything fails, do NOT commit a fix on top — fix the originating task**

If smoke catches a regression, identify which task's commit introduced the bad behaviour, revert/amend that commit (or add a follow-up commit referencing it), and re-run from Step 6.1. The principle: each task's commit must ship a green stack on its own.

- [ ] **Step 6.5: Optional — refresh the README screenshot for `04-model-metrics.png`**

PR-1 does not change the Model Metrics screenshot, but it does change `01-dashboard.png`. Refresh that screenshot at this stage. From the host:

```bash
# Take a fresh screenshot of localhost:3000/dashboard at 1440x900
# and save to docs/screenshots/01-dashboard.png
```

Commit:

```bash
git add docs/screenshots/01-dashboard.png
git commit -m "docs(screenshots): refresh dashboard.png for PR-1 tile refit

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Open the PR

After all tasks commit cleanly:

```bash
git push -u origin feat/dashboard-persona-refit

gh pr create \
  --base master \
  --title "feat(dashboard): real latency + LLM spend tiles (PR-1 of refit)" \
  --body "$(cat <<'EOF'
## Summary

Implements **PR-1** of the dashboard persona refit
([spec](docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md)):
replaces the hardcoded \`avgProcessingTime=\"2.3s\"\` on the dashboard
home with two real, data-derived tiles.

- **Today's Decisions** — 24h decision count + p95 latency from
  \`AgentRun.total_time_ms\`, computed via numpy.percentile on the
  rolling 24h window.
- **LLM Spend** — today's $ vs $5 cap with a progress bar that turns
  rose-red when >= 80% of cap, read from \`ApiBudgetGuard.get_daily_stats()\`.

The Avg Processing and Active Model tiles are removed from the
dashboard home. Active Model returns on the consolidated Model
Health page in PR-4 of the refit.

Backend extends \`DashboardStatsView\` with 7 new fields:
\`decision_latency_p50_ms_24h\`, \`decision_latency_p95_ms_24h\`,
\`decisions_24h_count\`, \`llm_spend_today_usd\`, \`llm_spend_cap_usd\`,
\`approved_count\`, \`denied_count\`. All existing fields preserved.
30s server-side cache TTL unchanged.

## Test plan

- [ ] \`docker compose exec backend pytest apps/loans/tests/test_dashboard_stats.py -v\` — 3/3 pass
- [ ] \`docker compose exec frontend npm test\` — full frontend suite green
- [ ] Manual: open \`/dashboard\` as admin, confirm the literal \`2.3s\` is gone and the LLM spend progress bar reflects real Redis-tracked spend
- [ ] Manual: confirm browser Network tab shows one \`/loans/dashboard-stats/\` request and one \`/loans/?page_size=5\` request (down from four)
- [ ] CI: lint + test workflows green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(Per `feedback_master_push_requires_auth.md`: do not push to `master` directly; this PR is the merge path. Per `feedback_design_trust_delegation.md`: the user has pre-approved the spec; pushing the feature branch + opening a PR is in-scope.)

---

## Self-review notes (from plan author)

**Spec coverage check (PR-1 only):**
- ✅ Backend: stats endpoint extension (Task 1)
- ✅ Frontend hook (Task 3)
- ✅ Two new tile types in StatsCards (Task 4)
- ✅ Remove hardcoded `"2.3s"` (Task 5, Step 5.3)
- ✅ Update `StatsCards` test (Task 4, Step 4.1)
- ✅ Move "Active Model" off dashboard (Task 4 implicitly: not in new tile list)

**Placeholder scan:** no TBDs, no "implement later", every code block has full content, no "similar to Task N" references.

**Type consistency check:** field names match across backend response → TS interface → hook → component prop. Verified: `decision_latency_p95_ms_24h` (backend) → `decision_latency_p95_ms_24h` (TS interface) → `stats.decision_latency_p95_ms_24h` (page) → `p95LatencyMs` (component prop, deliberately renamed at the page→component boundary because the component shouldn't care about the 24h window — it just renders).

**Out-of-scope deferred to PR-2/3/4 as per spec, not added to this plan:** status strip (drift/fairness/SLA traffic lights), approval-rate donut removal, counterfactual surfacing on customer status, Model Health consolidation.
