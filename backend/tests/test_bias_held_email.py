"""A draft the bias review held back is released only by the human-review paths.

The orchestrator persists the decision email, runs the bias check and, on an
escalation, withholds it (passed_guardrails=True, sent_at=None). The staff
"generate email" and "send latest" endpoints used to treat that row as a
generated-but-undelivered email and send it, bypassing the review. They now
refuse with 409 while the application is under review and for any unsent draft
with a flagged bias report.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.agents.models import AgentRun, BiasReport
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import LoanApplication, LoanDecision

SENDER = "apps.email_engine.services.sender.send_decision_email"
LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _draft(application, decision="approved"):
    return GeneratedEmail.objects.create(
        application=application,
        decision=decision,
        subject="Your loan decision",
        body="Dear Customer, body.",
        prompt_used="p",
        passed_guardrails=True,
    )


def _flag(run, email, score=75):
    return BiasReport.objects.create(
        agent_run=run,
        email=email,
        bias_score=score,
        categories=["age"],
        analysis="flagged",
        flagged=True,
        requires_human_review=True,
    )


@pytest.fixture
def held_after_review(sample_application):
    """Application decided (off review), whose only stored draft was bias-held."""
    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.9)
    LoanApplication.objects.filter(pk=sample_application.pk).update(status="approved")
    run = AgentRun.objects.create(application=sample_application, status=AgentRun.Status.COMPLETED, steps=[])
    email = _draft(sample_application)
    _flag(run, email)
    return sample_application


@pytest.fixture
def under_review(sample_application):
    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.9)
    LoanApplication.objects.filter(pk=sample_application.pk).update(status="review")
    AgentRun.objects.create(application=sample_application, status=AgentRun.Status.ESCALATED, steps=[])
    return sample_application


def _staff(officer_user):
    client = APIClient()
    client.force_authenticate(user=officer_user)
    return client


@LOCMEM
@pytest.mark.django_db
def test_generate_refuses_while_application_is_under_review(under_review, officer_user):
    # A real id: on the unfixed path the view serialises task.id, and a
    # MagicMock reaching the JSON renderer exhausts memory instead of failing.
    with patch("apps.email_engine.views.generate_email_task.delay", return_value=MagicMock(id="t-1")) as delay:
        resp = _staff(officer_user).post(f"/api/v1/emails/generate/{under_review.pk}/", {}, format="json")
    assert resp.status_code == 409, resp.data
    delay.assert_not_called()


@LOCMEM
@pytest.mark.django_db
def test_generate_refuses_a_bias_held_draft(held_after_review, officer_user):
    # A real id: on the unfixed path the view serialises task.id, and a
    # MagicMock reaching the JSON renderer exhausts memory instead of failing.
    with patch("apps.email_engine.views.generate_email_task.delay", return_value=MagicMock(id="t-1")) as delay:
        resp = _staff(officer_user).post(f"/api/v1/emails/generate/{held_after_review.pk}/", {}, format="json")
    assert resp.status_code == 409, resp.data
    delay.assert_not_called()


@LOCMEM
@pytest.mark.django_db
def test_send_latest_refuses_a_bias_held_draft(held_after_review, officer_user):
    send = MagicMock(return_value={"sent": True})
    with patch(SENDER, send):
        resp = _staff(officer_user).post(f"/api/v1/emails/send/{held_after_review.pk}/", {}, format="json")
    assert resp.status_code == 409, resp.data
    send.assert_not_called()
    assert GeneratedEmail.objects.get(application=held_after_review).sent_at is None


@LOCMEM
@pytest.mark.django_db
def test_send_latest_refuses_while_application_is_under_review(under_review, officer_user):
    _draft(under_review)
    send = MagicMock(return_value={"sent": True})
    with patch(SENDER, send):
        resp = _staff(officer_user).post(f"/api/v1/emails/send/{under_review.pk}/", {}, format="json")
    assert resp.status_code == 409, resp.data
    send.assert_not_called()


@pytest.mark.django_db
def test_task_does_not_redeliver_a_bias_held_draft(held_after_review):
    from apps.email_engine.services.decision_email import HeldForBiasReview
    from apps.email_engine.tasks import generate_email_task

    send = MagicMock(return_value={"sent": True})
    with patch(SENDER, send):
        result = generate_email_task.apply(args=(str(held_after_review.pk), "approved"))
    assert isinstance(result.result, HeldForBiasReview)
    send.assert_not_called()


@LOCMEM
@pytest.mark.django_db
def test_send_latest_still_delivers_an_unflagged_unsent_draft(sample_application, officer_user):
    """Control: a plain undelivered draft (SMTP failure) is still sendable."""
    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.9)
    LoanApplication.objects.filter(pk=sample_application.pk).update(status="approved")
    _draft(sample_application)
    send = MagicMock(return_value={"sent": True})
    with patch(SENDER, send):
        resp = _staff(officer_user).post(f"/api/v1/emails/send/{sample_application.pk}/", {}, format="json")
    assert resp.status_code == 200, resp.data
    assert send.call_count == 1
