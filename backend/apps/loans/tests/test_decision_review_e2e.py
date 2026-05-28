import pytest
from rest_framework.test import APIClient

from apps.loans.models import AuditLog, DecisionReview, LoanApplication, LoanDecision

pytestmark = pytest.mark.django_db


def _denied(django_user_model):
    cust = django_user_model.objects.create_user(username="cust", password="x", role="customer", email="cust@x.com")
    officer = django_user_model.objects.create_user(username="off", password="x", role="officer")
    app = LoanApplication.objects.create(
        applicant=cust,
        annual_income=50000,
        credit_score=500,
        loan_amount=30000,
        debt_to_income=5,
        employment_length=1,
        purpose="personal",
        home_ownership="rent",
        status="denied",
    )
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    return cust, officer, app


def test_full_flow_file_then_overturn(django_user_model, monkeypatch):
    import apps.loans.services.decision_review as svc

    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
    cust, officer, app = _denied(django_user_model)

    # 1. Customer files a review
    cclient = APIClient()
    cclient.force_authenticate(cust)
    r = cclient.post(
        "/api/v1/loans/decision-reviews/",
        {"application": str(app.id), "reason": "My income was understated"},
        format="json",
    )
    assert r.status_code == 201
    review_id = r.json()["id"]
    assert AuditLog.objects.filter(action="decision_review_requested", resource_id=review_id).exists()

    # 2. Officer overturns it
    oclient = APIClient()
    oclient.force_authenticate(officer)
    r2 = oclient.post(
        f"/api/v1/loans/decision-reviews/{review_id}/resolve/",
        {"outcome": "overturned", "note": "Verified income — approving"},
        format="json",
    )
    assert r2.status_code == 200

    # 3. Application is now approved + decision flipped + audit trail complete
    app.refresh_from_db()
    assert app.status == "approved"
    assert app.decision.decision == "approved"
    assert DecisionReview.objects.get(id=review_id).status == DecisionReview.Status.OVERTURNED
    assert AuditLog.objects.filter(action="decision_review_resolved", resource_id=review_id).exists()


def test_full_flow_file_then_uphold_keeps_denied(django_user_model):
    cust, officer, app = _denied(django_user_model)
    cclient = APIClient()
    cclient.force_authenticate(cust)
    review_id = cclient.post(
        "/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "please re-check"}, format="json"
    ).json()["id"]
    oclient = APIClient()
    oclient.force_authenticate(officer)
    r = oclient.post(
        f"/api/v1/loans/decision-reviews/{review_id}/resolve/",
        {"outcome": "upheld", "note": "Decision confirmed"},
        format="json",
    )
    assert r.status_code == 200
    app.refresh_from_db()
    assert app.status == "denied"
    assert DecisionReview.objects.get(id=review_id).status == DecisionReview.Status.UPHELD
