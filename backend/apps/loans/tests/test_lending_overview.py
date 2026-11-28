"""Tests for the business-facing lending metrics on the dashboard."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.loans.models import LoanApplication, LoanDecision
from apps.loans.services.lending_overview import decision_handling, top_decline_reasons

User = get_user_model()


@pytest.fixture
def applicant(db):
    return User.objects.create_user(username="overview_customer", password="x", role="customer")


def _decide(applicant, decision, *, shap=None, waterfall=None, involvement="none"):
    app = LoanApplication.objects.create(
        applicant=applicant,
        annual_income=Decimal("85000"),
        credit_score=700,
        loan_amount=Decimal("25000"),
        loan_term_months=36,
        debt_to_income=Decimal("0.30"),
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
        status=decision,
    )
    return LoanDecision.objects.create(
        application=app,
        decision=decision,
        confidence=0.8,
        shap_values=shap or {},
        decision_waterfall=waterfall or [],
        human_involvement=involvement,
    )


def test_counts_each_reason_once_per_decline_and_ranks_by_frequency(applicant):
    _decide(applicant, "denied", shap={"credit_score": -0.4, "debt_to_income": -0.2})
    _decide(applicant, "denied", shap={"credit_score": -0.3, "annual_income": 0.1})
    _decide(applicant, "approved", shap={"credit_score": -0.5})  # approvals never count

    result = top_decline_reasons()

    assert result["total_declines"] == 2
    top = result["reasons"][0]
    assert top["code"] == "R06"
    assert top["count"] == 2
    assert top["share"] == 100.0
    assert [r["code"] for r in result["reasons"]] == ["R06", "R03"]


def test_policy_rule_decline_is_counted_as_the_rule_not_the_model_drivers(applicant):
    _decide(
        applicant,
        "denied",
        shap={"credit_score": -0.4},
        waterfall=[{"stage": "policy_rules", "reason_code": "POLICY_DECLINE_P03"}],
    )

    reasons = top_decline_reasons()["reasons"]

    assert [r["code"] for r in reasons] == ["POLICY_DECLINE_P03"]
    assert reasons[0]["reason"] == "Undischarged bankruptcy or within 7yr window"


def test_no_declines_returns_empty_list(db):
    assert top_decline_reasons() == {"total_declines": 0, "window_days": 90, "reasons": []}


def test_decision_handling_splits_automated_reviewed_and_overridden(applicant):
    _decide(applicant, "approved")
    _decide(applicant, "denied", involvement="assisted")
    _decide(applicant, "approved", involvement="overridden")

    assert decision_handling() == {"total": 3, "automated": 1, "reviewed": 1, "overridden": 1}
