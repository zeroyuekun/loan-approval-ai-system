"""Officer actions on an escalated pipeline run: approve, deny or regenerate.

Concurrency and consistency guarantees:
- select_for_update() on the run, then the application, to prevent races
  between concurrent reviewers; every check and write uses the locked rows
- Audit log inside transaction to prevent ghost entries on DB failure
- LoanDecision updated on human deny to maintain consistency
- Task dispatched via on_commit() to ensure DB state is committed first
- update_fields on save() to prevent lost-update on concurrent writes
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.agents.models import AgentRun
from apps.agents.tasks import orchestrate_pipeline_task, resume_pipeline_task
from apps.loans.models import AuditLog, LoanApplication, LoanDecision
from apps.loans.services.reviewer_independence import assert_independent_reviewer

logger = logging.getLogger(__name__)

HUMAN_REVIEW_ACTIONS = ("approve", "deny", "regenerate")

_STATUS_BY_ACTION = {
    "approve": "review_approved_pipeline_resuming",
    "deny": "review_denied_pipeline_resuming",
    "regenerate": "regeneration_queued",
}


class HumanReviewRejected(Exception):
    """The action cannot be applied."""


class ReviewRunNotFound(HumanReviewRejected):
    """There is no agent run with that id."""


class ReviewConflict(HumanReviewRejected):
    """The run or its application is no longer waiting for this review."""


def apply_human_review_action(run_id, *, action: str, user, note: str, ip_address) -> dict:
    """Apply ``action`` to the escalated run ``run_id`` on behalf of ``user``.

    Returns the response payload. Raises ReviewRunNotFound, ReviewConflict
    (the run is not escalated or its application has moved on) or
    ReviewerNotIndependent, a PermissionDenied (the reviewer applied for the
    loan).
    """
    dispatched = {}

    def _dispatch_after_commit(task, *args, **kwargs):
        transaction.on_commit(lambda: dispatched.update(task=task.delay(*args, **kwargs)))

    with transaction.atomic():
        try:
            agent_run = AgentRun.objects.select_for_update().get(pk=run_id)
        except AgentRun.DoesNotExist as exc:
            raise ReviewRunNotFound("Agent run not found") from exc

        if agent_run.status != AgentRun.Status.ESCALATED:
            raise ReviewConflict(f"Agent run is not escalated (current status: {agent_run.status})")

        application = LoanApplication.objects.select_for_update().get(pk=agent_run.application_id)
        assert_independent_reviewer(user, application)

        # A run left escalated by an older pipeline must not act on an
        # application a later run has already decided.
        if application.status != LoanApplication.Status.REVIEW:
            raise ReviewConflict(f"Application is no longer in review (current status: {application.status})")

        review_step = {
            "step_name": "human_review_decision",
            "status": "completed",
            "result_summary": {"action": action, "reviewer": user.username, "note": note},
        }
        audit_details = {"note": note, "application_id": str(application.id)}

        if action == "approve":
            # Claim the run under the lock: it leaves the queue, and a second
            # action on it gets the 409 above instead of racing this one.
            agent_run.steps = agent_run.steps + [review_step]
            agent_run.status = AgentRun.Status.RUNNING
            agent_run.save(update_fields=["steps", "status", "updated_at"])
            _dispatch_after_commit(
                resume_pipeline_task, str(run_id), reviewer=user.username, note=note, action=action, reviewer_id=user.pk
            )

        elif action == "deny":
            decision = LoanDecision.objects.select_for_update().filter(application=application).first()
            if decision is None:
                # Nothing on record to announce: deny directly (no notice
                # can be generated without a LoanDecision).
                logger.info(
                    "human_review_deny_no_decision_record",
                    extra={
                        "agent_run_id": str(run_id),
                        "application_id": str(application.id),
                        "reviewer": user.username,
                    },
                )
                application.transition_to("denied", user=user, details={"reason": "human_review_deny"})
                agent_run.steps = agent_run.steps + [review_step]
                agent_run.status = AgentRun.Status.COMPLETED
                agent_run.total_time_ms = agent_run.total_time_ms or 0
                agent_run.save(update_fields=["steps", "status", "total_time_ms", "updated_at"])
                _audit(user, action, run_id, audit_details, ip_address)
                return {"status": "application_denied_by_reviewer", "action": action}

            # Record the reviewer's denial on the decision, then resume the
            # run exactly as an approval does: the resume generates the
            # denial email, runs the bias pre-screen/check on it, delivers
            # it once, and only then moves the application to denied. A
            # flagged denial email is withheld and the run re-escalates.
            original_decision = decision.decision
            decision.decision = "denied"
            decision.reasoning = f"Human review override by {user.username}: {note}"
            update_fields = ["decision", "reasoning"]
            if original_decision != "denied" and decision.mark_human(LoanDecision.HumanInvolvement.OVERRIDDEN):
                update_fields.append("human_involvement")
            decision.save(update_fields=update_fields)

            agent_run.steps = agent_run.steps + [review_step]
            agent_run.status = AgentRun.Status.RUNNING  # claimed, as for approve
            agent_run.save(update_fields=["steps", "status", "updated_at"])
            audit_details["original_decision"] = original_decision
            _dispatch_after_commit(
                resume_pipeline_task, str(run_id), reviewer=user.username, note=note, action=action, reviewer_id=user.pk
            )

        else:  # regenerate
            # Close the old run as superseded, NOT completed: a COMPLETED run
            # "owns" the application, so the orchestrate task's idempotency
            # guard would replay the stored decision instead of running, and
            # stuck-processing cleanup would skip the app if the new run died.
            agent_run.steps = agent_run.steps + [review_step]
            agent_run.status = AgentRun.Status.FAILED
            agent_run.error = f"Superseded by human-review regenerate ({user.username})"
            agent_run.total_time_ms = agent_run.total_time_ms or 0
            agent_run.save(update_fields=["steps", "status", "error", "total_time_ms", "updated_at"])

            # Reset application to pending so the new pipeline can process it
            application.transition_to("pending", user=user, details={"reason": "human_review_regenerate"})
            # force=True: an earlier COMPLETED run for this application must
            # not short-circuit the reviewer's regenerate request.
            _dispatch_after_commit(orchestrate_pipeline_task, str(application.id), force=True)

        _audit(user, action, run_id, audit_details, ip_address)

    return {
        "task_id": getattr(dispatched.get("task"), "id", None),
        "status": _STATUS_BY_ACTION[action],
        "action": action,
    }


def _audit(user, action, run_id, details, ip_address):
    AuditLog.objects.create(
        user=user,
        action=f"human_review_{action}",
        resource_type="AgentRun",
        resource_id=str(run_id),
        details=details,
        ip_address=ip_address,
    )
