"""Agent 2: a bias-flagged decision email gets rewritten with reviewer feedback.

``EmailGenerator.generate`` accepts ``bias_feedback`` and appends it to the
prompt as a compliance-review note. ``regenerate_decision_email`` returns the
rewrite without persisting it: ``run_agent2`` persists it only after the bias
detector has scored it, in one transaction with a bias report whose
``ai_review_approved`` stays False until the senior reviewer approves it. A
rewrite therefore never exists in the database without a report that holds it
from the staff send paths (see ``test_bias_held_email.py``).

The tests below cover ``apps.agents.services.bias_agent2.run_agent2``, the
orchestration that calls the rewrite, re-checks it with the bias detector and
a senior reviewer, and hands over to the template path on anything but a
clean, confidently-approved rewrite.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.test import override_settings

from apps.agents.models import AgentRun, BiasReport
from apps.agents.services.api_budget import BudgetExhausted, CircuitOpen
from apps.agents.services.step_tracker import StepTracker, pipeline_deadline
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
@pytest.mark.parametrize("template_fallback", [True, False], ids=["template", "llm-rewrite"])
def test_regenerate_returns_the_result_without_persisting_it(processing_denied, template_fallback):
    from apps.email_engine.services.decision_email import regenerate_decision_email

    gen = MagicMock()
    gen.generate.return_value = {**_llm_email(), "template_fallback": template_fallback}
    result = regenerate_decision_email(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x", generator=gen
    )
    assert result == gen.generate.return_value
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()
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


def _rewrite(body="New rewritten body", **overrides):
    return {**_llm_email(), "passed_guardrails": True, "body": body, **overrides}


def _persisted_rewrite(application, body="New rewritten body"):
    return GeneratedEmail.objects.get(application=application, body=body)


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
    detector_side_effect=None,
    review=None,
    review_side_effect=None,
    budget_side_effect=None,
    profile_context=None,
    enabled=True,
):
    """Call ``run_agent2`` with its collaborators patched. Returns
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
        budget_cls = stack.enter_context(patch(f"{AGENT2}.ApiBudgetGuard"))
        budget_cls.return_value.check_budget.side_effect = budget_side_effect
        if regen_side_effect is not None:
            regen.side_effect = regen_side_effect
        else:
            regen.return_value = regen_return
        if detector_side_effect is not None:
            detector_cls.return_value.analyze.side_effect = detector_side_effect
        elif new_bias is not None:
            detector_cls.return_value.analyze.return_value = new_bias
        if review_side_effect is not None:
            reviewer_cls.return_value.review.side_effect = review_side_effect
        elif review is not None:
            reviewer_cls.return_value.review.return_value = review
        with override_settings(BIAS_AGENT2_ENABLED=enabled):
            outcome = run_agent2(
                application,
                agent_run,
                "denied",
                email_result,
                bias_result,
                confidence=0.2,
                profile_context={} if profile_context is None else profile_context,
                tracker=tracker,
                steps=steps,
            )
    return outcome, steps, regen, detector_cls, reviewer_cls


def _context(application):
    return {
        "loan_amount": float(application.loan_amount),
        "purpose": application.get_purpose_display(),
        "decision": "denied",
    }


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
    regen_return = {**_llm_email(), "template_fallback": True}

    outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, regen_return=regen_return)

    assert outcome is None
    regen.assert_called_once()
    detector_cls.return_value.analyze.assert_not_called()
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["step_name"] == "bias_agent2_regeneration"
    assert steps[0]["result_summary"] == {
        "regenerated": False,
        "reason": "No LLM rewrite was produced (LLM unavailable or guardrails exhausted)",
    }
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()


@pytest.mark.django_db
def test_regenerated_result_fails_guardrails_returns_none(processing_denied, agent_run):
    regen_return = _rewrite(passed_guardrails=False)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, regen_return=regen_return)

    assert outcome is None
    detector_cls.return_value.analyze.assert_not_called()
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"]["regenerated"] is False
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()
    assert not BiasReport.objects.filter(agent_run=agent_run).exists()


