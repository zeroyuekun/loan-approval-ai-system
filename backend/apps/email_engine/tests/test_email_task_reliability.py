"""M6 + L25 — email task reliability.

Covers the sent_at idempotency marker (Task 2) and the Celery-native retry +
soft_time_limit + idempotent send behaviour (Task 3).
"""

import pytest

from apps.email_engine.models import GeneratedEmail


@pytest.mark.django_db
def test_generated_email_has_sent_at_marker(sample_application):
    email = GeneratedEmail.objects.create(
        application=sample_application,
        decision="denied",
        subject="s",
        body="b",
        prompt_used="p",
    )
    assert email.sent_at is None  # defaults to not-yet-sent


def test_email_task_has_soft_time_limit():
    from apps.email_engine.tasks import generate_email_task

    assert generate_email_task.soft_time_limit == 100
    assert generate_email_task.time_limit == 120


def test_generate_does_not_sleep_on_rate_limit(monkeypatch):
    """EmailGenerator.generate must surface RateLimited, never block on time.sleep."""
    import anthropic

    from apps.email_engine.services import email_generator as eg
    from apps.email_engine.services.email_generator import EmailGenerator
    from apps.email_engine.services.exceptions import RateLimited

    sleep_calls = []
    monkeypatch.setattr(eg.time, "sleep", lambda s: sleep_calls.append(s))

    # Build a fake rate-limit error without hitting the network.
    def _raise_rate_limit(*args, **kwargs):
        raise anthropic.RateLimitError(
            message="rate limited",
            response=httpx_response_stub(),
            body=None,
        )

    # guarded_api_call is imported locally inside generate() from the api_budget
    # module, so patch it at its definition site.
    monkeypatch.setattr("apps.agents.services.api_budget.guarded_api_call", _raise_rate_limit)

    gen = EmailGenerator()
    gen.client = object()  # non-None so _api_available is bypassed below
    monkeypatch.setattr(gen, "_api_available", lambda: True)

    class _FakeApplicant:
        first_name = "Test"
        last_name = "User"
        username = "testuser"
        email = "test@example.com"

    class _FakeApp:
        applicant = _FakeApplicant()
        loan_amount = 25000
        decision = None

        def get_purpose_display(self):
            return "Personal"

        def get_employment_type_display(self):
            return "PAYG permanent"

        def get_applicant_type_display(self):
            return "Single"

        has_cosigner = False

    with pytest.raises(RateLimited):
        gen.generate(_FakeApp(), "denied")

    assert sleep_calls == [], "generate must not block the worker with time.sleep"


def httpx_response_stub():
    """Minimal httpx.Response so anthropic.RateLimitError can be constructed."""
    import httpx

    return httpx.Response(status_code=429, request=httpx.Request("POST", "https://api.anthropic.com"))


@pytest.mark.django_db
def test_task_converts_rate_limited_to_retry(monkeypatch, sample_application):
    from celery.exceptions import Retry

    from apps.email_engine import tasks as email_tasks
    from apps.email_engine.services.exceptions import RateLimited

    def _raise_rate_limited(self, application, decision, *a, **kw):
        raise RateLimited(retry_after=45)

    monkeypatch.setattr(
        "apps.email_engine.services.email_generator.EmailGenerator.generate",
        _raise_rate_limited,
    )

    from unittest.mock import MagicMock

    retry_mock = MagicMock(side_effect=Retry)
    monkeypatch.setattr(email_tasks.generate_email_task, "retry", retry_mock)

    with pytest.raises(Retry):
        email_tasks.generate_email_task(str(sample_application.id), "denied")

    assert retry_mock.called
    _, kwargs = retry_mock.call_args
    assert "countdown" in kwargs
    assert kwargs["countdown"] == 45


@pytest.mark.django_db
def test_send_is_idempotent_on_redelivery(monkeypatch, sample_application):
    """Already-sent email (sent_at set) must NOT be re-sent on redelivery.

    The task short-circuits on the persisted GeneratedEmail and reports the true
    sent state from the sent_at marker (email_sent True because it WAS sent), and
    crucially does NOT call send_decision_email a second time.
    """
    from django.utils import timezone

    from apps.email_engine import tasks as email_tasks

    # Pre-existing email with sent_at set — simulates the prior delivery.
    GeneratedEmail.objects.create(
        application=sample_application,
        decision="denied",
        subject="s",
        body="b",
        prompt_used="p",
        passed_guardrails=True,
        sent_at=timezone.now(),
    )

    from unittest.mock import MagicMock

    send_mock = MagicMock(return_value={"sent": True})
    monkeypatch.setattr("apps.email_engine.services.sender.send_decision_email", send_mock)

    result = email_tasks.generate_email_task(str(sample_application.id), "denied")

    assert send_mock.call_count == 0  # never re-sent
    assert result["email_sent"] is True  # true sent state from sent_at marker


@pytest.mark.django_db
def test_send_occurs_once_when_not_yet_sent(monkeypatch, sample_application):
    """First delivery: sent_at is None → send IS called once and sent_at persists."""
    from apps.email_engine import tasks as email_tasks

    # Generator returns a passing result without touching the network.
    def _fake_generate(self, application, decision, *a, **kw):
        return {
            "subject": "Your application",
            "body": "Body text",
            "prompt_used": "p",
            "guardrail_results": [],
            "passed_guardrails": True,
            "quality_score": 100,
            "generation_time_ms": 10,
            "attempt_number": 1,
            "template_fallback": False,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    monkeypatch.setattr(
        "apps.email_engine.services.email_generator.EmailGenerator.generate",
        _fake_generate,
    )

    from unittest.mock import MagicMock

    send_mock = MagicMock(return_value={"sent": True})
    monkeypatch.setattr("apps.email_engine.services.sender.send_decision_email", send_mock)

    result = email_tasks.generate_email_task(str(sample_application.id), "denied")

    assert send_mock.call_count == 1
    assert result["email_sent"] is True
    email = GeneratedEmail.objects.get(pk=result["email_id"])
    assert email.sent_at is not None
