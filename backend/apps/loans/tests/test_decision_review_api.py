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


def test_cannot_file_on_another_customers_app(django_user_model):
    cust_b, app_b = _denied_app(django_user_model)
    cust_a = django_user_model.objects.create_user(username="other", password="x", role="customer", email="o@x.com")
    client = APIClient()
    client.force_authenticate(cust_a)
    r = client.post(
        "/api/v1/loans/decision-reviews/",
        {"application": str(app_b.id), "reason": "not mine"},
        format="json",
    )
    assert r.status_code == 400


def test_reason_too_long_rejected(django_user_model):
    cust, app = _denied_app(django_user_model)
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post(
        "/api/v1/loans/decision-reviews/",
        {"application": str(app.id), "reason": "x" * 5000},
        format="json",
    )
    assert r.status_code == 400


def test_list_filtered_by_application(django_user_model):
    cust, app = _denied_app(django_user_model)
    # A second denied app + review for the same customer.
    app2 = LoanApplication.objects.create(
        applicant=cust,
        annual_income=60000,
        credit_score=480,
        loan_amount=20000,
        debt_to_income=4,
        employment_length=2,
        purpose="personal",
        home_ownership="rent",
        status="denied",
    )
    LoanDecision.objects.create(application=app2, decision="denied", confidence=0.8)
    r1 = DecisionReview.objects.create(application=app, requested_by=cust, reason="a")
    DecisionReview.objects.create(application=app2, requested_by=cust, reason="b")
    client = APIClient()
    client.force_authenticate(cust)
    resp = client.get(f"/api/v1/loans/decision-reviews/?application={app.id}")
    assert resp.status_code == 200
    results = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
    ids = {row["id"] for row in results}
    assert ids == {str(r1.id)}


def test_resolve_response_body_shows_resolved_status(django_user_model, monkeypatch):
    import apps.loans.services.decision_review as svc

    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
    cust, app = _denied_app(django_user_model)
    officer = django_user_model.objects.create_user(username="obody", password="x", role="officer")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    client = APIClient()
    client.force_authenticate(officer)
    r = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned", "note": "approve now"},
        format="json",
    )
    assert r.status_code == 200
    assert r.data["status"] == "overturned"
    assert r.data["outcome_decision"] == "approved"
    assert r.data["resolution_note"] == "approve now"


def test_resolve_uphold_response_body_shows_upheld(django_user_model):
    cust, app = _denied_app(django_user_model)
    officer = django_user_model.objects.create_user(username="oup", password="x", role="officer")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    client = APIClient()
    client.force_authenticate(officer)
    r = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "upheld", "note": "stands"},
        format="json",
    )
    assert r.status_code == 200
    assert r.data["status"] == "upheld"


def test_resolve_overturn_on_non_denied_returns_409(django_user_model, monkeypatch):
    import apps.loans.services.decision_review as svc

    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
    cust, app = _denied_app(django_user_model)
    officer = django_user_model.objects.create_user(username="o409", password="x", role="officer")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    # Move the app off 'denied' after the review exists.
    app.transition_to("processing", details={"source": "test"})
    client = APIClient()
    client.force_authenticate(officer)
    r = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned", "note": "late"},
        format="json",
    )
    assert r.status_code == 409


def test_owner_can_withdraw_via_api(django_user_model):
    cust, app = _denied_app(django_user_model)
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="oops")
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post(f"/api/v1/loans/decision-reviews/{review.id}/withdraw/", {}, format="json")
    assert r.status_code == 200
    assert r.data["status"] == "withdrawn"


def test_non_owner_cannot_withdraw(django_user_model):
    cust, app = _denied_app(django_user_model)
    other = django_user_model.objects.create_user(username="x2", password="x", role="customer", email="x2@x.com")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="oops")
    client = APIClient()
    client.force_authenticate(other)
    r = client.post(f"/api/v1/loans/decision-reviews/{review.id}/withdraw/", {}, format="json")
    # get_object() queryset scopes to requested_by for customers -> 404 (not found in their qs)
    assert r.status_code == 404


def test_resolve_note_too_long_rejected(django_user_model):
    cust, app = _denied_app(django_user_model)
    officer = django_user_model.objects.create_user(username="off2", password="x", role="officer")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="please review")
    client = APIClient()
    client.force_authenticate(officer)
    r = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "upheld", "note": "y" * 5000},
        format="json",
    )
    assert r.status_code == 400
