"""C1 — decision emails can only be issued by staff, for the decision on record.

A customer must not be able to make the lender email them an approval letter
(rate, repayments, sign-by date) for a pending or denied application, and staff
must not be able to issue an email whose decision disagrees with LoanDecision.
"""

from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import LoanDecision


@pytest.fixture
def officer(db):
    return CustomUser.objects.create_user(
        username="c1_officer",
        email="c1_officer@test.com",
        password="testpass123",
        role="officer",
    )


def _decide(application, decision):
    return LoanDecision.objects.create(application=application, decision=decision, confidence=0.9)


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
@patch("apps.email_engine.tasks.generate_email_task.delay")
def test_customer_cannot_trigger_generation(mock_delay, sample_application):
    mock_delay.return_value = MagicMock(id="t-1")
    _decide(sample_application, "denied")
    resp = _client(sample_application.applicant).post(
        f"/api/v1/emails/generate/{sample_application.id}/", {"decision": "approved"}, format="json"
    )
    assert resp.status_code == 403
    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_customer_cannot_send_latest(monkeypatch, sample_application):
    _decide(sample_application, "approved")
    GeneratedEmail.objects.create(
        application=sample_application,
        decision="approved",
        subject="s",
        body="b",
        prompt_used="p",
        passed_guardrails=True,
    )
    send_mock = MagicMock(return_value={"sent": True})
    monkeypatch.setattr("apps.email_engine.services.sender.send_decision_email", send_mock)

    resp = _client(sample_application.applicant).post(f"/api/v1/emails/send/{sample_application.id}/")
    assert resp.status_code == 403
    assert send_mock.call_count == 0


@pytest.mark.django_db
@patch("apps.email_engine.tasks.generate_email_task.delay")
def test_staff_mismatched_decision_rejected(mock_delay, officer, sample_application):
    mock_delay.return_value = MagicMock(id="t-1")
    _decide(sample_application, "denied")
    resp = _client(officer).post(
        f"/api/v1/emails/generate/{sample_application.id}/", {"decision": "approved"}, format="json"
    )
    assert resp.status_code == 409
    mock_delay.assert_not_called()


@pytest.mark.django_db
@patch("apps.email_engine.tasks.generate_email_task.delay")
def test_staff_generation_without_decision_rejected(mock_delay, officer, sample_application):
    mock_delay.return_value = MagicMock(id="t-1")
    resp = _client(officer).post(f"/api/v1/emails/generate/{sample_application.id}/", {}, format="json")
    assert resp.status_code == 409
    mock_delay.assert_not_called()


@pytest.mark.django_db
@patch("apps.email_engine.tasks.generate_email_task.delay")
def test_staff_generation_uses_decision_on_record(mock_delay, officer, sample_application):
    """No body decision (the dashboard sends none) -> the LoanDecision is used."""
    mock_delay.return_value = MagicMock(id="t-1")
    _decide(sample_application, "denied")
    resp = _client(officer).post(f"/api/v1/emails/generate/{sample_application.id}/", {}, format="json")
    assert resp.status_code == 202
    mock_delay.assert_called_once_with(str(sample_application.id), "denied")


@pytest.mark.django_db
def test_staff_send_latest_refuses_email_for_other_decision(monkeypatch, officer, sample_application):
    """A stale approval email must not go out once the decision on record is denied."""
    _decide(sample_application, "denied")
    GeneratedEmail.objects.create(
        application=sample_application,
        decision="approved",
        subject="s",
        body="b",
        prompt_used="p",
        passed_guardrails=True,
    )
    send_mock = MagicMock(return_value={"sent": True})
    monkeypatch.setattr("apps.email_engine.services.sender.send_decision_email", send_mock)

    resp = _client(officer).post(f"/api/v1/emails/send/{sample_application.id}/")
    assert resp.status_code == 409
    assert send_mock.call_count == 0


@pytest.mark.django_db
def test_task_refuses_decision_that_disagrees_with_record(monkeypatch, sample_application):
    """Defence in depth: any caller of the task gets refused on a mismatch."""
    from apps.email_engine import tasks as email_tasks
    from apps.email_engine.services.decision_email import DecisionMismatch

    _decide(sample_application, "denied")

    def _must_not_generate(self, *a, **kw):
        raise AssertionError("generate() must not run for a mismatched decision")

    monkeypatch.setattr("apps.email_engine.services.email_generator.EmailGenerator.generate", _must_not_generate)

    with pytest.raises(DecisionMismatch):
        email_tasks.generate_email_task(str(sample_application.id), "approved")
    assert not GeneratedEmail.objects.filter(application=sample_application).exists()


@pytest.mark.django_db
def test_task_refuses_when_no_decision_on_record(monkeypatch, sample_application):
    from apps.email_engine import tasks as email_tasks
    from apps.email_engine.services.decision_email import DecisionMismatch

    with pytest.raises(DecisionMismatch):
        email_tasks.generate_email_task(str(sample_application.id), "approved")