@pytest.mark.django_db
def test_detector_flags_the_rewrite_returns_none(processing_denied, agent_run):
    still_flagged = _bias_result(score=45, flagged=True)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=_rewrite(), new_bias=still_flagged
    )

    assert outcome is None
    detector_cls.return_value.analyze.assert_called_once_with("New rewritten body", _context(processing_denied))
    reviewer_cls.return_value.review.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"]["regenerated"] is False
    assert steps[0]["result_summary"]["bias_score"] == 45
    report = BiasReport.objects.get(email=_persisted_rewrite(processing_denied))
    assert report.flagged is True
    assert report.ai_review_approved is False


@pytest.mark.django_db
def test_detector_crash_persists_no_rewrite(processing_denied, agent_run):
    """The rewrite is persisted only together with its report, after the detector
    scored it: a detector failure leaves no unscreened rewrite behind."""
    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=_rewrite(), detector_side_effect=RuntimeError("detector down")
    )

    assert outcome is None
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()
    assert steps[0]["result_summary"]["regenerated"] is False


@pytest.mark.django_db
def test_reviewer_rejects_the_rewrite_returns_none(processing_denied, agent_run):
    clean = _bias_result(score=5, flagged=False)
    rejected = _review(approved=False, confidence=0.95, reasoning="tone concerns remain")

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=_rewrite(), new_bias=clean, review=rejected
    )

    assert outcome is None
    reviewer_cls.return_value.review.assert_called_once_with("New rewritten body", clean, _context(processing_denied))
    assert len(steps) == 1
    summary = steps[0]["result_summary"]
    assert summary["regenerated"] is False
    assert summary["reviewer_approved"] is False
    report = BiasReport.objects.get(email=_persisted_rewrite(processing_denied))
    assert report.flagged is False
    assert report.ai_review_approved is False
    assert report.ai_review_reasoning == "tone concerns remain"


@pytest.mark.django_db
def test_reviewer_approves_with_low_confidence_returns_none(processing_denied, agent_run):
    clean = _bias_result(score=5, flagged=False)
    low_confidence = _review(approved=True, confidence=0.5)

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=_rewrite(), new_bias=clean, review=low_confidence
    )

    assert outcome is None
    assert len(steps) == 1
    summary = steps[0]["result_summary"]
    assert summary["regenerated"] is False
    assert summary["reviewer_approved"] is True
    assert summary["reviewer_confidence"] == 0.5
    # Below the confidence floor the gate did not approve, whatever the model said.
    assert BiasReport.objects.get(email=_persisted_rewrite(processing_denied)).ai_review_approved is False


@pytest.mark.django_db
def test_rewrite_is_held_while_the_senior_review_is_in_flight(processing_denied, agent_run):
    """If the task dies during the review, the persisted rewrite must already be
    held from the staff send paths."""
    from apps.email_engine.services.decision_email import bias_hold_reason

    seen = {}

    def _review_in_flight(body, bias, context):
        rewrite = _persisted_rewrite(processing_denied)
        seen["hold"] = bias_hold_reason(processing_denied.pk, rewrite)
        seen["approved"] = BiasReport.objects.get(email=rewrite).ai_review_approved
        return _review(approved=True, confidence=0.9)

    _run(
        processing_denied,
        agent_run,
        regen_return=_rewrite(),
        new_bias=_bias_result(score=5, flagged=False),
        review_side_effect=_review_in_flight,
    )

    assert seen["approved"] is False
    assert seen["hold"]


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
    from apps.email_engine.services.decision_email import bias_hold_reason

    result_dict = _rewrite()
    clean = _bias_result(score=5, flagged=False)
    approved = _review(approved=True, confidence=0.9, reasoning="reads well")

    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied,
        agent_run,
        email_result={**_llm_email(), "body": "Old flagged body"},
        regen_return=result_dict,
        new_bias=clean,
        review=approved,
    )

    generated = _persisted_rewrite(processing_denied)
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
    report = BiasReport.objects.get(email=generated)
    assert report.flagged is False
    assert report.ai_review_approved is True
    assert report.ai_review_reasoning == "reads well"
    assert bias_hold_reason(processing_denied.pk, generated) is None


