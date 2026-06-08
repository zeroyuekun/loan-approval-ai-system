"""Cross-customer permission regression tests for the loan-detail endpoint.

Verifies that:
  1. Customer A cannot retrieve customer B's loan application via the
     standard GET /api/v1/loans/{id}/ retrieve action. The queryset
     isolation at LoanApplicationViewSet.get_queryset() filters by
     applicant=request.user, so cross-customer requests return 404
     (not 403 — the resource is invisible, not forbidden).
  2. Customer A CAN retrieve their own denied application, and the
     response includes the counterfactuals serialized by
     CustomerLoanDecisionSerializer.

Closes the Change 3 acceptance criterion from the dashboard persona
refit spec (docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md).
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.loans.models import LoanApplication, LoanDecision

User = get_user_model()


@pytest.fixture
def customer_a(db):
    return User.objects.create_user(
        username="customer_a",
        password="test1234",
        email="a@aussieloanai.test",
        role="customer",
    )


@pytest.fixture
def customer_b(db):
    return User.objects.create_user(
        username="customer_b",
        password="test1234",
        email="b@aussieloanai.test",
        role="customer",
    )


@pytest.fixture
def denied_app_for_a(customer_a):
    """A denied LoanApplication owned by customer_a, with attached LoanDecision
    carrying counterfactual_results. Mirrors the shape PR-1's counterfactual
    pipeline emits.
    """
    app = LoanApplication.objects.create(
        applicant=customer_a,
        annual_income=Decimal("50000"),
        credit_score=520,
        loan_amount=Decimal("100000"),
        loan_term_months=36,
        debt_to_income=Decimal("6.0"),
        employment_length=2,
        purpose="home",
        home_ownership="rent",
        status="denied",
    )
    LoanDecision.objects.create(
        application=app,
        decision="denied",
        confidence=0.3,
        shap_values={"credit_score": -0.4, "debt_to_income": -0.3},
        counterfactual_results=[
            {"changes": {"loan_amount": 50000.0}, "statement": "Reduce loan to $50,000"},
            {"changes": {"loan_term_months": 60}, "statement": "Extend term to 60 months"},
        ],
    )
    return app


@pytest.mark.django_db
class TestCustomerLoanDetailPermissions:
    """End-to-end auth tests against the live LoanApplicationViewSet retrieve action."""

    def test_customer_b_cannot_retrieve_customer_a_loan(self, customer_b, denied_app_for_a):
        client = APIClient()
        client.force_authenticate(user=customer_b)
        # Customer A's app id, requested by customer B
        response = client.get(f"/api/v1/loans/{denied_app_for_a.id}/")
        # Queryset filter makes the resource invisible, so the API returns 404
        # not 403. This is the standard Django REST pattern for object-level
        # isolation and matches what get_queryset() implements at views.py:64.
        assert response.status_code == 404

    def test_customer_b_cannot_see_a_counterfactuals_via_list(self, customer_b, denied_app_for_a):
        """Even on the list endpoint, customer B's queryset is filtered
        to their own applications — none of customer A's data leaks
        into the paginated results.
        """
        client = APIClient()
        client.force_authenticate(user=customer_b)
        response = client.get("/api/v1/loans/")
        assert response.status_code == 200
        body = response.json()
        # Customer B has no applications of their own and cannot see A's
        results = body.get("results", body) if isinstance(body, dict) else body
        assert results == []  # or count == 0 on paginated payloads
        if isinstance(body, dict) and "count" in body:
            assert body["count"] == 0

    def test_customer_a_can_retrieve_own_denied_app_with_counterfactuals(self, customer_a, denied_app_for_a):
        client = APIClient()
        client.force_authenticate(user=customer_a)
        response = client.get(f"/api/v1/loans/{denied_app_for_a.id}/")
        assert response.status_code == 200
        body = response.json()
        # CustomerLoanApplicationSerializer chains to
        # CustomerLoanDecisionSerializer for the decision field
        decision = body.get("decision")
        assert decision is not None
        assert decision["decision"] == "denied"
        # The counterfactuals serializer-method-field surfaces the JSON.
        # Spec acceptance: denied customer sees actionable counterfactuals.
        assert "counterfactuals" in decision
        assert len(decision["counterfactuals"]) == 2
        statements = [cf["statement"] for cf in decision["counterfactuals"]]
        assert "Reduce loan to $50,000" in statements
        assert "Extend term to 60 months" in statements

    def test_unauthenticated_request_is_rejected(self, denied_app_for_a):
        """Sanity-check: no auth → 401/403 (DRF default), never 200."""
        client = APIClient()
        response = client.get(f"/api/v1/loans/{denied_app_for_a.id}/")
        assert response.status_code in (401, 403)
