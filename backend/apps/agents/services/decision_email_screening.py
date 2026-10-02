"""Bias screening for decision emails issued outside the orchestrator.

The orchestrator and the human-review resume bias-check every decision email
before it is sent. The standalone issuance paths (``generate_email_task`` and
the decision review overturn, which goes through it) used to generate and send
with no bias check at all, so an LLM-written email the pipeline would have
withheld reached the customer.

``screen_and_deliver_decision_email`` runs the same sequence for them: bias
check, then the template as a replacement for a flagged email, then delivery
of whatever checked clean. Anything else is held: the draft stays unsent with
its flagged bias report, which ``bias_hold_reason`` already refuses to send.

The decision is already on record when these paths run, so a hold does not
move the application into the review queue (the review queue resumes REVIEW
applications only). The screening is recorded on its own AgentRun, because a
BiasReport belongs to a run.
"""

import logging
import time

from django.conf import settings

from apps.agents.models import AgentRun
from apps.email_engine.services.decision_email import deliver_decision_email
from apps.loans.models import AuditLog

from .bias.core import BiasDetector
from .bias.thresholds import is_severe
from .bias_records import bias_context, save_bias_report
from .email_pipeline import replace_flagged_email
from .step_tracker import StepTracker

logger = logging.getLogger("agents.decision_email_screening")


def _bias_failure_mode():
    mode = getattr(settings, "BIAS_FAILURE_MODE", "block").lower()
    return mode if mode in ("block", "warn", "off") else "block"


def screen_and_deliver_decision_email(application, decision, email_result, generated_email, *, profile_context=None):
    """Bias-check a persisted decision email and send it, its replacement, or nothing.

    ``email_result`` is the generator result for ``generated_email`` (only its
    ``body``, ``passed_guardrails`` and ``template_fallback`` are read).
    Returns ``{"sent": bool, "held_reason": str|None, "generated_email": ...,
    "agent_run": AgentRun|None}``; ``generated_email`` is the email that was
    sent or held, which is the template when it replaced a flagged email.
    Delivery exceptions propagate (the Celery task retries infrastructure
    errors), after the run is marked failed.
    """
    outcome = {"sent": False, "held_reason": None, "generated_email": generated_email, "agent_run": None}
    if not email_result.get("passed_guardrails"):
        return outcome  # deliver_decision_email would refuse it anyway

    tracker = StepTracker()
    start_time = time.time()
    agent_run = AgentRun.objects.create(application=application, status=AgentRun.Status.RUNNING)
    outcome["agent_run"] = agent_run
    steps = []
    try:
        held_reason = None
        step = tracker.start_step("bias_check")
        detector = BiasDetector()
        try:
            bias_result = detector.analyze(email_result["body"], bias_context(application, decision))
            save_bias_report(agent_run, generated_email, bias_result)
        except Exception as exc:
            steps.append(tracker.fail_step(step, str(exc), failure_category="transient"))
            mode = _bias_failure_mode()
            logger.error("Application %s: bias check failed (%s): %s", application.pk, mode, exc)
            if mode == "block":
                held_reason = f"Bias check unavailable ({exc})"
        else:
            steps.append(
                tracker.complete_step(
                    step, result_summary={"bias_score": bias_result["score"], "flagged": bias_result["flagged"]}
                )
            )
            review_threshold = getattr(settings, "BIAS_THRESHOLD_REVIEW", 60)
            if is_severe(bias_result["score"], review_threshold):
                held_reason = f"Severe bias detected (score {bias_result['score']} >= {review_threshold})"
            elif bias_result["flagged"]:
                # The flagged LLM text never ships: the template replaces it
                # and is sent only if its own bias check is clean.
                try:
                    replacement = replace_flagged_email(
                        application,
                        agent_run,
                        decision,
                        email_result,
                        generated_email,
                        bias_result,
                        detector,
                        tracker,
                        steps,
                        profile_context=profile_context,
                    )
                except Exception as exc:
                    logger.error("Application %s: bias re-check of the replacement failed: %s", application.pk, exc)
                    replacement = None
                if replacement is None or replacement[2].get("flagged"):
                    held_reason = f"Bias flagged (score {bias_result['score']}) and no clean replacement email"
                else:
                    generated_email = replacement[1]
                    outcome["generated_email"] = generated_email

        step = tracker.start_step("email_delivery")
        if held_reason:
            steps.append(tracker.complete_step(step, result_summary={"sent": False, "reason": held_reason}))
            outcome["held_reason"] = held_reason
            logger.warning("Application %s: %s decision email held: %s", application.pk, decision, held_reason)
            AuditLog.objects.create(
                action="decision_email_held",
                resource_type="GeneratedEmail",
                resource_id=str(generated_email.id),
                details={"decision": decision, "reason": held_reason, "agent_run_id": str(agent_run.id)},
            )
        else:
            delivery = deliver_decision_email(generated_email)
            outcome["sent"] = delivery["sent"] or delivery["already_sent"]
            if outcome["sent"]:
                steps.append(
                    tracker.complete_step(step, result_summary={"sent": True, "recipient": delivery["recipient"]})
                )
            elif delivery["recipient"] is None:
                steps.append(
                    tracker.complete_step(step, result_summary={"sent": False, "reason": "No recipient email"})
                )
            else:
                steps.append(tracker.fail_step(step, delivery["error"] or "Send failed"))
    except BaseException as exc:
        agent_run.status = AgentRun.Status.FAILED
        agent_run.error = f"Decision email screening failed: {exc}"
        agent_run.steps = steps
        agent_run.total_time_ms = int((time.time() - start_time) * 1000)
        agent_run.save()
        raise

    # Completed either way; a hold is recorded on the run like a guardrail withhold.
    agent_run.status = AgentRun.Status.COMPLETED
    agent_run.error = f"Decision email held: {outcome['held_reason']}" if outcome["held_reason"] else ""
    agent_run.steps = steps
    agent_run.total_time_ms = int((time.time() - start_time) * 1000)
    agent_run.save()
    return outcome
