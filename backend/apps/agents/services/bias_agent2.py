"""Agent 2: rewrite a moderate-band bias-flagged decision email and check it more strictly.

The first bias check flagged the email but scored it below the human-review
threshold. Agent 2 asks the email generator for a new draft with the findings
as feedback, then requires two independent passes before the new draft may be
sent: the bias detector must not flag it, and the senior compliance reviewer
(a stronger model with a different mandate) must approve it with confidence.
Anything else hands over to the deterministic template path, so Agent 2 can
only replace an email with one that passed more checks, never weaken the flow.
"""

import logging

from django.conf import settings

from apps.email_engine.services.decision_email import regenerate_decision_email

from .bias.reviewer import AIEmailReviewer
from .bias_detector import BiasDetector
from .bias_records import bias_context, save_bias_report

logger = logging.getLogger("agents.orchestrator")

STEP_NAME = "bias_agent2_regeneration"


def _feedback(bias_result):
    categories = ", ".join(bias_result.get("categories") or []) or "unspecified"
    return f"Flagged categories: {categories}. Reviewer analysis: {bias_result.get('analysis', '')}"


def run_agent2(
    application, agent_run, decision, email_result, bias_result, *, confidence, profile_context, tracker, steps
):
    """Return ``(email_result, generated_email, bias_result)`` to send, or None to hand over."""
    if not getattr(settings, "BIAS_AGENT2_ENABLED", True) or email_result.get("template_fallback"):
        return None

    step = tracker.start_step(STEP_NAME)

    def hand_over(reason, **extra):
        steps.append(tracker.complete_step(step, result_summary={"regenerated": False, "reason": reason, **extra}))
        logger.info("Application %s: Agent 2 handed over to the template path: %s", application.pk, reason)
        return None

    try:
        result, generated_email = regenerate_decision_email(
            application,
            decision,
            confidence=confidence,
            profile_context=profile_context,
            bias_feedback=_feedback(bias_result),
        )
        if generated_email is None:
            return hand_over("The LLM was unavailable, so no rewrite was written")
        if not result.get("passed_guardrails"):
            return hand_over("The rewrite failed its guardrails")

        context = bias_context(application, decision)
        new_bias = BiasDetector().analyze(result["body"], context)
        save_bias_report(agent_run, generated_email, new_bias)
        if new_bias.get("flagged"):
            return hand_over("The bias check flagged the rewrite", bias_score=new_bias.get("score"))

        review = AIEmailReviewer().review(result["body"], new_bias, context)
        min_confidence = getattr(settings, "BIAS_AGENT2_MIN_REVIEWER_CONFIDENCE", 0.70)
        approved = bool(review.get("approved")) and float(review.get("confidence") or 0.0) >= min_confidence
        if not approved:
            return hand_over(
                "The senior reviewer did not approve the rewrite",
                bias_score=new_bias.get("score"),
                reviewer_approved=bool(review.get("approved")),
                reviewer_confidence=review.get("confidence"),
            )
    except Exception as exc:  # noqa: BLE001 - every failure hands over to the template path
        logger.warning("Application %s: Agent 2 failed: %s", application.pk, exc)
        return hand_over(f"Agent 2 failed: {type(exc).__name__}")

    steps.append(
        tracker.complete_step(
            step,
            result_summary={
                "regenerated": True,
                "previous_score": bias_result.get("score"),
                "bias_score": new_bias.get("score"),
                "flagged": False,
                "reviewer_approved": True,
                "reviewer_confidence": review.get("confidence"),
            },
        )
    )
    return result, generated_email, new_bias
