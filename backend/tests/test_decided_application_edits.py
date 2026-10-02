"""I5 — staff cannot rewrite the inputs of an assessed application, and every
staff edit is audited field by field.

An officer could PATCH loan_amount on an approved application from 20k to
500k: the decision was not re-run, the ADM explanation was then computed
against the edited values, and the audit row recorded only the status.
"""

from decimal import Decimal

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.loans.models import AuditLog, LoanApplication, LoanDecision

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _staff(officer_user):
    client = APIClient()
    client.force_authenticate(user=officer_user)
    return client


@pytest.fixture
def approved(sample_application):
    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.9)
    LoanApplication.objects.filter(pk=sample_application.pk).update(status="approved")
    sample_application.refresh_from_db()
    return sample_application


@LOCMEM
@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [("loan_amount", "500000.00"), ("annual_income", "999999.00"), ("credit_score", 300), ("has_bankruptcy", True)],
)
def test_scoring_inputs_of_an_assessed_application_are_frozen(approved, officer_user, field, value):
    before = getattr(approved, field)
    resp = _staff(officer_user).patch(f"/api/v1/loans/{approved.pk}/", {field: value}, format="json")
    assert resp.status_code == 400, resp.data
    assert field in resp.data
    approved.refresh_from_db()
    assert getattr(approved, field) == before
    assert not AuditLog.objects.filter(action="loan_updated", resource_id=str(approved.pk)).exists()


@LOCMEM
@pytest.mark.django_db
def test_workflow_fields_stay_editable_after_the_decision_and_are_audited(approved, officer_user):
    resp = _staff(officer_user).patch(
        f"/api/v1/loans/{approved.pk}/", {"notes": "Called the customer", "conditions_met": True}, format="json"
    )
    assert resp.status_code == 200, resp.data
    entry = AuditLog.objects.get(action="loan_updated", resource_id=str(approved.pk))
    assert entry.details["changed_fields"] == ["conditions_met", "notes"]
    assert entry.details["conditions_met"] == {"from": False, "to": True}
    assert "notes" not in entry.details  # free text recorded by name only


@LOCMEM
@pytest.mark.django_db
def test_inputs_of_a_pending_application_are_editable_with_before_and_after_audited(sample_application, officer_user):
    resp = _staff(officer_user).patch(
        f"/api/v1/loans/{sample_application.pk}/", {"loan_amount": "30000.00"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    sample_application.refresh_from_db()
    assert sample_application.loan_amount == Decimal("30000.00")
    entry = AuditLog.objects.get(action="loan_updated", resource_id=str(sample_application.pk))
    assert entry.details["changed_fields"] == ["loan_amount"]
    assert entry.details["loan_amount"]["to"] == "30000.00"
