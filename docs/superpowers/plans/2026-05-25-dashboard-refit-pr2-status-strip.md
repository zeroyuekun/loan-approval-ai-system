# Dashboard refit PR-2 — operator-grade status strip

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the approval-rate donut on the dashboard home with a four-indicator status strip (drift, fairness, pending human review with SLA, watchdog), and make `RecentApplications` rows directly navigate to the application detail page. The page becomes operator-grade — every element is "is something requiring action right now?" or "where do I drill in next?".

**Architecture:** Extend the existing `DashboardStatsView._compute_stats()` (PR-1) with a new `status_strip` field aggregating four sub-statuses derived from `DriftReport`, the active `ModelVersion.fairness_metrics` (via `check_fairness_gate()`), `AgentRun.status="escalated"` queue, and Redis `watchdog:health`. Frontend gets a new `<StatusStrip>` component with a traffic-light dot per indicator. `<RecentApplications>` rows become clickable. `<ApprovalRateChart>` (the donut) is deleted.

**Tech Stack:** Django 5 / DRF, Redis (already used by `ApiBudgetGuard` / `watchdog`), Next.js 15 / TanStack Query / Tailwind / shadcn-ui, Vitest + React Testing Library + MSW, pytest-django.

**Source spec:** [`docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md`](../specs/2026-05-25-dashboard-persona-refit-design.md) — Change 2. PR-1 already merged in concept (PR #191 open, branch `feat/dashboard-persona-refit`). PR-2 stacks on PR-1's branch; opens against `feat/dashboard-persona-refit` as base, retargets to master once PR-1 merges (per the user's stacked-PR convention).

**Out of scope:** PR-3 (counterfactual surfacing on customer status page), PR-4 (Model Health consolidation). Customer-facing status pages are untouched in PR-2.

---

## Branch setup

This PR stacks on PR-1. Before Task 1 begins, the executor creates the PR-2 branch off PR-1's HEAD:

```bash
git switch feat/dashboard-persona-refit   # PR-1 branch with commits 575d2aa→f391413
git switch -c feat/dashboard-persona-refit-pr2-status-strip
```

All commits in this plan land on `feat/dashboard-persona-refit-pr2-status-strip`.

---

## File map

**Backend — modify:**
- `backend/apps/loans/views.py` — `DashboardStatsView._compute_stats()`: add `status_strip` field with 4 sub-keys.

**Backend — create:**
- `backend/apps/loans/services/__init__.py` — empty package marker if it doesn't already exist (check first; `loans/services/fraud_detection.py` exists, so the dir is there — verify `__init__.py` exists or create it).
- `backend/apps/loans/services/dashboard_status.py` — new file with four pure functions: `drift_status()`, `fairness_status()`, `pending_review_status()`, `watchdog_status()`. Keeps the view thin and unit-testable.
- `backend/apps/loans/tests/test_dashboard_status.py` — test file covering each function + the merged `status_strip` payload.

**Frontend — modify:**
- `frontend/src/types/index.ts` — extend `DashboardStats` with `status_strip: DashboardStatusStrip` field; add the new interface.
- `frontend/src/components/dashboard/RecentApplications.tsx` — wrap rows in a click handler that navigates to `/dashboard/applications/{id}`; keep the existing applicant-name link to the customer page (don't break it; clicking the name link must not also trigger the row-level navigation).
- `frontend/src/__tests__/components/RecentApplications.test.tsx` — IF it exists, update; otherwise create.
- `frontend/src/app/dashboard/page.tsx` — wire new `<StatusStrip>`; delete `<ApprovalRateChart>` import + usage; widen the recent-applications panel to fill the deleted slot.
- `frontend/src/__tests__/pages/DashboardPage.test.tsx` — extend the existing fixture's `status_strip` field; add assertions for the strip + verify the donut is gone.

**Frontend — create:**
- `frontend/src/components/dashboard/StatusStrip.tsx` — new component (one file, ~150 LOC) with the 4 indicators.
- `frontend/src/__tests__/components/StatusStrip.test.tsx` — covers all four traffic-light states.

**Frontend — delete:**
- `frontend/src/components/dashboard/ApprovalRateChart.tsx` — the donut, removed.
- `frontend/src/__tests__/components/ApprovalRateChart.test.tsx` — if it exists, removed.

**Total:** 1 backend modify + 3 backend create (including test); 5 frontend modify + 2 frontend create + 1–2 frontend delete.

---

## Task 1: Backend service module — four pure status functions

**Files:**
- Create: `backend/apps/loans/services/__init__.py` (if missing)
- Create: `backend/apps/loans/services/dashboard_status.py`
- Create: `backend/apps/loans/tests/test_dashboard_status.py`

The view in Task 2 will consume these. Keeping them as pure functions (no DRF, no caching) makes them trivially testable.

- [ ] **Step 1.1: Check whether `backend/apps/loans/services/__init__.py` exists**

Run:
```bash
ls backend/apps/loans/services/__init__.py
```

If it does not exist, create it as an empty file:

```bash
mkdir -p backend/apps/loans/services
touch backend/apps/loans/services/__init__.py
```

If it exists, leave it alone.

- [ ] **Step 1.2: Write the failing test (full file content)**

Create `backend/apps/loans/tests/test_dashboard_status.py`:

```python
"""Tests for the four pure status functions feeding the dashboard
operator status strip (PR-2 of the dashboard persona refit).
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.agents.models import AgentRun
from apps.loans.models import LoanApplication
from apps.loans.services.dashboard_status import (
    compute_status_strip,
    drift_status,
    fairness_status,
    pending_review_status,
    watchdog_status,
)
from apps.ml_engine.models import DriftReport, ModelVersion

User = get_user_model()


@pytest.fixture
def active_model(db):
    return ModelVersion.objects.create(
        algorithm="xgb",
        version="test-1",
        file_path="/tmp/test.joblib",
        is_active=True,
        fairness_metrics={
            "gender": {"disparate_impact_ratio": 0.92},
            "age_bucket": {"disparate_impact_ratio": 0.85},
        },
    )


@pytest.fixture
def applicant(db):
    return User.objects.create_user(
        username="cust_strip", password="test1234", email="cust@test.invalid", role="customer"
    )


class TestDriftStatus:
    @pytest.mark.django_db
    def test_no_drift_reports_returns_unknown(self, active_model):
        result = drift_status(active_model)
        assert result["level"] == "unknown"
        assert "no reports" in result["detail"].lower()

    @pytest.mark.django_db
    def test_latest_report_dictates_level(self, active_model):
        # Older report, significant
        DriftReport.objects.create(
            model_version=active_model,
            report_date=date.today() - timedelta(days=7),
            period_start=date.today() - timedelta(days=14),
            period_end=date.today() - timedelta(days=7),
            psi_score=0.30,
            alert_level="significant",
        )
        # Newer report, none — this is what should be reported
        DriftReport.objects.create(
            model_version=active_model,
            report_date=date.today(),
            period_start=date.today() - timedelta(days=7),
            period_end=date.today(),
            psi_score=0.05,
            alert_level="none",
        )
        result = drift_status(active_model)
        assert result["level"] == "none"
        assert "0.05" in result["detail"]

    @pytest.mark.django_db
    def test_no_active_model_returns_unknown(self):
        result = drift_status(None)
        assert result["level"] == "unknown"


class TestFairnessStatus:
    @pytest.mark.django_db
    def test_passes_with_dir_above_threshold(self, active_model):
        # Both 0.92 and 0.85 are >= 0.80 (EEOC four-fifths)
        result = fairness_status(active_model)
        assert result["level"] == "pass"
        assert "0.85" in result["detail"]  # min DIR exposed

    @pytest.mark.django_db
    def test_fails_with_dir_below_threshold(self, active_model):
        active_model.fairness_metrics = {
            "gender": {"disparate_impact_ratio": 0.60},
        }
        active_model.save()
        result = fairness_status(active_model)
        assert result["level"] == "fail"
        assert "gender" in result["detail"]

    @pytest.mark.django_db
    def test_no_active_model_returns_unknown(self):
        result = fairness_status(None)
        assert result["level"] == "unknown"


class TestPendingReviewStatus:
    @pytest.mark.django_db
    def test_zero_pending_is_green(self, applicant):
        result = pending_review_status()
        assert result["level"] == "none"
        assert result["count"] == 0
        assert result["sla_breach"] is False

    @pytest.mark.django_db
    def test_pending_within_sla_is_amber(self, applicant):
        app = LoanApplication.objects.create(
            applicant=applicant,
            annual_income=Decimal("80000"),
            credit_score=700,
            loan_amount=Decimal("20000"),
            loan_term_months=36,
            debt_to_income=Decimal("0.30"),
            employment_length=5,
            purpose="personal",
            home_ownership="rent",
            status="review",
        )
        AgentRun.objects.create(application=app, status="escalated")
        result = pending_review_status()
        assert result["level"] == "moderate"
        assert result["count"] == 1
        assert result["sla_breach"] is False

    @pytest.mark.django_db
    def test_pending_past_sla_is_significant(self, applicant):
        app = LoanApplication.objects.create(
            applicant=applicant,
            annual_income=Decimal("80000"),
            credit_score=700,
            loan_amount=Decimal("20000"),
            loan_term_months=36,
            debt_to_income=Decimal("0.30"),
            employment_length=5,
            purpose="personal",
            home_ownership="rent",
            status="review",
        )
        run = AgentRun.objects.create(application=app, status="escalated")
        # Backdate to 30 hours ago
        AgentRun.objects.filter(pk=run.pk).update(
            created_at=timezone.now() - timedelta(hours=30)
        )
        result = pending_review_status()
        assert result["level"] == "significant"
        assert result["sla_breach"] is True
        assert result["oldest_age_hours"] >= 24


class TestWatchdogStatus:
    @patch("apps.loans.services.dashboard_status.redis.from_url")
    def test_no_key_means_stale(self, mock_from_url):
        mock_r = MagicMock()
        mock_r.hgetall.return_value = {}
        mock_from_url.return_value = mock_r
        result = watchdog_status()
        assert result["level"] == "unknown"
        assert "stale" in result["detail"].lower()

    @patch("apps.loans.services.dashboard_status.redis.from_url")
    def test_healthy_status(self, mock_from_url):
        mock_r = MagicMock()
        mock_r.hgetall.return_value = {
            b"status": b"healthy",
            b"consecutive_failures": b"0",
            b"last_check": b"2026-05-25T12:00:00+00:00",
        }
        mock_from_url.return_value = mock_r
        result = watchdog_status()
        assert result["level"] == "none"
        assert "healthy" in result["detail"].lower()

    @patch("apps.loans.services.dashboard_status.redis.from_url")
    def test_degraded_status(self, mock_from_url):
        mock_r = MagicMock()
        mock_r.hgetall.return_value = {
            b"status": b"degraded",
            b"consecutive_failures": b"2",
            b"last_check": b"2026-05-25T12:00:00+00:00",
        }
        mock_from_url.return_value = mock_r
        result = watchdog_status()
        assert result["level"] == "moderate"
        assert "2" in result["detail"]

    @patch("apps.loans.services.dashboard_status.redis.from_url")
    def test_redis_unreachable_is_unknown(self, mock_from_url):
        mock_from_url.side_effect = Exception("connection refused")
        result = watchdog_status()
        assert result["level"] == "unknown"
        assert "redis" in result["detail"].lower()


class TestComputeStatusStrip:
    @pytest.mark.django_db
    @patch("apps.loans.services.dashboard_status.redis.from_url")
    def test_returns_all_four_keys(self, mock_from_url, active_model):
        mock_r = MagicMock()
        mock_r.hgetall.return_value = {b"status": b"healthy"}
        mock_from_url.return_value = mock_r
        strip = compute_status_strip()
        assert set(strip.keys()) == {"drift", "fairness", "pending_review", "watchdog"}
        for k in strip:
            assert "level" in strip[k]
            assert "detail" in strip[k]
```

- [ ] **Step 1.3: Run the test to verify it fails**

Run:
```bash
docker compose exec backend pytest apps/loans/tests/test_dashboard_status.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'apps.loans.services.dashboard_status'` or `ImportError` — the module doesn't exist yet.

- [ ] **Step 1.4: Implement `dashboard_status.py` (full file content)**

Create `backend/apps/loans/services/dashboard_status.py`:

```python
"""Compute the four operator status-strip sub-statuses for the dashboard
home (PR-2 of the dashboard persona refit).

Each function returns a dict with at least:
    {
        "level": "none" | "moderate" | "significant" | "unknown",
        "detail": "human-readable single line",
    }

`pending_review_status` adds `count`, `oldest_age_hours`, `sla_breach`.
`watchdog_status` adds `last_check` when available.

These are pure functions — no caching, no DRF — so they're trivial to
unit-test. The caller (DashboardStatsView) is responsible for
30s-caching the assembled payload.
"""

from datetime import timedelta
import logging

import redis
from django.conf import settings
from django.utils import timezone

from apps.agents.models import AgentRun
from apps.ml_engine.models import DriftReport, ModelVersion
from apps.ml_engine.services.fairness_gate import (
    DEFAULT_DIR_THRESHOLD,
    check_fairness_gate,
)

logger = logging.getLogger(__name__)

# Pending review SLA: any escalated AgentRun waiting longer than this is
# flagged as "significant" with sla_breach=True.
PENDING_REVIEW_SLA_HOURS = 24


def drift_status(active_model: ModelVersion | None) -> dict:
    """Latest DriftReport.alert_level for the active model."""
    if active_model is None:
        return {"level": "unknown", "detail": "No active model"}

    report = (
        DriftReport.objects.filter(model_version=active_model)
        .order_by("-report_date")
        .first()
    )
    if report is None:
        return {"level": "unknown", "detail": "No drift reports yet"}

    level_map = {"none": "none", "moderate": "moderate", "significant": "significant"}
    psi_str = f"PSI {report.psi_score:.2f}" if report.psi_score is not None else "PSI n/a"
    return {
        "level": level_map.get(report.alert_level, "unknown"),
        "detail": f"{psi_str} (report {report.report_date.isoformat()})",
    }


def fairness_status(active_model: ModelVersion | None) -> dict:
    """Re-evaluate the fairness gate against the active model's stored
    fairness_metrics. Treats the EEOC four-fifths threshold as the gate.
    """
    if active_model is None:
        return {"level": "unknown", "detail": "No active model"}

    fairness_metrics = active_model.fairness_metrics or {}
    if not fairness_metrics:
        return {"level": "unknown", "detail": "No fairness metrics recorded"}

    gate = check_fairness_gate(fairness_metrics)
    if gate["passed"]:
        min_dir = gate["minimum_dir"]
        detail = f"Min DIR {min_dir:.2f}" if min_dir is not None else "Pass"
        return {"level": "none", "detail": detail}
    else:
        failing = ", ".join(gate["failing_attributes"])
        return {"level": "significant", "detail": f"Failing: {failing}"}


def pending_review_status() -> dict:
    """Count escalated AgentRuns and report the oldest age. SLA breach
    when any pending is older than PENDING_REVIEW_SLA_HOURS.
    """
    now = timezone.now()
    pending_qs = AgentRun.objects.filter(status="escalated").order_by("created_at")
    count = pending_qs.count()

    if count == 0:
        return {
            "level": "none",
            "detail": "No pending reviews",
            "count": 0,
            "oldest_age_hours": None,
            "sla_breach": False,
        }

    oldest = pending_qs.first()
    age = now - oldest.created_at
    age_hours = round(age.total_seconds() / 3600, 1)
    sla_breach = age_hours >= PENDING_REVIEW_SLA_HOURS

    if sla_breach:
        return {
            "level": "significant",
            "detail": f"{count} pending; oldest {age_hours}h (SLA breached)",
            "count": count,
            "oldest_age_hours": age_hours,
            "sla_breach": True,
        }
    return {
        "level": "moderate",
        "detail": f"{count} pending; oldest {age_hours}h",
        "count": count,
        "oldest_age_hours": age_hours,
        "sla_breach": False,
    }


def watchdog_status() -> dict:
    """Read the `watchdog:health` Redis hash written by the watchdog
    management command. TTL is 120s — missing key means the watchdog
    hasn't run recently.
    """
    try:
        r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=3)
        raw = r.hgetall("watchdog:health")
    except Exception as exc:
        logger.warning("watchdog_status_redis_unreachable: %s", exc)
        return {"level": "unknown", "detail": "Redis unreachable"}

    if not raw:
        return {"level": "unknown", "detail": "Watchdog state stale (key expired)"}

    def _decode(v):
        return v.decode() if isinstance(v, (bytes, bytearray)) else v

    decoded = {_decode(k): _decode(v) for k, v in raw.items()}
    status = decoded.get("status", "unknown")
    failures = decoded.get("consecutive_failures", "0")
    last_check = decoded.get("last_check")

    if status == "healthy":
        return {
            "level": "none",
            "detail": "Watchdog healthy",
            "last_check": last_check,
        }
    if status == "degraded":
        return {
            "level": "moderate",
            "detail": f"Degraded — {failures} consecutive failures",
            "last_check": last_check,
        }
    if status == "unreachable":
        return {
            "level": "significant",
            "detail": f"Backend unreachable — {failures} failures",
            "last_check": last_check,
        }
    return {"level": "unknown", "detail": f"Unknown status: {status}", "last_check": last_check}


def compute_status_strip() -> dict:
    """Assemble all four status indicators in one dict for the dashboard."""
    active_model = ModelVersion.objects.filter(is_active=True).first()
    return {
        "drift": drift_status(active_model),
        "fairness": fairness_status(active_model),
        "pending_review": pending_review_status(),
        "watchdog": watchdog_status(),
    }
```

- [ ] **Step 1.5: Run the tests to verify they pass**

Run:
```bash
docker compose exec backend pytest apps/loans/tests/test_dashboard_status.py -v
```

Expected: all 12 tests pass.

Also run the wider loans suite:
```bash
docker compose exec backend pytest apps/loans/tests/ -v
```

Expected: previously-green tests still green.

- [ ] **Step 1.6: Commit**

```bash
git add backend/apps/loans/services/__init__.py backend/apps/loans/services/dashboard_status.py backend/apps/loans/tests/test_dashboard_status.py
git commit -m "$(cat <<'EOF'
feat(dashboard): four pure status functions for operator strip

Adds backend/apps/loans/services/dashboard_status.py with four
pure functions and one assembler:

  - drift_status(active_model) — latest DriftReport.alert_level
  - fairness_status(active_model) — re-checks EEOC four-fifths rule
  - pending_review_status() — escalated AgentRun queue + SLA flag
  - watchdog_status() — reads watchdog:health Redis hash
  - compute_status_strip() — merges all four

Each function returns {level, detail} where level is one of
"none" | "moderate" | "significant" | "unknown" — matches the
traffic-light states the frontend StatusStrip will render in PR-2.

Pure functions — no caching. The 30s cache lives on the consuming
DashboardStatsView (next commit). 12 unit tests covering green,
amber, red, and unknown paths for each.

Backend half of PR-2 of docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire `status_strip` into `DashboardStatsView`

**Files:**
- Modify: `backend/apps/loans/views.py` (extend `_compute_stats()` return dict)
- Modify: `backend/apps/loans/tests/test_dashboard_stats.py` (PR-1's test file — add a new assertion that the response now contains `status_strip` with the right shape)

- [ ] **Step 2.1: Update the PR-1 test file with a new failing test (append, do not replace existing tests)**

Append this test class to `backend/apps/loans/tests/test_dashboard_stats.py` (after the existing `TestDashboardStatsExtensions` class added by PR-1):

```python
class TestDashboardStatsStatusStrip:
    """PR-2: the endpoint now also returns a status_strip with four sub-keys."""

    @pytest.mark.django_db
    @patch("apps.loans.views.ApiBudgetGuard")
    @patch("apps.loans.services.dashboard_status.redis.from_url")
    def test_response_includes_status_strip(
        self, mock_from_url, mock_budget_class, api_client, officer_user
    ):
        # Wire mocks consistent with the PR-1 tests
        mock_budget_class.return_value.get_daily_stats.return_value = {
            "calls": 0, "tokens": 0, "cost_usd": 0.0,
            "budget_limit_usd": 5.0, "call_limit": 500,
            "circuit_breaker_open": False,
        }
        from unittest.mock import MagicMock as _MM
        mock_r = _MM()
        mock_r.hgetall.return_value = {b"status": b"healthy"}
        mock_from_url.return_value = mock_r

        resp = api_client.get(reverse("dashboard-stats"))
        assert resp.status_code == 200
        data = resp.json()

        assert "status_strip" in data
        strip = data["status_strip"]
        assert set(strip.keys()) == {"drift", "fairness", "pending_review", "watchdog"}
        # Sanity-check shape of each indicator
        for key in ("drift", "fairness", "pending_review", "watchdog"):
            assert "level" in strip[key]
            assert "detail" in strip[key]
            assert strip[key]["level"] in {"none", "moderate", "significant", "unknown"}
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
docker compose exec backend pytest apps/loans/tests/test_dashboard_stats.py::TestDashboardStatsStatusStrip -v
```

Expected: FAIL with `KeyError: 'status_strip'` — the field is not yet returned by the view.

- [ ] **Step 2.3: Implement the view extension**

Edit `backend/apps/loans/views.py`. In the `_compute_stats` method, add this import at the top of the method body (alongside the existing `from apps.agents.models import AgentRun` line):

```python
from apps.loans.services.dashboard_status import compute_status_strip
```

Then in the `return` dict (the same one PR-1 modified), add ONE new top-level key — placement: directly after `"pipeline": {...},` (the last current key):

```python
            "status_strip": compute_status_strip(),
```

So the final tail of the return statement looks like:

```python
            "pipeline": {
                "total": pipeline_total,
                "completed": pipeline_completed,
                "failed": pipeline_failed,
                "escalated": pipeline_escalated,
                "success_rate": round(pipeline_completed / pipeline_total * 100, 1) if pipeline_total > 0 else 0,
            },
            "status_strip": compute_status_strip(),
        }
```

- [ ] **Step 2.4: Run test to verify it passes**

```bash
docker compose exec backend pytest apps/loans/tests/test_dashboard_stats.py -v
```

Expected: all PR-1 + new PR-2 tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add backend/apps/loans/views.py backend/apps/loans/tests/test_dashboard_stats.py
git commit -m "$(cat <<'EOF'
feat(dashboard): expose status_strip on /loans/dashboard-stats/

DashboardStatsView now calls compute_status_strip() and adds the
four indicators (drift, fairness, pending_review, watchdog) as a
top-level `status_strip` field on the response. The four functions
were added in the prior commit; the view just assembles them into
the existing endpoint so the dashboard keeps making a single fetch.

30s cache TTL preserved — a backend deploy needs up to 30s for the
new field to appear (clear with `manage.py shell -c "from
django.core.cache import cache; cache.delete('dashboard_stats')"`
if needed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: TypeScript — extend `DashboardStats` with `status_strip`

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 3.1: Add the new interface and field**

In `frontend/src/types/index.ts`, locate the `DashboardStats` interface added by PR-1 (look for `// Dashboard stats — response shape of GET /loans/dashboard-stats/.`).

Above the `DashboardStats` interface, insert:

```typescript
export type StatusLevel = 'none' | 'moderate' | 'significant' | 'unknown'

export interface StatusIndicator {
  level: StatusLevel
  detail: string
}

export interface PendingReviewStatus extends StatusIndicator {
  count: number
  oldest_age_hours: number | null
  sla_breach: boolean
}

export interface WatchdogStatus extends StatusIndicator {
  last_check?: string | null
}

export interface DashboardStatusStrip {
  drift: StatusIndicator
  fairness: StatusIndicator
  pending_review: PendingReviewStatus
  watchdog: WatchdogStatus
}
```

Then inside the `DashboardStats` interface, add ONE new field at the bottom (after `pipeline`):

```typescript
  status_strip: DashboardStatusStrip
```

- [ ] **Step 3.2: Verify type-check is clean**

```bash
docker compose exec frontend npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3.3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "$(cat <<'EOF'
feat(types): add DashboardStatusStrip + extend DashboardStats

Adds StatusLevel union, StatusIndicator base, PendingReviewStatus
(extends with count/oldest_age_hours/sla_breach), WatchdogStatus
(extends with last_check), and DashboardStatusStrip. Wires
status_strip onto the existing DashboardStats interface from PR-1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `StatusStrip` component + test

**Files:**
- Create: `frontend/src/components/dashboard/StatusStrip.tsx`
- Create: `frontend/src/__tests__/components/StatusStrip.test.tsx`

- [ ] **Step 4.1: Write the failing test (full file content)**

Create `frontend/src/__tests__/components/StatusStrip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { StatusStrip } from '@/components/dashboard/StatusStrip'
import type { DashboardStatusStrip } from '@/types'

const greenStrip: DashboardStatusStrip = {
  drift: { level: 'none', detail: 'PSI 0.05' },
  fairness: { level: 'none', detail: 'Min DIR 0.92' },
  pending_review: { level: 'none', detail: 'No pending reviews', count: 0, oldest_age_hours: null, sla_breach: false },
  watchdog: { level: 'none', detail: 'Watchdog healthy', last_check: '2026-05-25T12:00:00+00:00' },
}

const amberStrip: DashboardStatusStrip = {
  drift: { level: 'moderate', detail: 'PSI 0.18' },
  fairness: { level: 'none', detail: 'Min DIR 0.95' },
  pending_review: { level: 'moderate', detail: '3 pending; oldest 8.5h', count: 3, oldest_age_hours: 8.5, sla_breach: false },
  watchdog: { level: 'moderate', detail: 'Degraded — 1 consecutive failures', last_check: '2026-05-25T12:00:00+00:00' },
}

const redStrip: DashboardStatusStrip = {
  drift: { level: 'significant', detail: 'PSI 0.32' },
  fairness: { level: 'significant', detail: 'Failing: gender' },
  pending_review: { level: 'significant', detail: '5 pending; oldest 30h (SLA breached)', count: 5, oldest_age_hours: 30, sla_breach: true },
  watchdog: { level: 'significant', detail: 'Backend unreachable — 3 failures', last_check: '2026-05-25T12:00:00+00:00' },
}

describe('StatusStrip', () => {
  it('renders all four indicators with labels', () => {
    render(<StatusStrip strip={greenStrip} />)
    expect(screen.getByText('Drift')).toBeInTheDocument()
    expect(screen.getByText('Fairness')).toBeInTheDocument()
    expect(screen.getByText('Pending Review')).toBeInTheDocument()
    expect(screen.getByText('Watchdog')).toBeInTheDocument()
  })

  it('shows detail strings inline', () => {
    render(<StatusStrip strip={greenStrip} />)
    expect(screen.getByText('PSI 0.05')).toBeInTheDocument()
    expect(screen.getByText('Min DIR 0.92')).toBeInTheDocument()
    expect(screen.getByText('No pending reviews')).toBeInTheDocument()
    expect(screen.getByText('Watchdog healthy')).toBeInTheDocument()
  })

  it('uses green dots when all levels are none', () => {
    const { container } = render(<StatusStrip strip={greenStrip} />)
    const greenDots = container.querySelectorAll('[data-testid="status-dot-none"]')
    expect(greenDots.length).toBe(4)
  })

  it('uses amber dots for moderate levels', () => {
    const { container } = render(<StatusStrip strip={amberStrip} />)
    expect(container.querySelectorAll('[data-testid="status-dot-moderate"]').length).toBe(3)
    expect(container.querySelectorAll('[data-testid="status-dot-none"]').length).toBe(1)
  })

  it('uses red dots and shows SLA breach badge for significant levels', () => {
    const { container } = render(<StatusStrip strip={redStrip} />)
    expect(container.querySelectorAll('[data-testid="status-dot-significant"]').length).toBe(4)
    expect(screen.getByText(/SLA breached/i)).toBeInTheDocument()
  })

  it('renders an unknown indicator as a grey dot', () => {
    const partial = {
      ...greenStrip,
      drift: { level: 'unknown' as const, detail: 'No drift reports yet' },
    }
    const { container } = render(<StatusStrip strip={partial} />)
    expect(container.querySelector('[data-testid="status-dot-unknown"]')).toBeInTheDocument()
  })
})
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
cd frontend; npx vitest run src/__tests__/components/StatusStrip.test.tsx
```

(Container vitest is broken per PR-1; use host vitest. From PowerShell: `cd frontend; npx vitest run ...`.)

Expected: FAIL with `Cannot find module '@/components/dashboard/StatusStrip'`.

- [ ] **Step 4.3: Implement the component (full file content)**

Create `frontend/src/components/dashboard/StatusStrip.tsx`:

```tsx
'use client'

import {
  Activity,
  Shield,
  ShieldAlert,
  Users,
} from 'lucide-react'
import type { DashboardStatusStrip, StatusLevel } from '@/types'

type IndicatorConfig = {
  key: keyof DashboardStatusStrip
  label: string
  icon: typeof Activity
}

const INDICATORS: IndicatorConfig[] = [
  { key: 'drift', label: 'Drift', icon: Activity },
  { key: 'fairness', label: 'Fairness', icon: Shield },
  { key: 'pending_review', label: 'Pending Review', icon: Users },
  { key: 'watchdog', label: 'Watchdog', icon: ShieldAlert },
]

const DOT_CLASS: Record<StatusLevel, string> = {
  none: 'bg-emerald-500',
  moderate: 'bg-amber-500',
  significant: 'bg-rose-500',
  unknown: 'bg-slate-400',
}

const BORDER_CLASS: Record<StatusLevel, string> = {
  none: 'border-emerald-200/60',
  moderate: 'border-amber-200/60',
  significant: 'border-rose-200/60',
  unknown: 'border-slate-200/60',
}

interface StatusStripProps {
  strip: DashboardStatusStrip
}

export function StatusStrip({ strip }: StatusStripProps) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {INDICATORS.map(({ key, label, icon: Icon }) => {
        const indicator = strip[key]
        const level = indicator.level
        const slaBreach =
          key === 'pending_review' && strip.pending_review.sla_breach
        return (
          <div
            key={key}
            className={`flex items-center gap-3 rounded-lg border bg-white px-3 py-2.5 ${BORDER_CLASS[level]}`}
          >
            <span
              data-testid={`status-dot-${level}`}
              aria-label={`${label} status: ${level}`}
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT_CLASS[level]}`}
            />
            <Icon className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2">
                <p className="text-xs font-semibold text-slate-700">{label}</p>
                {slaBreach && (
                  <span className="text-[10px] font-bold uppercase tracking-wide text-rose-600">
                    SLA breached
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground truncate" title={indicator.detail}>
                {indicator.detail}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 4.4: Run test to verify it passes**

```bash
cd frontend; npx vitest run src/__tests__/components/StatusStrip.test.tsx
```

Expected: all 6 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add frontend/src/components/dashboard/StatusStrip.tsx frontend/src/__tests__/components/StatusStrip.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): StatusStrip — operator traffic-light component

Four-indicator horizontal strip (drift / fairness / pending review /
watchdog) with traffic-light dots (green=none, amber=moderate,
red=significant, slate=unknown) and inline detail text. Pending-
review tile additionally displays an "SLA breached" badge when
strip.pending_review.sla_breach is true.

6 test cases cover the green / amber / red / unknown matrix plus
all-four-labels-rendered and detail-string visibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `RecentApplications` row navigation

**Files:**
- Modify: `frontend/src/components/dashboard/RecentApplications.tsx`
- Modify (or Create) tests: see Step 5.1

- [ ] **Step 5.1: Check whether a test file exists for `RecentApplications`**

```bash
ls frontend/src/__tests__/components/RecentApplications.test.tsx
```

If it exists, modify it in Step 5.2; if not, create it in Step 5.2 (same target path either way).

- [ ] **Step 5.2: Write the failing test (full file content — works as both create or replace)**

Create or replace `frontend/src/__tests__/components/RecentApplications.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { RecentApplications } from '@/components/dashboard/RecentApplications'
import type { LoanApplication } from '@/types'

const mockApp = (id: string, firstName: string): LoanApplication => ({
  id,
  status: 'approved',
  loan_amount: 25000,
  created_at: '2026-05-25T00:00:00Z',
  updated_at: '2026-05-25T00:00:00Z',
  applicant: {
    id: 1,
    username: 'cust',
    email: 'cust@test.invalid',
    first_name: firstName,
    last_name: 'Test',
    role: 'customer',
  },
  decision: {
    decision: 'approved',
    confidence: 0.9,
    risk_score: 0.2,
    model_version: 'xgb-1',
    reasoning: 'ok',
    created_at: '2026-05-25T00:00:00Z',
  },
} as unknown as LoanApplication)

describe('RecentApplications', () => {
  it('renders applicant names', () => {
    render(<RecentApplications applications={[mockApp('a1', 'Alice'), mockApp('a2', 'Bob')]} />)
    expect(screen.getByText(/Alice/)).toBeInTheDocument()
    expect(screen.getByText(/Bob/)).toBeInTheDocument()
  })

  it('makes each row navigate to the application detail page', () => {
    render(<RecentApplications applications={[mockApp('a1', 'Alice')]} />)
    // The row should expose a link to /dashboard/applications/{id}
    const rowLink = screen.getByRole('link', { name: /open application a1/i })
    expect(rowLink).toHaveAttribute('href', '/dashboard/applications/a1')
  })

  it('still links applicant name to customer profile (existing behaviour)', () => {
    render(<RecentApplications applications={[mockApp('a1', 'Alice')]} />)
    const nameLink = screen.getByRole('link', { name: /Alice Test/ })
    expect(nameLink).toHaveAttribute('href', '/dashboard/customers/1')
  })

  it('shows empty state when no applications', () => {
    render(<RecentApplications applications={[]} />)
    expect(screen.getByText(/No applications yet/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 5.3: Run test to verify it fails**

```bash
cd frontend; npx vitest run src/__tests__/components/RecentApplications.test.tsx
```

Expected: FAIL on the "row navigate" test — there is no row-level link yet, only the name link.

- [ ] **Step 5.4: Implement row navigation (full file replacement)**

Replace `frontend/src/components/dashboard/RecentApplications.tsx` with:

```tsx
'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { LoanApplication } from '@/types'
import { formatCurrency, formatDate, getDisplayStatus } from '@/lib/utils'

interface RecentApplicationsProps {
  applications: LoanApplication[]
}

export function RecentApplications({ applications }: RecentApplicationsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent Applications</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Applicant</TableHead>
              <TableHead>Amount</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Date</TableHead>
              <TableHead className="sr-only">Open</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {applications.slice(0, 5).map((app) => {
              const s = getDisplayStatus(app.status, app.decision)
              return (
                <TableRow key={app.id} className="hover:bg-muted/50">
                  <TableCell>
                    <Link
                      href={`/dashboard/customers/${app.applicant.id}`}
                      className="font-medium text-blue-600 hover:underline"
                    >
                      {app.applicant.first_name} {app.applicant.last_name}
                    </Link>
                  </TableCell>
                  <TableCell>{formatCurrency(app.loan_amount)}</TableCell>
                  <TableCell>
                    <Badge className={s.color} variant="outline">{s.label}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{formatDate(app.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Link
                      href={`/dashboard/applications/${app.id}`}
                      aria-label={`Open application ${app.id}`}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Open →
                    </Link>
                  </TableCell>
                </TableRow>
              )
            })}
            {applications.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  No applications yet
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
```

Implementation note: per spec ("link each row directly to /dashboard/applications/[id]") and the test, the row gets a *visible* "Open" link in a new trailing cell rather than making the entire row clickable. This avoids the click-conflict with the inner applicant-name link that still navigates to the customer profile (preserves existing behaviour). The new cell has `sr-only` header text for screen readers.

- [ ] **Step 5.5: Run test to verify it passes**

```bash
cd frontend; npx vitest run src/__tests__/components/RecentApplications.test.tsx
```

Expected: all 4 tests pass.

- [ ] **Step 5.6: Commit**

```bash
git add frontend/src/components/dashboard/RecentApplications.tsx frontend/src/__tests__/components/RecentApplications.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): row-level navigation on RecentApplications

Each row now exposes an "Open →" link in a trailing cell that
navigates to /dashboard/applications/{id}. The existing
applicant-name link (to /dashboard/customers/{id}) is preserved, so
clicking the name still opens the customer profile.

Adds a screen-reader-only column header for the new cell. Test
coverage extended to four cases (existing two + row-link + customer
link preservation).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire the dashboard page; delete the donut

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx`
- Modify: `frontend/src/__tests__/pages/DashboardPage.test.tsx`
- Delete: `frontend/src/components/dashboard/ApprovalRateChart.tsx`
- Delete (if it exists): `frontend/src/__tests__/components/ApprovalRateChart.test.tsx`

- [ ] **Step 6.1: Update the page test (failing — partial edit, NOT full replacement)**

In `frontend/src/__tests__/pages/DashboardPage.test.tsx`, the `baseStats` constant added by PR-1 needs to gain a `status_strip` key. Locate `baseStats = {` (around the middle of the file) and add this field directly before the closing `}`:

```typescript
    status_strip: {
      drift: { level: 'none' as const, detail: 'PSI 0.05' },
      fairness: { level: 'none' as const, detail: 'Min DIR 0.92' },
      pending_review: { level: 'none' as const, detail: 'No pending reviews', count: 0, oldest_age_hours: null, sla_breach: false },
      watchdog: { level: 'none' as const, detail: 'Watchdog healthy', last_check: '2026-05-25T12:00:00+00:00' },
    },
```

Then, append this new test case at the bottom of the existing `describe('DashboardPage', () => { ... })` block (just before its closing brace):

```typescript
  it('renders the status strip with four indicators and no approval-rate donut', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () => HttpResponse.json(baseStats)),
      http.get(`${API_URL}/loans/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      )
    )
    renderPage()
    await waitFor(() => expect(screen.getByText('Drift')).toBeInTheDocument())
    expect(screen.getByText('Fairness')).toBeInTheDocument()
    expect(screen.getByText('Pending Review')).toBeInTheDocument()
    expect(screen.getByText('Watchdog')).toBeInTheDocument()
    // Donut removed — the chart's distinctive "approval rate" inner-text label
    // is no longer in the DOM.
    expect(screen.queryByText(/approval rate/i)).not.toBeInTheDocument()
  })
```

Wait — `Approval Rate` IS still rendered by `StatsCards` (the tile). Adjust the assertion to specifically check the donut's removed: the `<ApprovalRateChart>` component renders a `<text>` SVG node we'd target, but the simpler invariant is: the chart component file is gone. The test should instead assert that the chart's `data-testid` (which the deleted component had — see existing ApprovalRateChart for a `data-testid="approval-rate-chart"` attribute) is not present. Replace the final assertion line above with:

```typescript
    // Donut removed — its data-testid is not in the DOM.
    expect(screen.queryByTestId('approval-rate-chart')).not.toBeInTheDocument()
```

**Note for executor:** before writing this assertion, run `grep "data-testid" frontend/src/components/dashboard/ApprovalRateChart.tsx` to confirm the testid exists. If the chart does NOT have one, add `data-testid="approval-rate-chart"` to its root element in a tiny pre-deletion commit OR just drop this final assertion — its job is the safety net, not the primary check.

- [ ] **Step 6.2: Run page test to verify it fails**

```bash
cd frontend; npx vitest run src/__tests__/pages/DashboardPage.test.tsx
```

Expected: FAIL — `Drift` text not found because the page does not yet render `<StatusStrip>`.

- [ ] **Step 6.3: Implement the page change (full file replacement)**

Replace `frontend/src/app/dashboard/page.tsx` with:

```tsx
'use client'

import { useApplications } from '@/hooks/useApplications'
import { useDashboardStats } from '@/hooks/useDashboardStats'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { StatusStrip } from '@/components/dashboard/StatusStrip'
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
        <Skeleton className="h-80" />
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

      <StatusStrip strip={stats.status_strip} />

      <RecentApplications applications={applications} />
    </div>
  )
}
```

Changes from PR-1:
- `<StatusStrip strip={stats.status_strip} />` added between tiles and recent apps.
- `<ApprovalRateChart>` import removed.
- `<RecentApplications>` is no longer in a 2-column grid — it now spans full-width since the donut is gone. The wrapping `<div className="grid gap-6 md:grid-cols-2">` is also removed.
- Loading skeleton extended with 4 status-strip placeholders.

- [ ] **Step 6.4: Delete `ApprovalRateChart` and its test**

```bash
git rm frontend/src/components/dashboard/ApprovalRateChart.tsx
# Only run this if the test file actually exists — check first:
[ -f frontend/src/__tests__/components/ApprovalRateChart.test.tsx ] && \
  git rm frontend/src/__tests__/components/ApprovalRateChart.test.tsx
```

(On PowerShell, replace the bracket-test line with `if (Test-Path frontend/src/__tests__/components/ApprovalRateChart.test.tsx) { git rm frontend/src/__tests__/components/ApprovalRateChart.test.tsx }`.)

- [ ] **Step 6.5: Run the page test + wider suite**

```bash
cd frontend
npx vitest run src/__tests__/pages/DashboardPage.test.tsx
npx vitest run
```

Expected: page test passes (3 tests including the new one); wider suite is green. If any orphaned test still imports `ApprovalRateChart`, it will fail compile — that's the signal to delete that test too.

- [ ] **Step 6.6: Commit**

```bash
git add -A frontend/src/app/dashboard/page.tsx frontend/src/__tests__/pages/DashboardPage.test.tsx frontend/src/components/dashboard/
git commit -m "$(cat <<'EOF'
feat(dashboard): wire StatusStrip; delete approval-rate donut

Dashboard home now renders the operator status strip between the
StatsCards row and the RecentApplications table. The approval-rate
donut (ApprovalRateChart.tsx) is removed — it duplicated the
Approval Rate tile already shown in StatsCards. RecentApplications
spans full width now that the donut is gone.

Closes PR-2 of docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Smoke test

**Files:** none — manual + API verification.

- [ ] **Step 7.1: Live API smoke (sidesteps auth, sidesteps browser)**

```bash
docker compose exec -T backend python manage.py shell -c "
import json
from apps.loans.views import DashboardStatsView
from django.core.cache import cache
cache.delete('dashboard_stats')
data = DashboardStatsView()._compute_stats()
print(json.dumps(data.get('status_strip', '<MISSING>'), indent=2, default=str))
"
```

Expected: the JSON contains four sub-keys (drift, fairness, pending_review, watchdog), each with `level` ∈ {none, moderate, significant, unknown} and a non-empty `detail` string.

- [ ] **Step 7.2: Browser visual check at `localhost:3000/dashboard`**

Login (admin credentials — if `admin/admin1234` fails as it did during PR-1 smoke, create one via `manage.py createsuperuser` first), navigate to the dashboard, verify:
1. The four-tile row from PR-1 is still rendered (regression check).
2. A new horizontal four-indicator strip appears below the tiles, each with a coloured dot + label + detail.
3. The approval-rate donut is gone.
4. The `Recent Applications` table is full-width and each row has an "Open →" link that navigates to `/dashboard/applications/{id}` correctly.
5. No console errors.

If any check fails, identify which task's commit introduced the regression and fix that commit (or add a follow-up commit referencing it). Do not silently amend committed work.

---

## Open the PR

```bash
git push -u origin feat/dashboard-persona-refit-pr2-status-strip

gh pr create \
  --base feat/dashboard-persona-refit \
  --title "feat(dashboard): operator status strip + drop donut (PR-2 of refit)" \
  --body "$(cat <<'EOF'
## Summary

Implements **PR-2** of the dashboard persona refit
([spec](docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md),
[plan](docs/superpowers/plans/2026-05-25-dashboard-refit-pr2-status-strip.md)).

Stacks on **PR #191** (PR-1). Base intentionally targets
\`feat/dashboard-persona-refit\` — retarget to \`master\` before
merging PR #191 (per the stacked-PR convention).

Dashboard home now has:

1. The PR-1 tile row (unchanged).
2. A new **operator status strip** below the tiles with four traffic-light
   indicators — drift, fairness, pending human review (with SLA-breach
   badge when oldest pending > 24h), and watchdog. Sourced from
   \`DriftReport\` / active \`ModelVersion.fairness_metrics\` (via the
   pre-deployment fairness gate) / escalated \`AgentRun\` queue / the
   \`watchdog:health\` Redis hash.
3. The pre-existing recent-applications table, now **full-width** and with a
   trailing "Open →" link on each row that navigates to
   \`/dashboard/applications/{id}\`.

The **approval-rate donut is deleted** — it duplicated the Approval Rate
tile already shown in StatsCards.

Backend extends \`DashboardStatsView\` with one new top-level
\`status_strip\` field aggregating four sub-statuses. Each
sub-status is computed by a pure function in the new
\`apps/loans/services/dashboard_status.py\` module — trivially
testable, no caching of its own (the parent view's 30s cache
covers the assembled payload).

## Commits

| Layer | What |
|---|---|
| Backend services | Four pure status functions + 12 unit tests |
| Backend view | \`status_strip\` field added to \`/loans/dashboard-stats/\` |
| Types | \`DashboardStatusStrip\` interface added to \`@/types\` |
| Components | New \`<StatusStrip>\` component (6 tests) |
| Components | \`<RecentApplications>\` row navigation (4 tests) |
| Page | Dashboard wires \`<StatusStrip>\`, deletes donut, full-width recents |

## Test plan

- [x] \`apps/loans/tests/test_dashboard_status.py\` — 12/12 pass
- [x] \`apps/loans/tests/test_dashboard_stats.py\` (PR-1 + new PR-2 cases)
- [x] Frontend vitest full suite — green
- [x] Live API smoke: \`status_strip\` field present with all four indicators
- [ ] Visual smoke at \`localhost:3000/dashboard\` — reviewer to confirm strip renders + donut is gone

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

**Spec coverage check (PR-2 only):**
- ✅ Status strip with 4 indicators (drift, fairness, pending review with SLA, watchdog) — Tasks 1, 2, 4, 6
- ✅ Drift gate from `DriftReport` — Task 1 `drift_status()`
- ✅ Fairness gate from disparate-impact ratios — Task 1 `fairness_status()` calls existing `check_fairness_gate()`
- ✅ Pending human review with SLA breach if >24h — Task 1 `pending_review_status()`, `PENDING_REVIEW_SLA_HOURS = 24`
- ✅ Watchdog last-recovered count today — Task 1 `watchdog_status()` reads the Redis hash; "consecutive_failures" surfaces as the count
- ✅ Recent decisions row → `/dashboard/applications/{id}` — Task 5
- ✅ Approval-rate donut removed — Task 6 deletes the component file

**Placeholder scan:** no TBDs, no "implement later", every code block has full content.

**Type consistency:** `StatusLevel` values ("none"/"moderate"/"significant"/"unknown") match across Task 1 backend functions → Task 3 TS union → Task 4 component `DOT_CLASS` map keys → Task 4 test data. Field names `level`/`detail`/`count`/`oldest_age_hours`/`sla_breach`/`last_check` consistent across backend / types / component / page test.

**Out of scope (deferred to PR-3/PR-4):** counterfactual surfacing on customer status (PR-3); Model Metrics + Model Card consolidation (PR-4); CDR adapter, service decomposition, security gap-closure (separate foundation specs).
