"""Tests for DashboardStatsView — covers the PR-1 extension fields
(p50/p95 decision latency, 24h decision count, LLM spend, raw
approved/denied counts).
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache as django_cache
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


@pytest.fixture(autouse=True)
def _clear_dashboard_cache():
    """DashboardStatsView caches the payload for 30s under ``dashboard_stats``;
    that cache is shared across tests in the same process and would let one
    test leak its warm response into the next. Clear before and after every
    test in this module."""
    django_cache.delete("dashboard_stats")
    yield
    django_cache.delete("dashboard_stats")


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
