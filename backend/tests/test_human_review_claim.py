"""Human-review actions claim the escalated run under the lock.

Approve and Deny used to leave the run ESCALATED until a worker picked up the
resume, and Deny wrote "denied" onto the LoanDecision before anything checked
the application was still in review. A second reviewer (or a stale queue item
left behind by a forced re-run) could therefore overwrite a decision that had
already been acted on.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.loans.models import LoanDecision

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


class _StopAfterClaim(Exception):
    """Raised by a patched step that runs right after the resume claims the run."""


def _post_review(user, run_id, action):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(f"/api/v1/agents/review/{run_id}/", {"action": action, "note": "n"}, format="json")


@LOCMEM
@pytest.mark.django_db
def test_deny_on_a_stale_run_is_rejected_when_the_application_moved_on(
    escalated_agent_run, officer_user, django_capture_on_commit_callbacks
):
    application = escalated_agent_run.application
    application.status = "approved"  # a later re-run approved it
    application.save(update_fields=["status"])

    with (
        patch("apps.agents.services.human_review_actions.resume_pipeline_task.delay") as delay,
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        django_capture_on_commit_callbacks(execute=True),
    ):
        resp = _post_review(officer_user, escalated_agent_run.id, "deny")

    assert resp.status_code == 409, resp.data
    decision = LoanDecision.objects.get(application=application)
    assert decision.decision == "approved"
    assert decision.human_involvement != LoanDecision.HumanInvolvement.OVERRIDDEN
    delay.assert_not_called()


@LOCMEM
@pytest.mark.django_db
def test_a_second_action_on_a_claimed_run_is_rejected(
    escalated_agent_run, officer_user, django_capture_on_commit_callbacks
):
    with (
        patch("apps.agents.services.human_review_actions.resume_pipeline_task.delay") as delay,
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        django_capture_on_commit_callbacks(execute=True),
    ):
        delay.return_value = MagicMock(id="t-resume")
        first = _post_review(officer_user, escalated_agent_run.id, "approve")
        second = _post_review(officer_user, escalated_agent_run.id, "deny")

    assert first.status_code == 200, first.data
    assert second.status_code == 409, second.data
    assert delay.call_count == 1
    assert LoanDecision.objects.get(application=escalated_agent_run.application).decision == "approved"
    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == AgentRun.Status.RUNNING


@pytest.mark.django_db
def test_resume_continues_a_run_the_review_view_claimed(escalated_agent_run):
    from apps.agents.services.orchestrator import PipelineOrchestrator

    escalated_agent_run.status = AgentRun.Status.RUNNING
    escalated_agent_run.save(update_fields=["status"])

    with (
        patch(
            "apps.agents.services.context_builder.ApplicationContextBuilder.build_profile_context",
            side_effect=_StopAfterClaim,
        ),
        pytest.raises(_StopAfterClaim),
    ):
        PipelineOrchestrator().resume_after_review(str(escalated_agent_run.id), reviewer="r", note="n")


@pytest.mark.django_db
def test_resume_still_refuses_a_finished_run(escalated_agent_run):
    from apps.agents.services.orchestrator import PipelineOrchestrator

    escalated_agent_run.status = AgentRun.Status.COMPLETED
    escalated_agent_run.save(update_fields=["status"])

    with pytest.raises(ValueError, match="Cannot resume"):
        PipelineOrchestrator().resume_after_review(str(escalated_agent_run.id), reviewer="r", note="n")


@LOCMEM
@pytest.mark.django_db
def test_a_resume_that_fails_after_the_claim_returns_the_run_to_the_queue(escalated_agent_run):
    from apps.agents.tasks import resume_pipeline_task

    escalated_agent_run.status = AgentRun.Status.RUNNING  # claimed by the view
    escalated_agent_run.save(update_fields=["status"])

    with patch(
        "apps.agents.services.context_builder.ApplicationContextBuilder.build_profile_context",
        side_effect=RuntimeError("boom after claim"),
    ):
        result = resume_pipeline_task.apply(args=(str(escalated_agent_run.id),), kwargs={"action": "approve"})

    assert result.failed()
    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == AgentRun.Status.ESCALATED
    assert "boom after claim" in escalated_agent_run.error
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "review"


@LOCMEM
@pytest.mark.django_db
def test_the_sweep_returns_a_long_dead_resume_to_the_queue(escalated_agent_run):
    """A hard kill skips the task's except arm, so the beat sweep catches it."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.agents.tasks import recover_stuck_processing_applications

    AgentRun.objects.filter(pk=escalated_agent_run.pk).update(
        status=AgentRun.Status.RUNNING, updated_at=timezone.now() - timedelta(minutes=30)
    )

    recover_stuck_processing_applications()

    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == AgentRun.Status.ESCALATED


@LOCMEM
@pytest.mark.django_db
def test_the_sweep_leaves_a_live_resume_alone(escalated_agent_run):
    from apps.agents.tasks import recover_stuck_processing_applications

    AgentRun.objects.filter(pk=escalated_agent_run.pk).update(status=AgentRun.Status.RUNNING)

    recover_stuck_processing_applications()

    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == AgentRun.Status.RUNNING


@LOCMEM
@pytest.mark.django_db
def test_a_new_pipeline_supersedes_older_escalated_runs(escalated_agent_run):
    """A forced re-run or batch recheck must take the old item out of the queue."""
    from apps.agents.services.orchestrator import PipelineOrchestrator

    with (
        patch.object(PipelineOrchestrator, "_build_profile_context", side_effect=_StopAfterClaim),
        pytest.raises(_StopAfterClaim),
    ):
        PipelineOrchestrator().orchestrate(str(escalated_agent_run.application_id))

    escalated_agent_run.refresh_from_db()
    assert escalated_agent_run.status == AgentRun.Status.FAILED
    assert "superseded" in escalated_agent_run.error.lower()
