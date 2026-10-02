"""I3 — complaint status is staff-managed, staff edits are audited, no deletes.

Customers could POST a complaint already "resolved" (or "escalated_afca") with
their own resolution text, so it never entered the IDR queue or SLA tracking.
Officers could edit a complainant's description or hard-delete the complaint
with no AuditLog trace.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.loans.models import AuditLog, Complaint

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def complaint(customer_user, sample_application):
    return Complaint.objects.create(
        complainant=customer_user,
        loan_application=sample_application,
        category="decision",
        subject="Decision query",
        description="I think the decision is wrong.",
    )


@LOCMEM
@pytest.mark.django_db
def test_customer_cannot_file_a_complaint_already_resolved(customer_user, sample_application):
    resp = _client(customer_user).post(
        "/api/v1/loans/complaints/",
        {
            "loan_application": str(sample_application.pk),
            "category": "decision",
            "subject": "s",
            "description": "d",
            "status": "resolved",
            "resolution": "Sorted it myself",
            "resolved_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    created = Complaint.objects.get(pk=resp.data["id"])
    assert created.status == Complaint.Status.OPEN
    assert created.resolution == ""
    assert created.resolved_at is None


@LOCMEM
@pytest.mark.django_db
def test_staff_complaint_edit_is_audited_with_the_changed_fields(complaint, officer_user):
    resp = _client(officer_user).patch(
        f"/api/v1/loans/complaints/{complaint.pk}/",
        {"status": "investigating", "description": "rewritten by staff"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    entry = AuditLog.objects.get(action="complaint_updated", resource_id=str(complaint.pk))
    assert entry.user == officer_user
    assert sorted(entry.details["changed_fields"]) == ["description", "status"]
    assert entry.details["status"] == {"from": "open", "to": "investigating"}


@LOCMEM
@pytest.mark.django_db
def test_complaints_cannot_be_deleted(complaint, officer_user, admin_user):
    for user in (officer_user, admin_user):
        resp = _client(user).delete(f"/api/v1/loans/complaints/{complaint.pk}/")
        assert resp.status_code == 405, resp.status_code
    assert Complaint.objects.filter(pk=complaint.pk).exists()
