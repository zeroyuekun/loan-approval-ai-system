"""Known issue: decision-review resolve did len(note) on the raw JSON value, so
a null (or non-string) note raised TypeError and returned 500."""

import pytest
from rest_framework.test import APIClient

from apps.loans.models import DecisionReview, LoanApplication, LoanDecision


@pytest.fixture
def review(sample_application, customer_user):
    LoanApplication.objects.filter(pk=sample_application.pk).update(status="denied")
    LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.2)
    return DecisionReview.objects.create(application=sample_application, requested_by=customer_user, reason="r")


def _resolve(officer_user, review, payload):
    client = APIClient()
    client.force_authenticate(user=officer_user)
    return client.post(f"/api/v1/loans/decision-reviews/{review.pk}/resolve/", payload, format="json")


@pytest.mark.django_db
def test_null_note_is_treated_as_empty(officer_user, review):
    resp = _resolve(officer_user, review, {"outcome": "upheld", "note": None})
    assert resp.status_code == 200, resp.data


@pytest.mark.django_db
def test_non_string_note_is_a_400(officer_user, review):
    resp = _resolve(officer_user, review, {"outcome": "upheld", "note": 12345})
    assert resp.status_code == 400, resp.data


@pytest.mark.django_db
def test_non_uuid_application_filter_is_a_400_not_a_500(officer_user):
    """M6: a UUIDField filter on "abc" raised Django's ValidationError (500)."""
    client = APIClient()
    client.force_authenticate(user=officer_user)
    resp = client.get("/api/v1/loans/decision-reviews/?application=abc")
    assert resp.status_code == 400, resp.status_code
