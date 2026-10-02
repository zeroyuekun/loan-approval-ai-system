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
        patch("apps.agents.services.human_review_actions.resume_pipeline_task.delay", side_effect=_run_task),
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        patch(SENDER, send),
    ):
        bias.return_value.analyze.return_value = bias_result
        mkt.return_value.run_best_effort.side_effect = lambda application, agent_run, steps, *a, **kw: steps
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
        mkt.return_value.run_best_effort.side_effect = _marketing
        nbo.return_value.recommend.return_value = {"offers": []}
        run = _resume(escalated_agent_run.pk)

    assert run.status == "completed"
    assert order == [("send", "denial"), ("marketing", None)]
    assert GeneratedEmail.objects.get(application=escalated_agent_run.application, decision="denied").sent_at


@LOCMEM
@pytest.mark.django_db
def test_resume_follow_up_failure_after_the_denial_email_keeps_the_decision(escalated_agent_run):
    """The marketing follow-up hits the soft time limit after the denial email
    was sent: the denial stands and the run is not put back in the review
    queue, where the next approve would email the customer again."""
    from celery.exceptions import SoftTimeLimitExceeded

    from apps.agents.tasks import resume_pipeline_task

    decision = escalated_agent_run.application.decision
    decision.decision = "denied"
    decision.save()
    send = MagicMock(return_value={"sent": True})
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("denied")),
        patch(f"{HUMAN_REVIEW}.BiasDetector") as bias,
        patch(f"{HUMAN_REVIEW}.MarketingPipelineService.run", side_effect=SoftTimeLimitExceeded()),
        patch("apps.agents.services.email_pipeline.RecommendationEngine") as nbo,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.return_value = _clean_bias()
        nbo.return_value.recommend.return_value = {"offers": []}
        resume_pipeline_task.apply(args=(str(escalated_agent_run.pk),))

    app = escalated_agent_run.application
    app.refresh_from_db()
    assert app.status == "denied", "a follow-up failure put the announced denial back in the review queue"
    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == "completed"
    assert send.call_count == 1


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


# ---------------------------------------------------------------------------
# Standalone issuance (generate_email_task, decision review overturn): the
# email is bias-checked before it is sent, and the overturn queues it.
# ---------------------------------------------------------------------------

BIAS_ANALYZE = "apps.agents.services.bias.core.BiasDetector.analyze"


def _severe_bias():
    return {
        "score": 85,
        "flagged": True,
        "requires_human_review": True,
        "categories": ["gender"],
        "analysis": "severe",
        "score_source": "deterministic",
    }


def _moderate_bias():
    return {**_severe_bias(), "score": 45, "requires_human_review": False, "analysis": "moderate"}


def _template(decision="approved"):
    return {**_passing(decision), "subject": "Template subject", "body": "Template body.", "template_fallback": True}


@pytest.fixture
def overturnable(sample_application, officer_user):
    from apps.loans.models import DecisionReview

    sample_application.status = "denied"
    sample_application.save(update_fields=["status"])
    LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.4)
    review = DecisionReview.objects.create(
        application=sample_application,
        requested_by=sample_application.applicant,
        reason="disagree",
        status=DecisionReview.Status.UNDER_REVIEW,
    )
    return review, officer_user


@pytest.fixture
def pipeline_run(overturnable):
    """The completed pipeline run that denied the application."""
    from apps.agents.models import AgentRun

    review, _ = overturnable
    return AgentRun.objects.create(
        application=review.application,
        status=AgentRun.Status.COMPLETED,
        steps=[{"step_name": "ml_prediction", "status": "completed"}],
    )


def _overturn_with_severe_bias(review, officer, django_capture_on_commit_callbacks):
    """Overturn, running the queued email task in-process with a severe bias finding."""
    from apps.email_engine.tasks import generate_email_task
    from apps.loans.services.decision_review import apply_review_outcome

    send = MagicMock(return_value={"sent": True})

    def _run_now(*args, **kwargs):
        return generate_email_task.apply(args=args, kwargs=kwargs).get()

    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("approved")),
        patch(BIAS_ANALYZE, return_value=_severe_bias()) as analyze,
        patch(SENDER, send),
        patch("apps.email_engine.tasks.generate_email_task.delay", side_effect=_run_now),
        django_capture_on_commit_callbacks(execute=True),
    ):
        apply_review_outcome(review, officer=officer, outcome="overturned", note="manual approve")
    return analyze, send


