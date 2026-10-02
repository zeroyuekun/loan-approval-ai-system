"""Officer actions on an escalated pipeline run: approve, deny or regenerate.

Concurrency and consistency guarantees:
- select_for_update() to prevent race conditions between concurrent reviewers
- Audit log inside transaction to prevent ghost entries on DB failure
- LoanDecision updated on human deny to maintain consistency
- Task dispatched via on_commit() to ensure DB state is committed first
- update_fields on save() to prevent lost-update on concurrent writes
"""

from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import status

from apps.agents.models import AgentRun
from apps.agents.tasks import orchestrate_pipeline_task, resume_pipeline_task
from apps.loans.models import AuditLog, LoanApplication, LoanDecision

logger = logging.getLogger(__name__)

HUMAN_REVIEW_ACTIONS = ("approve", "deny", "regenerate")


class HumanReviewRejected(Exception):
    """The action cannot be applied; carries the HTTP status the view returns."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def apply_human_review_action(run_id, *, action: str, user, note: str, ip_address) -> dict:
    """Apply ``action`` to the escalated run ``run_id`` on behalf of ``user``.

    Returns the response payload; raises HumanReviewRejected when the run is
    missing, not escalated, owned by the reviewer, or its application has
    moved on.
    """
    reviewer_note = note

    # Acquire row lock to prevent two reviewers acting on the same run
    with transaction.atomic():
        try:
            agent_run = AgentRun.objects.select_for_update().get(pk=run_id)
        except AgentRun.DoesNotExist as exc:
            raise HumanReviewRejected("Agent run not found", status.HTTP_404_NOT_FOUND) from exc

        if agent_run.status != AgentRun.Status.ESCALATED:
            raise HumanReviewRejected(
                f"Agent run is not escalated (current status: {agent_run.status})",
                status.HTTP_409_CONFLICT,
            )

        # Staff can also be borrowers; nobody reviews their own application.
        if agent_run.application.applicant_id == user.pk:
            raise HumanReviewRejected("You cannot review a run for your own application.", status.HTTP_403_FORBIDDEN)

        # A run left escalated by an older pipeline must not act on an
        # application a later run has already decided.
        application_status = (
            LoanApplication.objects.select_for_update()
            .values_list("status", flat=True)
            .get(pk=agent_run.application_id)
        )
        if application_status != LoanApplication.Status.REVIEW:
            raise HumanReviewRejected(
                f"Application is no longer in review (current status: {application_status})",
                status.HTTP_409_CONFLICT,
            )

        review_step = {
            "step_name": "human_review_decision",
            "status": "completed",
            "result_summary": {
                "action": action,
                "reviewer": user.username,
                "note": reviewer_note,
            },
        }

        if action == "approve":
            # Claim the run under the lock: it leaves the queue, and a second
            # action on it gets the 409 above instead of racing this one.
            agent_run.steps = agent_run.steps + [review_step]
            agent_run.status = AgentRun.Status.RUNNING
            agent_run.save(update_fields=["steps", "status", "updated_at"])

            # Audit log inside the transaction
            AuditLog.objects.create(
                user=user,
                action="human_review_approve",
                resource_type="AgentRun",
                resource_id=str(run_id),
                details={"note": reviewer_note},
                ip_address=ip_address,
            )

            # Dispatch task after commit so it sees the updated state
            task_holder = {}

            def _dispatch_resume():
                task_holder["task"] = resume_pipeline_task.delay(
                    str(run_id),
                    reviewer=user.username,
                    note=reviewer_note,
                )

            transaction.on_commit(_dispatch_resume)

        elif action == "deny":
            application = agent_run.application
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
                AuditLog.objects.create(
                    user=user,
                    action="human_review_deny",
                    resource_type="AgentRun",
                    resource_id=str(run_id),
                    details={"note": reviewer_note, "application_id": str(application.id)},
                    ip_address=ip_address,
                )
                return {"status": "application_denied_by_reviewer", "action": "deny"}

            # Record the reviewer's denial on the decision, then resume the
            # run exactly as an approval does: the resume generates the
            # denial email, runs the bias pre-screen/check on it, delivers
            # it once, and only then moves the application to denied. A
            # flagged denial email is withheld and the run re-escalates.
            original_decision = decision.decision
            decision.decision = "denied"
            decision.reasoning = f"Human review override by {user.username}: {reviewer_note}"
            update_fields = ["decision", "reasoning"]
            if original_decision != "denied" and decision.mark_human(LoanDecision.HumanInvolvement.OVERRIDDEN):
                update_fields.append("human_involvement")
            decision.save(update_fields=update_fields)

            agent_run.steps = agent_run.steps + [review_step]
            agent_run.status = AgentRun.Status.RUNNING  # claimed, as for approve
            agent_run.save(update_fields=["steps", "status", "updated_at"])

            AuditLog.objects.create(
                user=user,
                action="human_review_deny",
                resource_type="AgentRun",
                resource_id=str(run_id),
                details={
                    "note": reviewer_note,
                    "application_id": str(application.id),
                    "original_decision": original_decision,
                },
                ip_address=ip_address,
            )

            task_holder = {}

            def _dispatch_deny():
                task_holder["task"] = resume_pipeline_task.delay(
                    str(run_id),
                    reviewer=user.username,
                    note=reviewer_note,
                    action="deny",
                )

            transaction.on_commit(_dispatch_deny)

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
            application = agent_run.application
            application.transition_to("pending", user=user, details={"reason": "human_review_regenerate"})

            AuditLog.objects.create(
                user=user,
                action="human_review_regenerate",
                resource_type="AgentRun",
                resource_id=str(run_id),
                details={"note": reviewer_note, "application_id": str(agent_run.application_id)},
                ip_address=ip_address,
            )

            # Dispatch new pipeline AFTER commit
            task_holder = {}

            def _dispatch_regenerate():
                # force=True: an earlier COMPLETED run for this application
                # must not short-circuit the reviewer's regenerate request.
                task_holder["task"] = orchestrate_pipeline_task.delay(str(agent_run.application_id), force=True)

            transaction.on_commit(_dispatch_regenerate)

    # For approve/regenerate, return task info after transaction commits
    task = task_holder.get("task")
    status_by_action = {
        "approve": "review_approved_pipeline_resuming",
        "deny": "review_denied_pipeline_resuming",
        "regenerate": "regeneration_queued",
    }
    return {
        "task_id": getattr(task, "id", None),
        "status": status_by_action[action],
        "action": action,
    }
