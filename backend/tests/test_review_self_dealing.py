"""Staff cannot act as the reviewer on their own loan application.

An officer can also be a borrower. The human-review queue must not let them
approve, deny or regenerate an escalated run for an application they applied
for themselves.
"""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.loans.models import AuditLog
from tests.conftest import use_locmem_cache


@use_locmem_cache
@pytest.mark.django_db
@pytest.mark.parametrize("action", ["approve", "deny", "regenerate"])
def test_officer_cannot_review_a_run_for_their_own_application(
    escalated_agent_run, officer_user, django_capture_on_commit_callbacks, action
):
    application = escalated_agent_run.application
    application.applicant = officer_user
    application.save(update_fields=["applicant"])

    client = APIClient()
    client.force_authenticate(user=officer_user)
    with (
        patch("apps.agents.tasks.resume_pipeline_task.delay") as resume,
        patch("apps.agents.tasks.orchestrate_pipeline_task.delay") as orchestrate,
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        django_capture_on_commit_callbacks(execute=True),
    ):
        resp = client.post(f"/api/v1/agents/review/{escalated_agent_run.id}/", {"action": action}, format="json")

    assert resp.status_code == 403, resp.data
    escalated_agent_run.refresh_from_db()
    application.refresh_from_db()
    assert escalated_agent_run.status == AgentRun.Status.ESCALATED
    assert application.status == "review"
    assert not AuditLog.objects.filter(action__startswith="human_review_").exists()
    resume.assert_not_called()
    orchestrate.assert_not_called()