@pytest.fixture
def decided_approved(sample_application):
    sample_application.status = "approved"
    sample_application.save(update_fields=["status"])
    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.8)
    return sample_application


@LOCMEM
@pytest.mark.django_db
def test_generate_email_task_holds_a_severely_biased_email(decided_approved):
    from apps.agents.models import BiasReport
    from apps.email_engine.tasks import generate_email_task
    from apps.loans.models import AuditLog

    send = MagicMock(return_value={"sent": True})
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("approved")),
        patch(BIAS_ANALYZE, return_value=_severe_bias()) as analyze,
        patch(SENDER, send),
    ):
        result = generate_email_task.apply(
            args=(str(decided_approved.pk), "approved"), kwargs={"regenerate": True}
        ).get()

    assert analyze.call_count == 1, "the email was sent without a bias check"
    assert send.call_count == 0
    assert result["email_sent"] is False
    assert result["held_reason"]
    email = GeneratedEmail.objects.get(pk=result["email_id"])
    assert email.sent_at is None
    # The flagged report is what keeps the staff send paths from releasing it.
    assert BiasReport.objects.filter(email=email, flagged=True).exists()
    assert AuditLog.objects.filter(action="decision_email_held", resource_id=str(email.pk)).exists()


@LOCMEM
@pytest.mark.django_db
def test_generate_email_task_replaces_a_flagged_email_with_the_template(decided_approved):
    from apps.email_engine.tasks import generate_email_task

    send = MagicMock(return_value={"sent": True})
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("approved")),
        patch.object(EmailGenerator, "generate_template", return_value=_template("approved")),
        patch(BIAS_ANALYZE, side_effect=[_moderate_bias(), _clean_bias()]) as analyze,
        patch(SENDER, send),
    ):
        result = generate_email_task.apply(
            args=(str(decided_approved.pk), "approved"), kwargs={"regenerate": True}
        ).get()

    assert analyze.call_count == 2, "the flagged email was not replaced and re-checked"
    assert send.call_count == 1
    assert send.call_args.args[2] == "Template body."  # never the flagged LLM text
    assert result["email_sent"] is True
    assert GeneratedEmail.objects.get(pk=result["email_id"]).template_fallback is True


@LOCMEM
@pytest.mark.django_db
def test_screening_counts_an_unavailable_bias_check(decided_approved):
    """The bias_check_unavailable alert covers the standalone screening, not
    only the pipeline: an outage there withholds the email and is counted."""
    from apps.agents.metrics import bias_check_unavailable_total
    from apps.email_engine.tasks import generate_email_task

    counter = bias_check_unavailable_total.labels(mode="block")
    before = counter._value.get()
    send = MagicMock(return_value={"sent": True})
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("approved")),
        patch(BIAS_ANALYZE, side_effect=RuntimeError("detector down")),
        patch(SENDER, send),
        override_settings(BIAS_FAILURE_MODE="block"),
    ):
        result = generate_email_task.apply(
            args=(str(decided_approved.pk), "approved"), kwargs={"regenerate": True}
        ).get()

    assert counter._value.get() == before + 1
    send.assert_not_called()
    assert result["held_reason"].startswith("Bias check unavailable")


@LOCMEM
@pytest.mark.django_db
def test_redelivery_bias_checks_a_draft_that_was_never_screened(decided_approved):
    """A stored draft with no bias report (the check was down, or the worker
    died before it ran) is screened before the redelivery path sends it."""
    from apps.email_engine.tasks import generate_email_task

    GeneratedEmail.objects.create(
        application=decided_approved,
        decision="approved",
        subject="s",
        body="Dear Customer, body text.",
        prompt_used="p",
        passed_guardrails=True,
    )
    send = MagicMock(return_value={"sent": True})
    with patch(BIAS_ANALYZE, return_value=_severe_bias()) as analyze, patch(SENDER, send):
        result = generate_email_task.apply(args=(str(decided_approved.pk), "approved")).get()

    assert analyze.call_count == 1, "an unscreened draft was redelivered without a bias check"
    assert send.call_count == 0
    assert result["email_sent"] is False


