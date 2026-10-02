"""I4 — deleting a loan application soft-deletes it.

SoftDeleteModel did not override delete() and nothing called soft_delete(),
so DELETE /api/v1/loans/<id>/ physically removed the application and, by
CASCADE, its LoanDecision, fraud checks, decision reviews, agent runs, bias
reports and emails: the evidence a 7-year retention policy keeps.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import AuditLog, LoanApplication, LoanDecision

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def decided(sample_application):
    decision = LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.2)
    AgentRun.objects.create(application=sample_application, status=AgentRun.Status.COMPLETED, steps=[])
    GeneratedEmail.objects.create(
        application=sample_application,
        decision="denied",
        subject="s",
        body="b",
        prompt_used="p",
        passed_guardrails=True,
    )
    return sample_application, decision


@LOCMEM
@pytest.mark.django_db
def test_api_delete_soft_deletes_and_keeps_the_decision_evidence(decided, admin_user):
    app, decision = decided
    resp = _client(admin_user).delete(f"/api/v1/loans/{app.pk}/")
    assert resp.status_code == 204

    row = LoanApplication.all_objects.all_with_deleted().get(pk=app.pk)
    assert row.deleted_at is not None
    assert LoanDecision.objects.filter(pk=decision.pk).exists()
    assert AgentRun.objects.filter(application_id=app.pk).exists()
    assert GeneratedEmail.objects.filter(application_id=app.pk).exists()

    audit = AuditLog.objects.get(action="loan_deleted", resource_id=str(app.pk))
    assert audit.details["decision_id"] == str(decision.pk)
    assert audit.details["decision"] == "denied"
    assert audit.details["status"] == app.status
    assert audit.details["soft_delete"] is True


@LOCMEM
@pytest.mark.django_db
def test_soft_deleted_application_disappears_from_the_api(decided, admin_user):
    app, _ = decided
    client = _client(admin_user)
    client.delete(f"/api/v1/loans/{app.pk}/")
    assert client.get(f"/api/v1/loans/{app.pk}/").status_code == 404
    assert client.get("/api/v1/loans/").data["count"] == 0
    # Related records are hidden through the application, not orphaned in lists.
    assert client.get(f"/api/v1/emails/{app.pk}/").status_code == 404
    assert client.get("/api/v1/emails/").data["count"] == 0
    assert client.get("/api/v1/agents/runs/").data["count"] == 0


@pytest.mark.django_db
def test_model_and_queryset_delete_are_soft_and_hard_delete_is_explicit(sample_application):
    sample_application.delete()
    assert LoanApplication.all_objects.all_with_deleted().filter(pk=sample_application.pk).exists()
    assert not LoanApplication.objects.filter(pk=sample_application.pk).exists()

    sample_application.restore()
    LoanApplication.objects.filter(pk=sample_application.pk).delete()
    assert LoanApplication.all_objects.dead().filter(pk=sample_application.pk).exists()

    LoanApplication.all_objects.all_with_deleted().filter(pk=sample_application.pk).hard_delete()
    assert not LoanApplication.all_objects.all_with_deleted().filter(pk=sample_application.pk).exists()
