"""Integration test: denied applicant gets counterfactual explanations end-to-end."""

import pytest
from django.contrib.auth import get_user_model

from apps.loans.models import LoanApplication, LoanDecision
from apps.loans.serializers import CustomerLoanDecisionSerializer

User = get_user_model()


@pytest.mark.django_db
def test_golden_denied_applicant_gets_counterfactuals():
    """Seed a deliberately-denied applicant and verify CF fields are serialized."""
    user = User.objects.create_user(username="golden_denied", password="test1234", role="customer")
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=30000,
        credit_score=400,
        loan_amount=200000,
        loan_term_months=36,
        debt_to_income=8.0,
        employment_length=1,
        purpose="home",
        home_ownership="rent",
        has_cosigner=False,
        status="denied",
    )
    decision = LoanDecision.objects.create(
        application=app,
        decision="denied",
        confidence=0.15,
        shap_values={"credit_score": -0.5, "debt_to_income": -0.35, "loan_amount": -0.2},
        counterfactual_results=[
            {"changes": {"loan_amount": 50000.0}, "statement": "Reduce your loan amount from $200,000 to $50,000"},
            {"changes": {"loan_term_months": 60}, "statement": "Extend your loan term from 36 to 60 months"},
            {"changes": {"has_cosigner": 1}, "statement": "Add a co-signer to your application"},
        ],
    )

    serializer = CustomerLoanDecisionSerializer(decision)
    data = serializer.data

    assert data["decision"] == "denied"
    assert len(data["counterfactuals"]) == 3
    assert data["counterfactuals"][0]["statement"].startswith("Reduce your loan")
    assert data["denial_reasons"] is not None
    assert len(data["denial_reasons"]) > 0
    assert data["reapplication_guidance"] is not None
    assert data["reapplication_guidance"]["improvement_targets"] is not None
