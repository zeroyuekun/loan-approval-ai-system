import pytest

from apps.loans.models import LoanApplication, LoanDecision
from apps.loans.serializers import CustomerLoanDecisionSerializer

pytestmark = pytest.mark.django_db


def _denied_decision(django_user_model):
    user = django_user_model.objects.create_user(username="cust1", password="x", role="customer")
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=50000,
        credit_score=500,
        loan_amount=30000,
        debt_to_income=5,
        employment_length=1,
        purpose="personal",
        home_ownership="rent",
        status="denied",
    )
    return LoanDecision.objects.create(
        application=app,
        decision="denied",
        confidence=0.9,
        shap_values={"credit_score": -0.5},
        feature_importances={"credit_score": 0.5},
        counterfactual_results=[{"changes": {"loan_amount": 10000}, "statement": "Reduce your loan amount"}],
    )


def test_serializer_exposes_adm_disclosure(django_user_model):
    data = CustomerLoanDecisionSerializer(_denied_decision(django_user_model)).data
    assert data["adm_disclosure"]["mode"] == "solely_automated"
    assert data["adm_disclosure"]["human_review_right"] is True
    # parity: existing keys still present
    assert data["denial_reasons"][0]["code"] == "R06"
    assert data["reapplication_guidance"] is not None