# ---------------------------------------------------------------------------
# Time limit and API budget
# ---------------------------------------------------------------------------


def test_seconds_until_deadline_is_none_outside_a_deadline_scope():
    from apps.agents.services.step_tracker import seconds_until_deadline

    assert seconds_until_deadline() is None


def test_seconds_until_deadline_counts_down_inside_the_scope():
    from apps.agents.services.step_tracker import seconds_until_deadline

    with pipeline_deadline(100):
        left = seconds_until_deadline()
    assert 99 < left <= 100


@pytest.mark.django_db
@pytest.mark.parametrize("stage", ["generation", "detector", "review"])
def test_a_soft_time_limit_propagates_out_of_agent2(processing_denied, agent_run, stage):
    """A soft limit swallowed here would let the pipeline go on to the template
    path and escalate, leaving the application PENDING with no escalated run."""
    limit = SoftTimeLimitExceeded("soft limit")
    kwargs = {"regen_return": _rewrite(), "new_bias": _bias_result(score=5, flagged=False)}
    if stage == "generation":
        kwargs = {"regen_side_effect": limit}
    elif stage == "detector":
        kwargs["detector_side_effect"] = limit
    else:
        kwargs["review_side_effect"] = limit

    with pytest.raises(SoftTimeLimitExceeded):
        _run(processing_denied, agent_run, **kwargs)


@pytest.mark.django_db
def test_a_rewrite_cut_off_by_the_time_limit_during_review_stays_held(processing_denied, agent_run):
    from apps.email_engine.services.decision_email import bias_hold_reason

    with pytest.raises(SoftTimeLimitExceeded):
        _run(
            processing_denied,
            agent_run,
            regen_return=_rewrite(),
            new_bias=_bias_result(score=5, flagged=False),
            review_side_effect=SoftTimeLimitExceeded("soft limit"),
        )

    rewrite = _persisted_rewrite(processing_denied)
    assert BiasReport.objects.get(email=rewrite).ai_review_approved is False
    assert bias_hold_reason(processing_denied.pk, rewrite)


@pytest.mark.django_db
@override_settings(BIAS_AGENT2_MIN_SECONDS_LEFT=240)
def test_too_little_time_left_hands_over_without_calling_the_generator(processing_denied, agent_run):
    with pipeline_deadline(100):
        outcome, steps, regen, detector_cls, reviewer_cls = _run(processing_denied, agent_run, regen_return=_rewrite())

    assert outcome is None
    regen.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"] == {"regenerated": False, "reason": "Not enough time left for a rewrite"}


@pytest.mark.django_db
@override_settings(BIAS_AGENT2_MIN_SECONDS_LEFT=240)
def test_enough_time_left_runs_the_rewrite(processing_denied, agent_run):
    with pipeline_deadline(500):
        _, _, regen, _, _ = _run(processing_denied, agent_run, regen_return={**_llm_email(), "template_fallback": True})

    regen.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize("gate", [BudgetExhausted("daily cap"), CircuitOpen("breaker open")])
def test_a_closed_api_budget_hands_over_without_calling_the_generator(processing_denied, agent_run, gate):
    outcome, steps, regen, detector_cls, reviewer_cls = _run(
        processing_denied, agent_run, regen_return=_rewrite(), budget_side_effect=gate
    )

    assert outcome is None
    regen.assert_not_called()
    assert len(steps) == 1
    assert steps[0]["result_summary"] == {"regenerated": False, "reason": "API budget closed"}


# ---------------------------------------------------------------------------
# Senior reviewer call: cost and APP 8 metadata, neutral rejection wording
# ---------------------------------------------------------------------------


