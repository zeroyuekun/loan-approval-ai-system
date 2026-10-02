"""Agent 2: a bias-flagged decision email gets rewritten with reviewer feedback.

``EmailGenerator.generate`` accepts ``bias_feedback`` and appends it to the
prompt as a compliance-review note. ``regenerate_decision_email`` wraps the
rewrite and persists it — unless the generator degraded to the template,
which is never persisted here because the template-replacement path (see
``test_bias_moderate_band.py``) persists its own template.

The tests below cover ``apps.agents.services.bias_agent2.run_agent2``, the
orchestration that calls the rewrite, re-checks it with the bias detector and
a senior reviewer, and hands over to the template path on anything but a
clean, confidently-approved rewrite.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.agents.models import AgentRun, BiasReport
from apps.agents.services.step_tracker import StepTracker
from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.exceptions import RateLimited

from .test_bias_moderate_band import _llm_email, processing_denied  # noqa: F401 - fixture + helper reuse

__all__ = ["processing_denied"]

AGENT2 = "apps.agents.services.bias_agent2"


@pytest.mark.django_db
def test_bias_feedback_reaches_the_prompt(processing_denied):
    gen = EmailGenerator()
    gen.client = object()  # pretend an LLM backend is configured
    captured = {}

    def _fake_call(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        raise RuntimeError("stop after prompt build")

    with (
        patch("apps.agents.services.api_budget.ApiBudgetGuard.check_budget"),
        patch("apps.agents.services.api_budget.guarded_api_call", _fake_call),
    ):
        try:
            gen.generate(processing_denied, "denied", bias_feedback="tone_check: labels the person")
        except Exception:
            pass

    assert "COMPLIANCE REVIEW FEEDBACK" in captured["prompt"]
    assert "tone_check: labels the person" in captured["prompt"]


@pytest.mark.django_db
def test_regenerate_does_not_persist_a_template_result(processing_denied):
    from apps.email_engine.services.decision_email import regenerate_decision_email

    gen = MagicMock()
    gen.generate.return_value = {**_llm_email(), "template_fallback": True}
    result, generated = regenerate_decision_email(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x", generator=gen
    )
    assert generated is None
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()


@pytest.mark.django_db
def test_regenerate_persists_a_non_template_result(processing_denied):
    from apps.email_engine.services.decision_email import regenerate_decision_email

    gen = MagicMock()
    gen.generate.return_value = _llm_email()
    result, generated = regenerate_decision_email(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x", generator=gen
    )
    assert generated is not None
    assert GeneratedEmail.objects.filter(application=processing_denied).exists()
    gen.generate.assert_called_once_with(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x"
    )


# ---------------------------------------------------------------------------
# run_agent2: rewrite a moderate-band flagged email, re-check it more strictly
# ---------------------------------------------------------------------------


def _bias_result(score=45, flagged=True, categories=None, analysis="moderate finding"):
    return {
        "score": score,
        "flagged": flagged,
        "requires_human_review": flagged,
        "categories": categories if categories is not None else (["tone_check"] if flagged else []),
        "analysis": analysis,
        "score_source": "deterministic_weighted" if flagged else "deterministic",
    }


def _review(approved=True, confidence=0.9, reasoning="ok"):
    return {"approved": approved, "confidence": confidence, "reasoning": reasoning}


def _generated_email(application, body="New rewritten body"):
    return GeneratedEmail.objects.create(
        application=application,
        decision="denied",
        subject="Your loan decision (denied)",
        body=body,
        prompt_used="p",
        passed_guardrails=True,
    )


@pytest.fixture
def agent_run(processing_denied):
    return AgentRun.objects.create(application=processing_denied, status="running", steps=[])


def _run(
    application,
    agent_run,
    *,
    email_result=None,
    bias_result=None,
    regen_return=None,
    regen_side_effect=None,
    new_bias=None,
    review=None,
    enabled=True,
):
    """Call ``run_agent2`` with the three collaborators patched. Returns
    ``(outcome, steps, regen_mock, detector_cls, reviewer_cls)``."""
    from apps.agents.services.bias_agent2 import run_agent2

    email_result = _llm_email() if email_result is None else email_result
    bias_result = bias_result if bias_result is not None else _bias_result()
    steps = []
    tracker = StepTracker()

    with ExitStack() as stack:
        regen = stack.enter_context(patch(f"{AGENT2}.regenerate_decision_email"))
        detector_cls = stack.enter_context(patch(f"{AGENT2}.BiasDetector"))
        reviewer_cls = stack.enter_context(patch(f"{AGENT2}.AIEmailReviewer"))
        if regen_side_effect is not None:
            regen.side_effect = regen_side_effect
        else:
            regen.return_value = regen_return
        if new_bias is not None:
            detector_cls.return_value.analyze.return_value = new_bias
        if review is not None:
            reviewer_cls.return_value.review.return_value = review
        with override_settings(BIAS_AGENT2_ENABLED=enabled):
            outcome = run_agent2(
                application,
                agent_run,
                "denied",
                email_result,
                bias_result,
                confidence=0.2,
                profile_context={},
                tracker=tracker,
                steps=steps,
            )
    return outcome, steps, regen, detector_cls, reviewer_cls


@pytest.mark.django_db
def test_disabled_returns_none_without_calling_the_generator(processing_denied, agent_run):
    outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, enabled=False)

    assert outcome is None
    regen.assert_not_called()
    detector_cls.assert_not_called()
    reviewer_cls.assert_not_called()
    assert steps == []


@pytest.mark.django_db
def test_original_template_fallback_returns_none_without_calling_the_generator(processing_denied, agent_run):
    original_template = {**_llm_email(), "template_fallback": True}

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, email_result=original_template
    )

    assert outcome is None
    regen.assert_not_called()
    detector_cls.assert_not_called()
    reviewer_cls.assert_not_called()
    assert steps == []


@pytest.mark.django_db
def test_regenerated_result_is_a_template_returns_none(processing_denied, agent_run):
    regen_return = ({**_llm_email(), "template_fallback": True}, None)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, regen_return=regen_return)

    assert outcome is None
    regen.assert_called_once()
    detector_cls.return_value.analyze.assert_not_called()
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["step_name"] == "bias_agent2_regeneration"
    assert steps[0]["result_summary"]["regenerated"] is False


@pytest.mark.django_db
def test_regenerated_result_fails_guardrails_returns_none(processing_denied, agent_run):
    generated = _generated_email(processing_denied)
    regen_return = ({**_llm_email(), "passed_guardrails": False, "body": "New rewritten body"}, generated)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, regen_return=regen_return)

    assert outcome is None
    detector_cls.return_value.analyze.assert_not_called()
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"]["regenerated"] is False
    assert not BiasReport.objects.filter(email=generated).exists()


@pytest.mark.django_db
def test_detector_flags_the_rewrite_returns_none(processing_denied, agent_run):
    generated = _generated_email(processing_denied, body="New rewritten body")
    regen_return = ({**_llm_email(), "passed_guardrails": True, "body": "New rewritten body"}, generated)
    still_flagged = _bias_result(score=45, flagged=True)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=regen_return, new_bias=still_flagged
    )

    assert outcome is None
    detector_cls.return_value.analyze.assert_called_once_with(
        "New rewritten body",
        {
            "loan_amount": float(processing_denied.loan_amount),
            "purpose": processing_denied.get_purpose_display(),
            "decision": "denied",
        },
    )
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"]["regenerated"] is False
    assert steps[0]["result_summary"]["bias_score"] == 45
    report = BiasReport.objects.get(email=generated)
    assert report.flagged is True


@pytest.mark.django_db
def test_reviewer_rejects_the_rewrite_returns_none(processing_denied, agent_run):
    generated = _generated_email(processing_denied, body="New rewritten body")
    regen_return = ({**_llm_email(), "passed_guardrails": True, "body": "New rewritten body"}, generated)
    clean = _bias_result(score=5, flagged=False)
    rejected = _review(approved=False, confidence=0.95)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=regen_return, new_bias=clean, review=rejected
    )

    assert outcome is None
    reviewer_cls.return_value.review.assert_called_once_with(
        "New rewritten body",
        clean,
        {
            "loan_amount": float(processing_denied.loan_amount),
            "purpose": processing_denied.get_purpose_display(),
            "decision": "denied",
        },
    )
    assert len(steps) == 1
    summary = steps[0]["result_summary"]
    assert summary["regenerated"] is False
    assert summary["reviewer_approved"] is False
    assert BiasReport.objects.filter(email=generated).exists()


@pytest.mark.django_db
def test_reviewer_approves_with_low_confidence_returns_none(processing_denied, agent_run):
    generated = _generated_email(processing_denied, body="New rewritten body")
    regen_return = ({**_llm_email(), "passed_guardrails": True, "body": "New rewritten body"}, generated)
    clean = _bias_result(score=5, flagged=False)
    low_confidence = _review(approved=True, confidence=0.5)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=regen_return, new_bias=clean, review=low_confidence
    )

    assert outcome is None
    assert len(steps) == 1
    summary = steps[0]["result_summary"]
    assert summary["regenerated"] is False
    assert summary["reviewer_approved"] is True
    assert summary["reviewer_confidence"] == 0.5


@pytest.mark.django_db
@pytest.mark.parametrize("exc", [RateLimited("rate limited"), RuntimeError("boom")])
def test_generator_exception_returns_none(processing_denied, agent_run, exc):
    outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, regen_side_effect=exc)

    assert outcome is None
    detector_cls.return_value.analyze.assert_not_called()
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"]["regenerated"] is False
    assert steps[0]["status"] == "completed"


@pytest.mark.django_db
def test_clean_detector_and_confident_reviewer_returns_the_tuple_to_send(processing_denied, agent_run):
    generated = _generated_email(processing_denied, body="New rewritten body")
    result_dict = {**_llm_email(), "passed_guardrails": True, "body": "New rewritten body"}
    regen_return = (result_dict, generated)
    clean = _bias_result(score=5, flagged=False)
    approved = _review(approved=True, confidence=0.9)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied,
        agent_run,
        email_result={**_llm_email(), "body": "Old flagged body"},
        regen_return=regen_return,
        new_bias=clean,
        review=approved,
    )

    assert outcome == (result_dict, generated, clean)
    # The reviewer sees the NEW body, not the original flagged email's body.
    reviewer_cls.return_value.review.assert_called_once()
    assert reviewer_cls.return_value.review.call_args.args[0] == "New rewritten body"
    assert len(steps) == 1
    summary = steps[0]["result_summary"]
    assert summary["regenerated"] is True
    assert summary["flagged"] is False
    assert summary["reviewer_approved"] is True
    assert summary["reviewer_confidence"] == 0.9
    assert BiasReport.objects.filter(email=generated, flagged=False).exists()
