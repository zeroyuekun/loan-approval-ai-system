"""Moderate-band bias findings on a decision email: regenerate, re-check, then send or hold.

A bias score above BIAS_THRESHOLD_PASS but below BIAS_THRESHOLD_REVIEW marks
the email ``flagged`` and ``requires_human_review``. A flagged email must never
reach the customer as written. The pipeline (and the human-review resume path)
replaces it once with the deterministic template and runs the bias check on the
replacement. Only a clean replacement is sent; a replacement that is still
flagged, or a flagged email that already was the template, is held for the
human-review queue. The resume path applies the same rule: a reviewer clearing
the run does not clear an email written after the review.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.agents.models import AgentRun, BiasReport
from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.email_generator import EmailGenerator
from apps.loans.models import LoanDecision

SENDER = "apps.email_engine.services.sender.send_decision_email"
HUMAN_REVIEW = "apps.agents.services.human_review_handler"
AGENT2 = "apps.agents.services.bias_agent2"
LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _llm_email(decision="denied"):
    return {
        "subject": f"Your loan decision ({decision})",
        "body": "Dear Customer, LLM-written body.",
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


def _bias(score, flagged):
    return {
        "score": score,
        "flagged": flagged,
        "requires_human_review": flagged,
        "categories": ["tone_check"] if flagged else [],
        "analysis": "moderate finding" if flagged else "clean",
        "score_source": "deterministic_weighted" if flagged else "deterministic",
    }


MODERATE = _bias(45, True)
CLEAN = _bias(5, False)


@pytest.fixture
def processing_denied(sample_application):
    LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.2)
    sample_application.status = "processing"
    sample_application.save()
    return sample_application


def _run_pipeline(application, *, generate_result, bias_results, send):
    from apps.agents.services.email_pipeline import EmailPipelineService
    from apps.agents.services.step_tracker import StepTracker

    run = AgentRun.objects.create(application=application, status="running", steps=[])
    with (
        patch.object(EmailGenerator, "generate", return_value=generate_result),
        patch("apps.agents.services.email_pipeline.BiasDetector") as bias,
        patch("apps.agents.services.email_pipeline.RecommendationEngine") as nbo,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.side_effect = list(bias_results)
        nbo.return_value.recommend.return_value = {"offers": []}
        steps, email_result, generated_email, bias_result, escalated = EmailPipelineService(StepTracker()).run(
            application, run, {}, {"probability": 0.2}, "denied", [], []
        )
    return run, steps, email_result, generated_email, escalated, bias


def _run_pipeline_agent2(
    application,
    *,
    generate_side_effect,
    pipeline_bias_results,
    agent2_bias_result=None,
    agent2_review=None,
    send,
):
    """Like ``_run_pipeline`` but with Agent 2 enabled (the default). Its two
    collaborators — ``BiasDetector`` and ``AIEmailReviewer`` inside
    ``bias_agent2`` — are mocked independently of the pipeline's own
    ``BiasDetector``, which only ever sees the original email and (if Agent 2
    hands over) the template replacement."""
    from apps.agents.services.email_pipeline import EmailPipelineService
    from apps.agents.services.step_tracker import StepTracker

    run = AgentRun.objects.create(application=application, status="running", steps=[])
    steps, waterfall = [], []
    with (
        patch.object(EmailGenerator, "generate", side_effect=generate_side_effect),
        patch("apps.agents.services.email_pipeline.BiasDetector") as bias,
        patch(f"{AGENT2}.BiasDetector") as agent2_bias,
        patch(f"{AGENT2}.AIEmailReviewer") as agent2_reviewer,
        patch(f"{AGENT2}.ApiBudgetGuard"),
        patch("apps.agents.services.email_pipeline.RecommendationEngine") as nbo,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.side_effect = list(pipeline_bias_results)
        if agent2_bias_result is not None:
            agent2_bias.return_value.analyze.return_value = agent2_bias_result
        if agent2_review is not None:
            agent2_reviewer.return_value.review.return_value = agent2_review
        nbo.return_value.recommend.return_value = {"offers": []}
        _, email_result, generated_email, bias_result, escalated = EmailPipelineService(StepTracker()).run(
            application, run, {}, {"probability": 0.2}, "denied", steps, waterfall
        )
    return run, steps, waterfall, email_result, generated_email, escalated, bias, agent2_bias, agent2_reviewer


@pytest.mark.django_db
def test_moderate_email_is_rewritten_by_agent2_and_sent_when_clean_and_approved(processing_denied):
    """Agent 2's rewrite is clean and the senior reviewer approves it with
    confidence: the rewrite is sent, never the template, never the flagged
    original."""
    send = MagicMock(return_value={"sent": True})
    rewrite = {**_llm_email(), "body": "Dear Customer, Agent 2 rewritten body."}

    run, steps, waterfall, email_result, generated_email, escalated, bias, agent2_bias, agent2_reviewer = (
        _run_pipeline_agent2(
            processing_denied,
            generate_side_effect=[_llm_email(), rewrite],
            pipeline_bias_results=[MODERATE, CLEAN],
            agent2_bias_result=CLEAN,
            agent2_review={"approved": True, "confidence": 0.9, "reasoning": "ok"},
            send=send,
        )
    )

    assert not escalated
    assert send.call_count == 1
    assert "Agent 2 rewritten body" in send.call_args.args[2]
    assert "LLM-written body" not in send.call_args.args[2]
    assert bias.return_value.analyze.call_count == 1, "Agent 2 bypasses the template re-check entirely"
    assert any(
        e["reason_code"] == "EMAIL_REGENERATED_AGENT2" and e["step"] == "bias_agent2_regeneration" for e in waterfall
    )
    assert any(
        s["step_name"] == "bias_agent2_regeneration" and s["result_summary"]["regenerated"] is True for s in steps
    )
    generated_email.refresh_from_db()
    assert generated_email.sent_at is not None
    flagged_draft = GeneratedEmail.objects.get(application=processing_denied, body="Dear Customer, LLM-written body.")
    assert flagged_draft.sent_at is None


@pytest.mark.django_db
def test_moderate_email_falls_back_to_template_when_agent2_reviewer_rejects(processing_denied):
    """The senior reviewer rejects Agent 2's rewrite: hand over to the
    deterministic template, which checks clean and is sent."""
    send = MagicMock(return_value={"sent": True})
    rewrite = {**_llm_email(), "body": "Dear Customer, Agent 2 rewritten body."}

    run, steps, waterfall, email_result, generated_email, escalated, bias, agent2_bias, agent2_reviewer = (
        _run_pipeline_agent2(
            processing_denied,
            generate_side_effect=[_llm_email(), rewrite],
            pipeline_bias_results=[MODERATE, CLEAN],
            agent2_bias_result=CLEAN,
            agent2_review={"approved": False, "confidence": 0.95, "reasoning": "tone concerns remain"},
            send=send,
        )
    )

    agent2_reviewer.return_value.review.assert_called_once()
    assert not escalated
    assert send.call_count == 1
    assert "LLM-written body" not in send.call_args.args[2]
    assert "Agent 2 rewritten body" not in send.call_args.args[2]
    assert email_result["template_fallback"] is True
    assert not any(e["reason_code"] == "EMAIL_REGENERATED_AGENT2" for e in waterfall)
    assert any(e["reason_code"] == "EMAIL_REPLACED" for e in waterfall)


@pytest.mark.django_db
def test_moderate_email_escalates_when_agent2_rejects_and_template_also_flagged(processing_denied):
    """The senior reviewer rejects Agent 2's rewrite and the template
    replacement is still flagged: escalate to human review, send nothing."""
    send = MagicMock(return_value={"sent": True})
    rewrite = {**_llm_email(), "body": "Dear Customer, Agent 2 rewritten body."}

    run, steps, waterfall, email_result, generated_email, escalated, bias, agent2_bias, agent2_reviewer = (
        _run_pipeline_agent2(
            processing_denied,
            generate_side_effect=[_llm_email(), rewrite],
            pipeline_bias_results=[MODERATE, MODERATE],
            agent2_bias_result=CLEAN,
            agent2_review={"approved": False, "confidence": 0.95, "reasoning": "tone concerns remain"},
            send=send,
        )
    )

    agent2_reviewer.return_value.review.assert_called_once()
    assert escalated
    send.assert_not_called()
    processing_denied.refresh_from_db()
    assert processing_denied.status == "review"
    assert run.status == "escalated"


@pytest.mark.django_db
def test_bias_report_stores_every_score_source_the_detector_emits(processing_denied):
    """BiasDetector emits 'deterministic_weighted' (22 chars) when the LLM confirms
    a moderate finding; the column must hold it or the insert fails and the
    pipeline misreads the finding as a bias-check outage."""
    run = AgentRun.objects.create(application=processing_denied, status="running", steps=[])
    for source in ("deterministic", "deterministic_weighted", "llm_false_positive", "composite"):
        BiasReport.objects.create(agent_run=run, bias_score=45, score_source=source, categories=[], analysis="")
    assert BiasReport.objects.filter(agent_run=run).count() == 4


@override_settings(BIAS_AGENT2_ENABLED=False)
@pytest.mark.django_db
def test_moderate_llm_email_is_replaced_by_template_and_sent_when_replacement_is_clean(processing_denied):
    send = MagicMock(return_value={"sent": True})

    run, steps, email_result, generated_email, escalated, bias = _run_pipeline(
        processing_denied, generate_result=_llm_email(), bias_results=[MODERATE, CLEAN], send=send
    )

    assert not escalated
    assert bias.return_value.analyze.call_count == 2, "the replacement must be bias-checked too"
    assert send.call_count == 1
    assert "LLM-written body" not in send.call_args.args[2], "the flagged LLM text must not be sent"
    assert email_result["template_fallback"] is True
    generated_email.refresh_from_db()
    assert generated_email.template_fallback is True
    assert generated_email.sent_at is not None
    flagged_draft = GeneratedEmail.objects.get(application=processing_denied, template_fallback=False)
    assert flagged_draft.sent_at is None
    assert flagged_draft.bias_reports.filter(flagged=True).exists()
    assert BiasReport.objects.filter(agent_run=run).count() == 2
    assert any(s["step_name"] == "bias_regeneration" for s in steps)


@override_settings(BIAS_AGENT2_ENABLED=False)
@pytest.mark.django_db
def test_moderate_email_whose_replacement_is_still_flagged_is_held_for_review(processing_denied):
    send = MagicMock(return_value={"sent": True})

    run, steps, _, _, escalated, _ = _run_pipeline(
        processing_denied, generate_result=_llm_email(), bias_results=[MODERATE, MODERATE], send=send
    )

    assert escalated
    send.assert_not_called()
    processing_denied.refresh_from_db()
    assert processing_denied.status == "review"
    assert run.status == "escalated"
    assert not GeneratedEmail.objects.filter(application=processing_denied, sent_at__isnull=False).exists()


@override_settings(BIAS_AGENT2_ENABLED=False)
@pytest.mark.django_db
def test_moderate_template_email_is_held_without_regenerating(processing_denied):
    """Regenerating a flagged template yields the same text, so it goes straight to review."""
    send = MagicMock(return_value={"sent": True})
    template = EmailGenerator().generate_template(processing_denied, "denied")

    run, _, _, _, escalated, bias = _run_pipeline(
        processing_denied, generate_result=template, bias_results=[MODERATE], send=send
    )

    assert escalated
    send.assert_not_called()
    assert bias.return_value.analyze.call_count == 1
    assert GeneratedEmail.objects.filter(application=processing_denied).count() == 1
    processing_denied.refresh_from_db()
    assert processing_denied.status == "review"


@pytest.mark.django_db
def test_clean_email_is_sent_without_regeneration(processing_denied):
    send = MagicMock(return_value={"sent": True})

    _, steps, email_result, _, escalated, bias = _run_pipeline(
        processing_denied, generate_result=_llm_email(), bias_results=[CLEAN], send=send
    )

    assert not escalated
    assert bias.return_value.analyze.call_count == 1
    assert email_result["template_fallback"] is False
    assert send.call_count == 1
    assert not any(s["step_name"] == "bias_regeneration" for s in steps)


# ---------------------------------------------------------------------------
# Human-review resume path: same moderate-band rule
# ---------------------------------------------------------------------------


def _resume(run, *, bias_results, send):
    from apps.agents.services.orchestrator import PipelineOrchestrator

    with (
        patch.object(EmailGenerator, "generate", return_value=_llm_email("approved")),
        patch(f"{HUMAN_REVIEW}.BiasDetector") as bias,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.side_effect = list(bias_results)
        result = PipelineOrchestrator().resume_after_review(run.pk)
    return result, bias


@LOCMEM
@pytest.mark.django_db
def test_resume_replaces_a_moderate_email_with_a_clean_template(escalated_agent_run):
    send = MagicMock(return_value={"sent": True})

    run, bias = _resume(escalated_agent_run, bias_results=[MODERATE, CLEAN], send=send)

    assert run.status == "completed"
    assert bias.return_value.analyze.call_count == 2
    assert send.call_count == 1
    assert "LLM-written body" not in send.call_args.args[2]
    sent = GeneratedEmail.objects.get(application=escalated_agent_run.application, sent_at__isnull=False)
    assert sent.template_fallback is True


@LOCMEM
@pytest.mark.django_db
def test_resume_holds_a_replacement_that_is_still_moderately_flagged(escalated_agent_run):
    """The resume sends a replacement only if it checks clean, as the pipeline
    and the standalone screening do: a moderately flagged template is held and
    the run goes back to the review queue."""
    send = MagicMock(return_value={"sent": True})

    run, bias = _resume(escalated_agent_run, bias_results=[MODERATE, MODERATE], send=send)

    assert bias.return_value.analyze.call_count == 2  # the replacement was checked
    send.assert_not_called()
    assert run.status == "escalated"
    app = escalated_agent_run.application
    app.refresh_from_db()
    assert app.status == "review"


@LOCMEM
@pytest.mark.django_db
def test_resume_re_escalates_when_the_replacement_is_severe(escalated_agent_run):
    send = MagicMock(return_value={"sent": True})

    run, _ = _resume(escalated_agent_run, bias_results=[MODERATE, _bias(75, True)], send=send)

    send.assert_not_called()
    assert run.status == "escalated"
    app = escalated_agent_run.application
    app.refresh_from_db()
    assert app.status == "review"
