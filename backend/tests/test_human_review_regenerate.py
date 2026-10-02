"""I1 — human-review "Regenerate" must run a fresh pipeline.

Previously the view marked the escalated run COMPLETED and dispatched
orchestrate_pipeline_task without force. The task's idempotency guard saw that
COMPLETED run, replayed the stored ML decision via restore_status_from_decision
and returned "already_completed": the application was decided with no email,
no bias check and no new run. This test runs the real task body.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.agents.tasks import orchestrate_pipeline_task

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


@LOCMEM
@pytest.mark.django_db
def test_regenerate_runs_a_new_pipeline(escalated_agent_run, officer_user, django_capture_on_commit_callbacks):
    app_id = str(escalated_agent_run.application_id)
    orchestrate_calls = []

    def _fake_orchestrate(self, application_id):
        orchestrate_calls.append(str(application_id))
        return MagicMock(id="new-run", status="completed", total_time_ms=1, steps=[])

    def _run_task_body(*args, **kwargs):
        # Execute the real task body synchronously instead of queueing it.
        return orchestrate_pipeline_task.apply(args=args, kwargs=kwargs)

    client = APIClient()
    client.force_authenticate(user=officer_user)
    with (
        patch("apps.agents.services.orchestrator.PipelineOrchestrator.orchestrate", _fake_orchestrate),
        patch(
            "apps.agents.services.orchestrator.PipelineOrchestrator.restore_status_from_decision",
            side_effect=AssertionError("regenerate must not replay the stored decision"),
        ),
        patch("apps.agents.views.orchestrate_pipeline_task.delay", side_effect=_run_task_body),
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        django_capture_on_commit_callbacks(execute=True),
    ):
        resp = client.post(
            f"/api/v1/agents/review/{escalated_agent_run.id}/",
            {"action": "regenerate", "note": "re-run please"},
            format="json",
        )

    assert resp.status_code == 200, resp.data
    assert orchestrate_calls == [app_id], "a fresh pipeline must run"

    escalated_agent_run.refresh_from_db()
    # The superseded run must not count as a COMPLETED run that owns the
    # application (it would short-circuit the idempotency guard and stop
    # stuck-processing cleanup if the new run fails).
    assert escalated_agent_run.status != AgentRun.Status.COMPLETED


@LOCMEM
@pytest.mark.django_db
def test_regenerate_dispatches_with_force(escalated_agent_run, officer_user, django_capture_on_commit_callbacks):
    client = APIClient()
    client.force_authenticate(user=officer_user)
    with (
        patch("apps.agents.views.orchestrate_pipeline_task.delay") as delay,
        patch("apps.agents.views.OrchestrationThrottle.allow_request", return_value=True),
        django_capture_on_commit_callbacks(execute=True),
    ):
        delay.return_value = MagicMock(id="t-regen")
        resp = client.post(
            f"/api/v1/agents/review/{escalated_agent_run.id}/",
            {"action": "regenerate"},
            format="json",
        )
    assert resp.status_code == 200
    delay.assert_called_once_with(str(escalated_agent_run.application_id), force=True)