@LOCMEM
@pytest.mark.django_db
def test_overturn_approval_email_is_bias_checked(overturnable, django_capture_on_commit_callbacks):
    """The overturn issues its approval email through the bias-checked path:
    a severely flagged LLM email is held, not sent."""
    review, officer = overturnable

    analyze, send = _overturn_with_severe_bias(review, officer, django_capture_on_commit_callbacks)

    assert analyze.call_count == 1, "the overturn approval email skipped the bias check"
    assert send.call_count == 0
    email = GeneratedEmail.objects.get(application=review.application, decision="approved")
    assert email.sent_at is None


@LOCMEM
@pytest.mark.django_db
def test_overturn_screening_is_recorded_on_the_existing_run(
    overturnable, pipeline_run, django_capture_on_commit_callbacks
):
    """The screening's bias report goes on the run that decided the application.
    No new AgentRun: one would become the application's latest run."""
    from apps.agents.models import AgentRun, BiasReport

    review, officer = overturnable
    runs_before = AgentRun.objects.filter(application=review.application).count()

    _overturn_with_severe_bias(review, officer, django_capture_on_commit_callbacks)

    assert AgentRun.objects.filter(application=review.application).count() == runs_before, (
        "the screening created a run of its own"
    )
    email = GeneratedEmail.objects.get(application=review.application, decision="approved")
    report = BiasReport.objects.get(email=email)
    assert report.agent_run_id == pipeline_run.pk
    assert report.flagged is True
    pipeline_run.refresh_from_db()
    assert pipeline_run.status == AgentRun.Status.COMPLETED  # status left alone
    assert pipeline_run.steps[-1]["step_name"] == "decision_email_reissue"
    assert pipeline_run.steps[-1]["result_summary"]["sent"] is False


@LOCMEM
@pytest.mark.django_db
def test_run_view_still_shows_the_pipeline_run_after_a_screening(
    overturnable, pipeline_run, officer_user, django_capture_on_commit_callbacks
):
    review, officer = overturnable

    _overturn_with_severe_bias(review, officer, django_capture_on_commit_callbacks)

    client = APIClient()
    client.force_authenticate(user=officer_user)
    resp = client.get(f"/api/v1/agents/runs/{review.application_id}/")
    assert resp.status_code == 200, resp.data
    assert resp.data["id"] == str(pipeline_run.pk), "the Pipeline tab shows a screening stub, not the pipeline run"
    assert resp.data["steps"][0]["step_name"] == "ml_prediction"
    assert [r["flagged"] for r in resp.data["bias_reports"]] == [True]


@pytest.mark.django_db
def test_overturn_queues_the_approval_email_after_commit(overturnable, django_capture_on_commit_callbacks):
    """No LLM call or SMTP send inside the request: the overturn queues the
    email task once the transaction commits."""
    from apps.loans.services.decision_review import apply_review_outcome

    review, officer = overturnable
    with (
        patch.object(EmailGenerator, "generate", return_value=_passing("approved")) as generate,
        patch(SENDER, MagicMock(return_value={"sent": True})),
        patch("apps.email_engine.tasks.generate_email_task.delay") as delay,
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            apply_review_outcome(review, officer=officer, outcome="overturned", note="manual approve")
        assert delay.call_count == 0  # nothing dispatched before COMMIT
        for callback in callbacks:
            callback()

    delay.assert_called_once_with(str(review.application_id), "approved", regenerate=True)
    assert generate.call_count == 0, "the approval email was generated inside the request"


@pytest.mark.django_db
def test_persisted_model_used_is_the_actual_backend(decided_denied):
    """Known issue: model_used was hardcoded to claude-sonnet-4-6 for every email."""
    from apps.email_engine.services.decision_email import generate_decision_email

    result = {**_passing("denied"), "model_used": "ollama:llama3.2:3b"}
    with patch.object(EmailGenerator, "generate", return_value=result):
        _, email = generate_decision_email(decided_denied, "denied")
    assert email.model_used == "ollama:llama3.2:3b"