def _review_once(monkeypatch):
    from apps.agents.services.bias.reviewer import AIEmailReviewer

    captured = {}

    def _fake_guarded_call(client, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after the call is built")

    monkeypatch.setattr("apps.agents.services.bias.helpers.guarded_api_call", _fake_guarded_call)
    monkeypatch.setattr("apps.agents.services.bias.reviewer._make_anthropic_client", lambda: MagicMock())
    AIEmailReviewer().review(
        "BODY",
        {"score": 5, "analysis": "x", "categories": []},
        {"purpose": "home", "decision": "denied", "loan_amount": 100000},
    )
    return captured


def test_senior_review_call_carries_service_and_pii_metadata(monkeypatch):
    captured = _review_once(monkeypatch)

    assert captured["_service"] == "bias_agent2_review"
    assert captured["_pii_categories"] == ["name", "loan_amount", "credit_assessment"]


def test_senior_review_prompt_does_not_promise_a_human_review(monkeypatch):
    """In Agent 2 a rejection hands over to the template, not to a human."""
    prompt = _review_once(monkeypatch)["messages"][0]["content"]

    assert "the email will not be sent as written" in prompt
    assert "human review" not in prompt.lower()
    assert "human escalation" not in prompt.lower()


# ---------------------------------------------------------------------------
# Observability: step budget and outcome counter
# ---------------------------------------------------------------------------


def _outcome_count(outcome):
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value("bias_agent2_outcomes_total", {"outcome": outcome}) or 0.0


def test_agent2_step_has_its_own_timeout_budget():
    step = StepTracker().start_step("bias_agent2_regeneration")

    assert step["timeout_ms"] == 180_000


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("outcome", "kwargs"),
    [
        ("skipped", {"enabled": False}),
        ("handed_over_budget_closed", {"budget_side_effect": BudgetExhausted("cap")}),
        ("handed_over_no_rewrite", {"regen_return": {**_llm_email(), "template_fallback": True}}),
        ("handed_over_guardrails", {"regen_return": _rewrite(passed_guardrails=False)}),
        ("handed_over_bias_flagged", {"regen_return": _rewrite(), "new_bias": _bias_result(score=45, flagged=True)}),
        (
            "handed_over_reviewer_rejected",
            {
                "regen_return": _rewrite(),
                "new_bias": _bias_result(score=5, flagged=False),
                "review": _review(approved=False),
            },
        ),
        ("handed_over_error", {"regen_side_effect": RuntimeError("boom")}),
        (
            "sent",
            {"regen_return": _rewrite(), "new_bias": _bias_result(score=5, flagged=False), "review": _review()},
        ),
    ],
)
def test_each_agent2_outcome_is_counted(processing_denied, agent_run, outcome, kwargs):
    before = _outcome_count(outcome)

    _run(processing_denied, agent_run, **kwargs)

    assert _outcome_count(outcome) == before + 1


@pytest.mark.django_db
@override_settings(BIAS_AGENT2_MIN_SECONDS_LEFT=240)
def test_low_time_hand_over_is_counted(processing_denied, agent_run):
    before = _outcome_count("handed_over_low_time")

    with pipeline_deadline(100):
        _run(processing_denied, agent_run, regen_return=_rewrite())

    assert _outcome_count("handed_over_low_time") == before + 1


@pytest.mark.django_db
def test_the_rewrite_request_carries_the_next_best_offer(processing_denied, agent_run):
    """A denial rewrite must keep the offer the first draft was given."""
    offer = {"type": "reduced_loan", "name": "Reduced Amount Loan", "amount": 15000}

    _, _, regen, _, _ = _run(
        processing_denied,
        agent_run,
        regen_return={**_llm_email(), "template_fallback": True},
        profile_context={"nbo_offer": offer},
    )

    assert regen.call_args.kwargs["profile_context"]["nbo_offer"] == offer
