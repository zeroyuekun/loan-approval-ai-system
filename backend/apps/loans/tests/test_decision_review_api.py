import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.loans.models import DecisionReview, LoanApplication, LoanDecision

pytestmark = pytest.mark.django_db


def _denied_app(django_user_model):
    cust = django_user_model.objects.create_user(username="c", password="x", role="customer", email="c@x.com")
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
    return cust, app


def test_customer_can_file_review_on_own_denied_app(django_user_model):
    cust, app = _denied_app(django_user_model)
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post(
        "/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "disagree"}, format="json"
    )
    assert r.status_code == 201
    assert DecisionReview.objects.filter(application=app, requested_by=cust).count() == 1


def test_cannot_file_on_non_denied(django_user_model):
    cust, app = _denied_app(django_user_model)
    app.status = "approved"
    app.save(update_fields=["status"])
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "x"}, format="json")
    assert r.status_code == 400


def test_duplicate_open_review_blocked(django_user_model):
    cust, app = _denied_app(django_user_model)
    client = APIClient()
    client.force_authenticate(cust)
    client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "a"}, format="json")
    r = client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "b"}, format="json")
    assert r.status_code == 400


def test_officer_resolve_overturn(django_user_model, monkeypatch):
    import apps.loans.services.decision_review as svc

    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
    cust, app = _denied_app(django_user_model)
    officer = django_user_model.objects.create_user(username="o", password="x", role="officer")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    client = APIClient()
    client.force_authenticate(officer)
    r = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned", "note": "approve"},
        format="json",
    )
    assert r.status_code == 200
    app.refresh_from_db()
    assert app.status == "approved"


def test_customer_cannot_resolve(django_user_model):
    cust, app = _denied_app(django_user_model)
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/", {"outcome": "upheld", "note": "n"}, format="json"
    )
    assert r.status_code == 403


@override_settings(DECISION_REVIEW_ENABLED=False)
def test_filing_disabled_when_flag_off(django_user_model):
    cust, app = _denied_app(django_user_model)
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "x"}, format="json")
    assert r.status_code == 503
