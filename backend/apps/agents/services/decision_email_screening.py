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
applications only).

A BiasReport belongs to a run. The screening's reports go on the
application's latest run (the pipeline or review run that reached the
decision), whose status is left alone, and the screening is appended to its
steps as one ``decision_email_reissue`` step. A run of its own would become
the application's latest run: the Pipeline tab, the run list, the SLA stats
and the "latest run" idempotency checks would all read a stub. Only an
application with no run at all gets one, completed when the screening ends.
"""

import logging
import time

from django.db import transaction

from apps.agents.models import AgentRun
from apps.email_engine.services.decision_email import deliver_decision_email
from apps.loans.models import AuditLog

from .bias.core import BiasDetector
from .email_pipeline import screen_bias
from .step_tracker import StepTracker

logger = logging.getLogger("agents.decision_email_screening")


REISSUE_STEP = "decision_email_reissue"


def screen_and_deliver_decision_email(application, decision, email_result, generated_email, *, profile_context=None):
    """Bias-check a persisted decision email and send it, its replacement, or nothing.

    ``email_result`` is the generator result for ``generated_email`` (only its
    ``body``, ``passed_guardrails`` and ``template_fallback`` are read).
    Returns ``{"sent": bool, "held_reason": str|None, "generated_email": ...,
    "agent_run": AgentRun|None}``; ``generated_email`` is the email that was
    sent or held, which is the template when it replaced a flagged email, and
    ``agent_run`` is the run the screening was recorded on. Delivery
    exceptions propagate (the Celery task retries infrastructure errors),
    after the screening is recorded as failed.
    """
    outcome = {"sent": False, "held_reason": None, "generated_email": generated_email, "agent_run": None}
    if not email_result.get("passed_guardrails"):
        return outcome  # deliver_decision_email would refuse it anyway

    tracker = StepTracker()
    start_time = time.time()
    agent_run = AgentRun.objects.latest_for(application.pk)
    own_run = agent_run is None
    if own_run:
        agent_run = AgentRun.objects.create(application=application, status=AgentRun.Status.RUNNING)
    outcome["agent_run"] = agent_run
    reissue = tracker.start_step(REISSUE_STEP)
    steps = []
    try:
        screening = screen_bias(
            application,
            agent_run,
            decision,
            email_result,
            generated_email,
            detector_class=BiasDetector,
            tracker=tracker,
            steps=steps,
            profile_context=profile_context,
        )
        generated_email = outcome["generated_email"] = screening.generated_email
        held_reason = outcome["held_reason"] = screening.held_reason

        step = tracker.start_step("email_delivery")
        if held_reason:
            steps.append(tracker.complete_step(step, result_summary={"sent": False, "reason": held_reason}))
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
            steps.append(tracker.record_delivery(step, delivery))
    except BaseException as exc:
        if own_run:
            _close_own_run(
                agent_run, steps, start_time, AgentRun.Status.FAILED, f"Decision email screening failed: {exc}"
            )
        else:
            _append_step(agent_run, StepTracker.post_decision_failure_step(REISSUE_STEP, exc))
        raise

    if own_run:
        # Completed either way; a hold is recorded on the run like a guardrail withhold.
        held = outcome["held_reason"]
        _close_own_run(
            agent_run, steps, start_time, AgentRun.Status.COMPLETED, f"Decision email held: {held}" if held else ""
        )
    else:
        _append_step(
            agent_run,
            tracker.complete_step(
                reissue,
                result_summary={
                    "decision": decision,
                    "sent": outcome["sent"],
                    "reason": outcome["held_reason"],
                    "template_fallback": outcome["generated_email"].template_fallback,
                    "steps": [{"step_name": s["step_name"], "status": s["status"]} for s in steps],
                },
            ),
        )
    return outcome


def _close_own_run(agent_run, steps, start_time, status, error):
    """Finish the run the screening created for an application that had none."""
    agent_run.status = status
    agent_run.error = error
    agent_run.steps = steps
    agent_run.total_time_ms = int((time.time() - start_time) * 1000)
    agent_run.save()


def _append_step(agent_run, step):
    """Add the screening to an existing run's steps under a row lock, leaving its status alone."""
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=agent_run.pk)
        locked.steps = [*(locked.steps or []), step]
        locked.save(update_fields=["steps", "updated_at"])
    agent_run.steps = locked.steps
