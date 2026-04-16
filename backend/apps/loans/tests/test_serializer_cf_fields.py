import pytest
from django.contrib.auth import get_user_model

from apps.loans.models import LoanApplication, LoanDecision
from apps.loans.serializers import CustomerLoanDecisionSerializer

User = get_user_model()


@pytest.fixture
def denied_decision(db):
    user = User.objects.create_user(username="cftest", password="test1234", role="customer")
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=50000,
        credit_score=500,
        loan_amount=100000,
        loan_term_months=36,
        debt_to_income=6.0,
        employment_length=2,
        purpose="home",
        home_ownership="rent",
        status="denied",
    )
    return LoanDecision.objects.create(
        application=app,
        decision="denied",
        confidence=0.3,
        shap_values={"credit_score": -0.4, "debt_to_income": -0.3},
        counterfactual_results=[
            {"changes": {"loan_amount": 50000.0}, "statement": "Reduce loan to $50,000"},
            {"changes": {"loan_term_months": 60}, "statement": "Extend term to 60 months"},
        ],
    )


@pytest.fixture
def approved_decision(db):
    user = User.objects.create_user(username="cftest2", password="test1234", role="customer")
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=150000,
        credit_score=900,
        loan_amount=50000,
        loan_term_months=36,
        debt_to_income=2.0,
        employment_length=10,
        purpose="home",
        home_ownership="own",
        status="approved",
    )
    return LoanDecision.objects.create(
        application=app,
        decision="approved",
        confidence=0.9,
        shap_values={},
        counterfactual_results=[],
    )


@pytest.mark.django_db
class TestCustomerLoanDecisionSerializerCF:
    def test_counterfactuals_present_for_denied(self, denied_decision):
        data = CustomerLoanDecisionSerializer(denied_decision).data
        assert "counterfactuals" in data
        assert len(data["counterfactuals"]) == 2
        assert data["counterfactuals"][0]["statement"] == "Reduce loan to $50,000"

    def test_counterfactuals_empty_for_approved(self, approved_decision):
        data = CustomerLoanDecisionSerializer(approved_decision).data
        assert "counterfactuals" in data
        assert data["counterfactuals"] == []

    def test_reapplication_guidance_uses_counterfactuals(self, denied_decision):
        data = CustomerLoanDecisionSerializer(denied_decision).data
        assert data["reapplication_guidance"] is not None
        assert "improvement_targets" in data["reapplication_guidance"]
