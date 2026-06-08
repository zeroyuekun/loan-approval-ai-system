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
def active_model(db, tmp_path, settings):
    # ModelVersion.clean() requires file_path to live under
    # settings.ML_MODELS_DIR and end in .joblib. Sandbox the dir to
    # tmp_path so the fixture is hermetic.
    settings.ML_MODELS_DIR = str(tmp_path)
    return ModelVersion.objects.create(
        algorithm="xgb",
        version="test-1",
        file_path=str(tmp_path / "test.joblib"),
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
        # Implementation phrasing: "No drift reports yet".
        assert "no drift reports" in result["detail"].lower()

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
        # Both 0.92 and 0.85 are >= 0.80 (EEOC four-fifths).
        # NB: the plan's draft test asserted level == "pass" / "fail" but the
        # StatusLevel union (and the rest of the plan — drift, watchdog,
        # frontend dot-class map) is "none" | "moderate" | "significant" |
        # "unknown". Aligned to the union — "pass" maps to "none", "fail"
        # maps to "significant" — so the four backend functions all return
        # the same value set the frontend expects.
        result = fairness_status(active_model)
        assert result["level"] == "none"
        assert "0.85" in result["detail"]  # min DIR exposed

    @pytest.mark.django_db
    def test_fails_with_dir_below_threshold(self, active_model):
        active_model.fairness_metrics = {
            "gender": {"disparate_impact_ratio": 0.60},
        }
        active_model.save()
        result = fairness_status(active_model)
        assert result["level"] == "significant"
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
        AgentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=30))
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
