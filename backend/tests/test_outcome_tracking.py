"""Tests for the outcome tracking service (SR 11-7 outcomes analysis).

Covers:
- Empty dataset (no outcomes) returns zeros gracefully
- Confusion matrix computation with known data
- Accuracy calculation
- Calibration gap (predicted default rate - actual default rate)
- Vintage analysis grouping by origination month
- Binary outcome mapping (arrears_90 and default -> bad; performing/prepaid -> good)
"""
import pytest
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.services.outcome_tracker import (
    compute_outcome_analysis,
    compute_vintage_analysis,
    _is_bad_outcome,
)

User = get_user_model()


def _make_user(username):
    return User.objects.create_user(username=username, password="testpass123")


def _make_app(user, *, actual_outcome=None, outcome_date=None, **overrides):
    """Create a LoanApplication with sensible defaults."""
    defaults = dict(
        applicant=user,
        annual_income=Decimal("80000"),
        credit_score=700,
        loan_amount=Decimal("20000"),
        loan_term_months=36,
        debt_to_income=Decimal("3.0"),
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
        actual_outcome=actual_outcome,
        outcome_date=outcome_date,
    )
    defaults.update(overrides)
    return LoanApplication.objects.create(**defaults)


def _make_decision(application, *, decision="approved", confidence=0.85, risk_grade="A"):
    """Create a LoanDecision for the given application."""
    return LoanDecision.objects.create(
        application=application,
        decision=decision,
        confidence=confidence,
        risk_grade=risk_grade,
        model_version="test-v1",
    )


# ---------------------------------------------------------------------------
# Binary outcome mapping
# ---------------------------------------------------------------------------
class TestBinaryOutcomeMapping:
    def test_default_is_bad(self):
        assert _is_bad_outcome("default") is True

    def test_arrears_90_is_bad(self):
        assert _is_bad_outcome("arrears_90") is True

    def test_performing_is_good(self):
        assert _is_bad_outcome("performing") is False

    def test_prepaid_is_good(self):
        assert _is_bad_outcome("prepaid") is False

    def test_arrears_30_is_good(self):
        assert _is_bad_outcome("arrears_30") is False

    def test_arrears_60_is_good(self):
        assert _is_bad_outcome("arrears_60") is False


