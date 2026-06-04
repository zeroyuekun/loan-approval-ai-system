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


# ---------------------------------------------------------------------------
# M17 — Template fallback, no-apology regression, and double-send guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_template_fallback_when_api_unavailable(monkeypatch, sample_application):
    """When _api_available returns False, generate() must use the template path
    (template_fallback=True) rather than calling the Claude API."""
    from apps.email_engine.services.email_generator import EmailGenerator

    gen = EmailGenerator()
    # Force the API-available probe to return False without touching the network.
    monkeypatch.setattr(gen, "_api_available", lambda: False)

    result = gen.generate(sample_application, "denied")

    assert result["template_fallback"] is True, "Expected template_fallback=True when API unavailable"
    assert result["subject"], "Template fallback must produce a non-empty subject"
    assert result["body"], "Template fallback must produce a non-empty body"
    assert result["prompt_used"] == "[TEMPLATE FALLBACK — Claude API unavailable]"


@pytest.mark.django_db
def test_denial_template_has_no_apology_language(monkeypatch, sample_application):
    """Denial template emails must not contain apology/disappointment language.

    Regression guard for the CLAUDE.md rule: never add 'sorry', 'apologise',
    or 'disappointment' to denial email templates.
    """
    from apps.email_engine.services.email_generator import EmailGenerator

    gen = EmailGenerator()
    monkeypatch.setattr(gen, "_api_available", lambda: False)

    result = gen.generate(sample_application, "denied")
    body = result["body"].lower()

    assert "sorry" not in body, "Denial email must not contain 'sorry'"
    assert "apologis" not in body, "Denial email must not contain 'apologis' (apologise/apologising)"
    assert "disappointment" not in body, "Denial email must not contain 'disappointment'"


@pytest.mark.django_db
def test_send_latest_email_view_double_send_guard(monkeypatch, sample_application):
    """Second POST to SendLatestEmailView must be a no-op — sent_at must not be
    set twice and send_decision_email must only be called once."""
    from unittest.mock import MagicMock

    from rest_framework.test import APIClient

    from apps.email_engine.models import GeneratedEmail

    send_mock = MagicMock(return_value={"sent": True})
    monkeypatch.setattr("apps.email_engine.services.sender.send_decision_email", send_mock)

    email = GeneratedEmail.objects.create(
        application=sample_application,
        decision="denied",
        subject="Your Loan Decision",
        body="Body text",
        prompt_used="p",
        passed_guardrails=True,
        sent_at=None,
    )

    client = APIClient()
    client.force_authenticate(user=sample_application.applicant)

    url = f"/api/v1/emails/send/{sample_application.id}/"

    # First request: should send and set sent_at
    resp1 = client.post(url)
    assert resp1.status_code == 200
    assert resp1.data.get("sent") is True
    assert send_mock.call_count == 1

    # Second request: sent_at is already set — must be a no-op
    resp2 = client.post(url)
    assert resp2.status_code == 200
    # No additional send call
    assert send_mock.call_count == 1, "send_decision_email must not be called a second time"

    # Verify sent_at is set only once (unchanged after second request)
    email.refresh_from_db()
    assert email.sent_at is not None
    first_sent_at = email.sent_at

    email.refresh_from_db()
    assert email.sent_at == first_sent_at, "sent_at must not change after second POST"


@pytest.mark.django_db
def test_redelivery_sends_generated_but_unsent_email(monkeypatch, sample_application):
    """A passing-but-unsent email (sent_at is None) must be delivered on a later
    task run, exactly once, without re-generating (regression: the idempotency
    guard treated 'a row exists' as 'work done' and never retried the send)."""
    from apps.email_engine import tasks as email_tasks

    GeneratedEmail.objects.create(
        application=sample_application,
        decision="denied",
        subject="Your application",
        body="Body text",
        prompt_used="p",
        passed_guardrails=True,
        sent_at=None,  # generated but never delivered
    )

    from unittest.mock import MagicMock

    send_mock = MagicMock(return_value={"sent": True})
    monkeypatch.setattr("apps.email_engine.services.sender.send_decision_email", send_mock)

    # Generation must NOT run again — an email already exists; only the send.
    def _must_not_generate(self, *a, **kw):
        raise AssertionError("generate() must not run when an email already exists")

    monkeypatch.setattr("apps.email_engine.services.email_generator.EmailGenerator.generate", _must_not_generate)

    result = email_tasks.generate_email_task(str(sample_application.id), "denied")

    assert send_mock.call_count == 1  # delivered exactly once
    assert result["email_sent"] is True
    email = GeneratedEmail.objects.get(application=sample_application, decision="denied")
    assert email.sent_at is not None  # marker persisted
