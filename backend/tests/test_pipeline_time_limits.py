"""I9 — a time-limited orchestrate task must not leave the application in PROCESSING.

SoftTimeLimitExceeded subclasses Exception, so the broad except arms in every
pipeline step swallowed it and the run carried on until the hard kill. The
hard kill does not run Task.on_failure, and on_failure only cleaned up when
retries were exhausted, so the application stayed in PROCESSING.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.agents.models import AgentRun
from apps.agents.services.step_tracker import StepTracker, pipeline_deadline
from apps.loans.models import LoanApplication

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def test_step_cannot_start_after_the_deadline():
    tracker = StepTracker()
    with pipeline_deadline(0):
        with pytest.raises(SoftTimeLimitExceeded):
            tracker.start_step("bias_check")
    tracker.start_step("bias_check")  # no deadline outside the scope


def test_fail_step_does_not_swallow_a_soft_time_limit():
    tracker = StepTracker()
    step = tracker.start_step("email_generation")
    with pytest.raises(SoftTimeLimitExceeded):
        try:
            raise SoftTimeLimitExceeded()
        except Exception as e:  # the shape of every pipeline step handler
            tracker.fail_step(step, str(e))


@LOCMEM
@pytest.mark.django_db
def test_soft_limit_in_a_step_reaches_the_task_and_resets_the_application(sample_application):
    """Bias step hits the soft limit -> task cleanup moves the app out of PROCESSING."""
    from apps.agents.tasks import orchestrate_pipeline_task

    def _processing_then_timeout(self, application_id):
        app = LoanApplication.objects.get(pk=application_id)
        app.transition_to("processing", details={"source": "test"})
        AgentRun.objects.create(application=app, status=AgentRun.Status.RUNNING, steps=[])
        tracker = StepTracker()
        step = tracker.start_step("bias_check")
        try:
            raise SoftTimeLimitExceeded()
        except Exception as e:
            tracker.fail_step(step, str(e))  # a step handler that used to swallow it
        raise AssertionError("pipeline kept running past the soft time limit")

    with patch("apps.agents.services.orchestrator.PipelineOrchestrator.orchestrate", _processing_then_timeout):
        result = orchestrate_pipeline_task.apply(args=(str(sample_application.pk),))

    assert isinstance(result.result, SoftTimeLimitExceeded)
    sample_application.refresh_from_db()
    assert sample_application.status == LoanApplication.Status.PENDING
    assert not AgentRun.objects.filter(application=sample_application, status=AgentRun.Status.RUNNING).exists()


def _stuck(application, minutes_ago):
    LoanApplication.objects.filter(pk=application.pk).update(
        status=LoanApplication.Status.PROCESSING, updated_at=timezone.now() - timedelta(minutes=minutes_ago)
    )
    AgentRun.objects.create(application=application, status=AgentRun.Status.RUNNING, steps=[])


@LOCMEM
@pytest.mark.django_db
def test_sweep_resets_application_left_processing_by_a_hard_kill(sample_application):
    from apps.agents.tasks import recover_stuck_processing_applications

    _stuck(sample_application, minutes_ago=30)
    result = recover_stuck_processing_applications()

    sample_application.refresh_from_db()
    # Re-runnable PENDING, not the bias-only human review queue.
    assert sample_application.status == LoanApplication.Status.PENDING
    assert result["recovered"] == [str(sample_application.pk)]
    assert AgentRun.objects.get(application=sample_application).status == AgentRun.Status.FAILED


@LOCMEM
@pytest.mark.django_db
def test_sweep_leaves_a_live_run_alone(sample_application):
    from apps.agents.tasks import _lock_key, recover_stuck_processing_applications

    _stuck(sample_application, minutes_ago=2)  # still inside the time limit
    recover_stuck_processing_applications()
    sample_application.refresh_from_db()
    assert sample_application.status == LoanApplication.Status.PROCESSING

    LoanApplication.objects.filter(pk=sample_application.pk).update(updated_at=timezone.now() - timedelta(minutes=30))
    cache.set(_lock_key(sample_application.pk), "live-task", 600)  # a task still holds the lock
    recover_stuck_processing_applications()
    sample_application.refresh_from_db()
    assert sample_application.status == LoanApplication.Status.PROCESSING


def test_sweep_is_scheduled():
    from config.celery import app

    tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert "apps.agents.tasks.recover_stuck_processing_applications" in tasks
