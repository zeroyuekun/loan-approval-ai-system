"""I2 / I3 / I4 — every decided application gets exactly one decision notice.

- I2: when the LLM output fails the guardrails on every attempt, the compliant
  deterministic template is issued instead of withholding the notice.
- I3: a provider 429 (RateLimited) outside the Celery email task degrades to
  the template rather than leaving the customer with no email.
- I4: human-review Deny sends the denial email; resuming a denied run sends the
  denial before the marketing follow-up; resuming an approved run stamps
  sent_at so a later generate/send does not email the customer twice.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.exceptions import RateLimited
from apps.loans.models import LoanDecision

SENDER = "apps.email_engine.services.sender.send_decision_email"
HUMAN_REVIEW = "apps.agents.services.human_review_handler"
LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _passing(decision="approved"):
    return {
        "subject": f"Your loan decision ({decision})",
        "body": "Dear Customer, body text.",
        "prompt_used": "p",
        "guardrail_results": [],
        "passed_guardrails": True,
        "quality_score": 100,
        "generation_time_ms": 5,
        "attempt_number": 1,
        "template_fallback": False,
        "input_tokens": 10,
        "output_tokens": 20,
        "model_used": "claude-sonnet-4-6",
    }


def _clean_bias():
    return {
        "score": 5,
        "flagged": False,
        "requires_human_review": False,
        "categories": [],
        "analysis": "clean",
        "score_source": "deterministic",
    }


@pytest.fixture
def decided_denied(sample_application):
    LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.2)
    return sample_application


# ---------------------------------------------------------------------------
# I2 — guardrail exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guardrail_exhaustion_issues_compliant_template(decided_denied):
    gen = EmailGenerator()
    gen.client = object()  # pretend an LLM backend is configured

    response = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"subject": "Bad", "body": "LLM draft that fails"})],
        usage=None,
        stop_reason="tool_use",
    )
    llm_calls = []

    def _fake_call(*args, **kwargs):
        llm_calls.append(1)
        return response

    real_checks = gen.guardrail_checker.run_all_checks

    def _checks(body, context, template_mode=False):
        if template_mode:
            return real_checks(body, context, template_mode=True)
        return [{"check_name": "prohibited_language", "passed": False, "details": "x", "weight": 20}]

    gen.guardrail_checker.run_all_checks = _checks
    with (
        patch("apps.agents.services.api_budget.ApiBudgetGuard.check_budget"),
        patch("apps.agents.services.api_budget.guarded_api_call", _fake_call),
    ):
        result = gen.generate(decided_denied, "denied")

    assert len(llm_calls) == EmailGenerator.MAX_RETRIES
    assert result["template_fallback"] is True
    assert result["passed_guardrails"] is True, "the template must be issued, not withheld"
    assert "LLM draft that fails" not in result["body"]


# ---------------------------------------------------------------------------
# I3 — rate limiting outside the Celery task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rate_limited_degrades_to_template_in_service(decided_denied):
    from apps.email_engine.services.decision_email import generate_decision_email

    with patch.object(EmailGenerator, "generate", side_effect=RateLimited(retry_after=30)):
        result, email = generate_decision_email(decided_denied, "denied")

    assert result["template_fallback"] is True
    assert email.passed_guardrails is True
    assert email.model_used == "template"


@pytest.mark.django_db
def test_rate_limited_can_still_propagate_for_celery_retry(decided_denied):
    from apps.email_engine.services.decision_email import generate_decision_email

    with patch.object(EmailGenerator, "generate", side_effect=RateLimited(retry_after=30)):
        with pytest.raises(RateLimited):
            generate_decision_email(decided_denied, "denied", on_rate_limit="raise")


@pytest.mark.django_db
def test_orchestrator_email_step_sends_template_on_rate_limit(decided_denied):
    from apps.agents.models import AgentRun
    from apps.agents.services.email_pipeline import EmailPipelineService
    from apps.agents.services.step_tracker import StepTracker

    run = AgentRun.objects.create(application=decided_denied, status="running", steps=[])
    send = MagicMock(return_value={"sent": True})
    with (
        patch.object(EmailGenerator, "generate", side_effect=RateLimited(retry_after=30)),
        patch("apps.agents.services.email_pipeline.BiasDetector") as bias,
        patch("apps.agents.services.email_pipeline.RecommendationEngine") as nbo,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.return_value = _clean_bias()
        nbo.return_value.recommend.return_value = {"offers": []}
        steps, email_result, generated_email, _, escalated = EmailPipelineService(StepTracker()).run(
            decided_denied, run, {}, {"probability": 0.2}, "denied", [], []
        )

    assert not escalated
    assert email_result is not None and email_result["template_fallback"] is True
    assert send.call_count == 1
    assert send.call_args.kwargs["email_type"] == "denial"
    generated_email.refresh_from_db()
    assert generated_email.sent_at is not None


# ---------------------------------------------------------------------------
# I4 — human-review outcomes
# ---------------------------------------------------------------------------


def _deny(run, officer_user, *, bias_result, send):
    """POST a human-review Deny and run the resume task it queues in-process."""
    from apps.agents.tasks import resume_pipeline_task

    def _run_task(*args, **kwargs):
        return resume_pipeline_task.apply(args=args, kwargs=kwargs)

    client = APIClient()
    client.force_authenticate(user=officer_user)
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("denied")),
        patch(f"{HUMAN_REVIEW}.BiasDetector") as bias,
        patch(f"{HUMAN_REVIEW}.MarketingPipelineService") as mkt,
        patch("apps.agents.services.email_pipeline.RecommendationEngine") as nbo,
        patch("apps.agents.views.resume_pipeline_task.delay", side_effect=_run_task),
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        patch(SENDER, send),
    ):
        bias.return_value.analyze.return_value = bias_result
        mkt.return_value.run.side_effect = lambda application, agent_run, steps, *a, **kw: steps
        nbo.return_value.recommend.return_value = {"offers": []}
        resp = client.post(f"/api/v1/agents/review/{run.id}/", {"action": "deny", "note": "n"}, format="json")
    return resp, bias


@LOCMEM
@pytest.mark.django_db(transaction=True)
def test_human_review_deny_sends_bias_checked_denial_email(escalated_agent_run, officer_user):
    """A2: the reviewer's denial goes through the same issue path as every
    other decision email: generate, bias pre-screen/check, deliver once."""
    app = escalated_agent_run.application
    send = MagicMock(return_value={"sent": True})

    resp, bias = _deny(escalated_agent_run, officer_user, bias_result=_clean_bias(), send=send)

    assert resp.status_code == 200, resp.data
    bias.return_value.analyze.assert_called_once()
    assert bias.return_value.analyze.call_args.args[1]["decision"] == "denied"
    denial = GeneratedEmail.objects.get(application=app, decision="denied")
    assert denial.sent_at is not None
    assert send.call_count == 1
    assert send.call_args.kwargs["email_type"] == "denial"
    app.refresh_from_db()
    assert app.status == "denied"
    decision = LoanDecision.objects.get(application=app)
    assert decision.decision == "denied"
    # The model approved; the officer denied: an override, not a review.
    assert decision.human_involvement == LoanDecision.HumanInvolvement.OVERRIDDEN
    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == "completed"


@LOCMEM
@pytest.mark.django_db(transaction=True)
def test_human_review_deny_withholds_a_bias_flagged_denial_email(escalated_agent_run, officer_user):
    app = escalated_agent_run.application
    send = MagicMock(return_value={"sent": True})
    flagged = {**_clean_bias(), "score": 75, "flagged": True, "requires_human_review": True}

    resp, _ = _deny(escalated_agent_run, officer_user, bias_result=flagged, send=send)

    assert resp.status_code == 200, resp.data
    send.assert_not_called()
    app.refresh_from_db()
    assert app.status == "review"  # back in the bias queue, not denied without a notice
    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == "escalated"
    held = GeneratedEmail.objects.get(application=app, decision="denied")
    assert held.sent_at is None
    assert held.bias_reports.filter(flagged=True).exists()  # identifiable as bias-held


def _resume(run_id):
    from apps.agents.services.orchestrator import PipelineOrchestrator

    return PipelineOrchestrator().resume_after_review(run_id)


@LOCMEM
@pytest.mark.django_db
def test_resume_denied_sends_denial_before_marketing(escalated_agent_run):
    decision = escalated_agent_run.application.decision
    decision.decision = "denied"
    decision.save()
    send = MagicMock(return_value={"sent": True})
    order = []
    send.side_effect = lambda *a, **kw: order.append(("send", kw.get("email_type"))) or {"sent": True}

    def _marketing(application, agent_run, steps, *a, **kw):
        order.append(("marketing", None))
        return steps

    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("denied")),
        patch(f"{HUMAN_REVIEW}.BiasDetector") as bias,
        patch(f"{HUMAN_REVIEW}.MarketingPipelineService") as mkt,
        patch("apps.agents.services.email_pipeline.RecommendationEngine") as nbo,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.return_value = _clean_bias()
        mkt.return_value.run.side_effect = _marketing
        nbo.return_value.recommend.return_value = {"offers": []}
        run = _resume(escalated_agent_run.pk)

    assert run.status == "completed"
    assert order == [("send", "denial"), ("marketing", None)]
    assert GeneratedEmail.objects.get(application=escalated_agent_run.application, decision="denied").sent_at


@LOCMEM
@pytest.mark.django_db
def test_resume_approved_stamps_sent_at_so_no_duplicate_send(escalated_agent_run):
    from apps.email_engine.tasks import generate_email_task

    send = MagicMock(return_value={"sent": True})
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("approved")),
        patch(f"{HUMAN_REVIEW}.BiasDetector") as bias,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.return_value = _clean_bias()
        run = _resume(escalated_agent_run.pk)
        assert run.status == "completed"
        assert send.call_count == 1

        email = GeneratedEmail.objects.get(application=escalated_agent_run.application, decision="approved")
        assert email.sent_at is not None

        # A later standalone generate/send for the same decision must not re-send.
        result = generate_email_task.apply(args=(str(escalated_agent_run.application_id), "approved")).get()
        assert result["email_sent"] is True
        assert send.call_count == 1


@pytest.mark.django_db
def test_decision_review_overturn_email_stamps_sent_at(sample_application):
    """The overturn path sends through the shared service, so sent_at is set."""
    from apps.loans.services import decision_review as svc

    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.7)
    send = MagicMock(return_value={"sent": True})
    with patch.object(EmailGenerator, "generate", return_value=_passing("approved")), patch(SENDER, send):
        svc._send_approval_email(sample_application)

    email = GeneratedEmail.objects.get(application=sample_application, decision="approved")
    assert email.sent_at is not None
    assert send.call_count == 1


@pytest.mark.django_db
def test_persisted_model_used_is_the_actual_backend(decided_denied):
    """Known issue: model_used was hardcoded to claude-sonnet-4-6 for every email."""
    from apps.email_engine.services.decision_email import generate_decision_email

    result = {**_passing("denied"), "model_used": "ollama:llama3.2:3b"}
    with patch.object(EmailGenerator, "generate", return_value=result):
        _, email = generate_decision_email(decided_denied, "denied")
    assert email.model_used == "ollama:llama3.2:3b"