# ---------------------------------------------------------------------------
# Outcome analysis
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestComputeOutcomeAnalysis:
    def test_no_outcomes_returns_zeros(self):
        """With no applications at all, return zero/empty results."""
        result = compute_outcome_analysis()

        assert result["total_with_outcomes"] == 0
        assert result["accuracy"] == 0.0
        assert result["confusion_matrix"] == {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        assert result["accuracy_by_risk_grade"] == {}
        assert result["actual_default_rate"] == 0.0
        assert result["predicted_default_rate"] == 0.0
        assert result["calibration_gap"] == 0.0
        assert result["outcome_breakdown"] == {}

    def test_no_outcomes_with_apps_but_no_outcome_field(self):
        """Applications exist but none have actual_outcome set."""
        user = _make_user("no_outcome_user")
        app = _make_app(user)
        _make_decision(app)

        result = compute_outcome_analysis()
        assert result["total_with_outcomes"] == 0

    def test_confusion_matrix_all_true_positives(self):
        """All denied applications actually defaulted -> all TP."""
        user = _make_user("tp_user")
        for i in range(3):
            app = _make_app(user, actual_outcome="default")
            _make_decision(app, decision="denied", risk_grade="CCC")

        result = compute_outcome_analysis()
        assert result["total_with_outcomes"] == 3
        assert result["confusion_matrix"] == {"tp": 3, "fp": 0, "tn": 0, "fn": 0}
        assert result["accuracy"] == 1.0

    def test_confusion_matrix_all_true_negatives(self):
        """All approved applications are performing -> all TN."""
        user = _make_user("tn_user")
        for i in range(4):
            app = _make_app(user, actual_outcome="performing")
            _make_decision(app, decision="approved", risk_grade="AAA")

        result = compute_outcome_analysis()
        assert result["total_with_outcomes"] == 4
        assert result["confusion_matrix"] == {"tp": 0, "fp": 0, "tn": 4, "fn": 0}
        assert result["accuracy"] == 1.0

    def test_confusion_matrix_mixed(self):
        """Mix of outcomes to verify all four quadrants."""
        user = _make_user("mixed_user")

        # TP: denied + default
        app1 = _make_app(user, actual_outcome="default")
        _make_decision(app1, decision="denied", risk_grade="CCC")

        # TN: approved + performing
        app2 = _make_app(user, actual_outcome="performing")
        _make_decision(app2, decision="approved", risk_grade="AAA")

        # FP: denied + performing (denied but they would have been fine)
        app3 = _make_app(user, actual_outcome="performing")
        _make_decision(app3, decision="denied", risk_grade="BB")

        # FN: approved + default (approved but they defaulted)
        app4 = _make_app(user, actual_outcome="default")
        _make_decision(app4, decision="approved", risk_grade="A")

        result = compute_outcome_analysis()
        cm = result["confusion_matrix"]
        assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
        assert result["total_with_outcomes"] == 4
        assert result["accuracy"] == 0.5  # 2 correct out of 4

    def test_arrears_90_treated_as_bad(self):
        """arrears_90 should be classified as bad outcome (like default)."""
        user = _make_user("arrears90_user")

        # TP: denied + arrears_90
        app = _make_app(user, actual_outcome="arrears_90")
        _make_decision(app, decision="denied", risk_grade="B")

        result = compute_outcome_analysis()
        assert result["confusion_matrix"]["tp"] == 1
        assert result["actual_default_rate"] == 1.0

    def test_calibration_gap(self):
        """Calibration gap = predicted default rate - actual default rate."""
        user = _make_user("calibration_user")

        # 2 denied (predicted bad), 2 approved (predicted good)
        # 1 actual bad, 3 actual good
        # predicted_default_rate = 2/4 = 0.5
        # actual_default_rate = 1/4 = 0.25
        # calibration_gap = 0.25

        app1 = _make_app(user, actual_outcome="default")
        _make_decision(app1, decision="denied", risk_grade="CCC")  # TP

        app2 = _make_app(user, actual_outcome="performing")
        _make_decision(app2, decision="denied", risk_grade="BB")  # FP

        app3 = _make_app(user, actual_outcome="performing")
        _make_decision(app3, decision="approved", risk_grade="AAA")  # TN

        app4 = _make_app(user, actual_outcome="performing")
        _make_decision(app4, decision="approved", risk_grade="AA")  # TN

        result = compute_outcome_analysis()
        assert result["predicted_default_rate"] == 0.5
        assert result["actual_default_rate"] == 0.25
        assert result["calibration_gap"] == 0.25

    def test_accuracy_by_risk_grade(self):
        """Each risk grade should have its own accuracy."""
        user = _make_user("grade_user")

        # AAA: 2 correct (TN)
        for _ in range(2):
            app = _make_app(user, actual_outcome="performing")
            _make_decision(app, decision="approved", risk_grade="AAA")

        # CCC: 1 correct (TP), 1 wrong (FP)
        app_tp = _make_app(user, actual_outcome="default")
        _make_decision(app_tp, decision="denied", risk_grade="CCC")

        app_fp = _make_app(user, actual_outcome="performing")
        _make_decision(app_fp, decision="denied", risk_grade="CCC")

        result = compute_outcome_analysis()
        assert result["accuracy_by_risk_grade"]["AAA"] == 1.0
        assert result["accuracy_by_risk_grade"]["CCC"] == 0.5

    def test_outcome_breakdown(self):
        """outcome_breakdown should count each outcome type."""
        user = _make_user("breakdown_user")

        for outcome in ["performing", "performing", "default", "prepaid"]:
            app = _make_app(user, actual_outcome=outcome)
            _make_decision(app, decision="approved")

        result = compute_outcome_analysis()
        assert result["outcome_breakdown"]["performing"] == 2
        assert result["outcome_breakdown"]["default"] == 1
        assert result["outcome_breakdown"]["prepaid"] == 1


# ---------------------------------------------------------------------------
# Vintage analysis
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestComputeVintageAnalysis:
    def test_empty_returns_empty_list(self):
        result = compute_vintage_analysis()
        assert result == []

    def test_groups_by_month(self):
        """Applications should be grouped by their origination month."""
        user = _make_user("vintage_user")

        # Two apps in same month, one default, one performing
        app1 = _make_app(user, actual_outcome="performing")
        _make_decision(app1, decision="approved")

        app2 = _make_app(user, actual_outcome="default")
        _make_decision(app2, decision="approved")

        result = compute_vintage_analysis()
        assert len(result) == 1  # all created at the same time -> same month
        row = result[0]
        assert row["originated"] == 2
        assert row["defaulted"] == 1
        assert row["default_rate"] == 0.5

    def test_only_approved_included(self):
        """Vintage analysis only considers approved applications."""
        user = _make_user("vintage_approved_user")

        # Approved with outcome
        app1 = _make_app(user, actual_outcome="performing")
        _make_decision(app1, decision="approved")

        # Denied with outcome -- should be excluded from vintage
        app2 = _make_app(user, actual_outcome="default")
        _make_decision(app2, decision="denied")

        result = compute_vintage_analysis()
        assert len(result) == 1
        assert result[0]["originated"] == 1
        assert result[0]["defaulted"] == 0

    def test_arrears_90_counted_as_default(self):
        """arrears_90 should be counted as defaulted in vintage analysis."""
        user = _make_user("vintage_arrears_user")

        app = _make_app(user, actual_outcome="arrears_90")
        _make_decision(app, decision="approved")

        result = compute_vintage_analysis()
        assert result[0]["defaulted"] == 1
        assert result[0]["default_rate"] == 1.0

    def test_no_outcomes_excluded(self):
        """Applications without actual_outcome should not appear."""
        user = _make_user("vintage_no_outcome_user")

        app = _make_app(user)  # no actual_outcome
        _make_decision(app, decision="approved")

        result = compute_vintage_analysis()
        assert result == []
