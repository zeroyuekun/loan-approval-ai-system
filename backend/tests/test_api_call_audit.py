"""I6 — the APP 8 cross-border log must answer "whose data went offshore".

Every APICallLog row previously had service="unknown" and null application /
run FKs (no call site passed them), rows were written only for successful
calls, and pii_categories came from keyword-matching the whole prompt, so the
bias prompt's own instruction text ("income", "credit score") produced
categories for data that was never sent.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.agents.models import AgentRun, APICallLog
from apps.agents.services.api_budget import api_call_context, current_api_call_context, guarded_api_call

GUARD = "apps.agents.services.api_budget.ApiBudgetGuard"


def _client(provider="anthropic", raises=None):
    client = MagicMock()
    client.provider = provider
    if raises is not None:
        client.messages.create.side_effect = raises
    else:
        client.messages.create.return_value = SimpleNamespace(usage=SimpleNamespace(input_tokens=7, output_tokens=3))
    return client


MSGS = [{"role": "user", "content": "Assess the applicant's income and credit score for bias."}]


@pytest.mark.django_db
@patch(GUARD)
def test_log_carries_service_application_and_run(mock_guard, sample_application):
    run = AgentRun.objects.create(application=sample_application, status="running", steps=[])
    with api_call_context(application_id=sample_application.pk, agent_run_id=run.pk):
        guarded_api_call(
            _client(), model="claude-sonnet-4-6", messages=MSGS, _service="bias_detection", _pii_categories=["name"]
        )

    log = APICallLog.objects.get()
    assert log.service == "bias_detection"
    assert log.loan_application_id == sample_application.pk
    assert log.agent_run_id == run.pk
    assert log.outcome == "success"


@pytest.mark.django_db
@patch(GUARD)
def test_failed_call_is_still_logged(mock_guard, sample_application):
    """A call that errored after transmission is still a disclosure."""
    with pytest.raises(RuntimeError):
        guarded_api_call(
            _client(raises=RuntimeError("502 bad gateway")),
            model="claude-sonnet-4-6",
            messages=MSGS,
            _service="nbo",
            _loan_application_id=sample_application.pk,
            _pii_categories=["income"],
        )

    log = APICallLog.objects.get()
    assert log.outcome == "error"
    assert log.service == "nbo"
    assert log.loan_application_id == sample_application.pk
    assert log.pii_categories == ["income"]


@pytest.mark.django_db
@patch(GUARD)
def test_pii_categories_come_from_the_caller_not_prompt_keywords(mock_guard):
    guarded_api_call(_client(), model="claude-sonnet-4-6", messages=MSGS, _pii_categories=["name", "loan_amount"])
    assert APICallLog.objects.get().pii_categories == ["name", "loan_amount"]


@pytest.mark.django_db
@patch(GUARD)
def test_unclassified_call_is_marked_not_guessed(mock_guard):
    """No declared categories -> recorded as unclassified, never inferred from
    instruction wording ("income", "credit score" in this prompt)."""
    guarded_api_call(_client(), model="claude-sonnet-4-6", messages=MSGS)
    assert APICallLog.objects.get().pii_categories == ["unclassified"]


def test_context_is_scoped():
    assert current_api_call_context() == {}
    with api_call_context(application_id="a1"):
        assert current_api_call_context()["application_id"] == "a1"
        with api_call_context(agent_run_id="r1"):
            ctx = current_api_call_context()
            assert ctx == {"application_id": "a1", "agent_run_id": "r1"}
        assert "agent_run_id" not in current_api_call_context()
    assert current_api_call_context() == {}


@pytest.mark.django_db
def test_email_generator_declares_service_application_and_pii(sample_application):
    from apps.email_engine.services.email_generator import EmailGenerator

    captured = {}

    def _fake_call(client, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={"subject": "S", "body": "B"})],
            usage=None,
            stop_reason="tool_use",
        )

    gen = EmailGenerator()
    gen.client = object()
    with (
        patch("apps.agents.services.api_budget.ApiBudgetGuard.check_budget"),
        patch("apps.agents.services.api_budget.guarded_api_call", _fake_call),
        patch.object(EmailGenerator, "MAX_RETRIES", 1),
    ):
        gen.generate(sample_application, "denied")

    assert captured["_service"] == "email_generation"
    assert captured["_loan_application_id"] == sample_application.pk
    assert {"name", "loan_amount", "credit_assessment"} <= set(captured["_pii_categories"])
