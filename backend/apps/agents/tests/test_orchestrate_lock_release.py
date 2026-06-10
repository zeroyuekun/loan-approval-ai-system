"""Fix-4 regression guard: dedup lock must be released on terminal failure.

Before the fix: when autoretry_for exhausted all retries, Celery called
on_failure but the base Task.on_failure did nothing about the dedup lock,
leaving it held for the full TTL (~600 s).

After the fix: _OrchestrateTask.on_failure releases the lock when
self.request.retries >= self.max_retries (terminal failure), while keeping
the lock alive DURING retries (M22 safety).

Strategy: we test the lock-management logic in isolation by calling
_OrchestrateTask.on_failure as an unbound method with a duck-typed self
object (not a real Task instance — Celery's Task.request is a property that
requires real Celery context), and patch Task.on_failure so super() succeeds.
"""

from unittest.mock import MagicMock, patch

from celery import Task
from django.test import override_settings

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


class _FakeSelf:
    """Minimal duck-type that satisfies _OrchestrateTask.on_failure attribute accesses."""

    def __init__(self, retries, max_retries):
        self.request = MagicMock()
        self.request.retries = retries
        self.max_retries = max_retries


def _invoke_on_failure(retries, max_retries, args, kwargs):
    """Call the lock-management logic inside _OrchestrateTask.on_failure.

    Patches Task.on_failure so the super() call succeeds with a non-real-Task
    self object.
    """
    from apps.agents.tasks import _OrchestrateTask

    fake_self = _FakeSelf(retries, max_retries)

    with patch.object(Task, "on_failure"):  # neutralise super().on_failure
        _OrchestrateTask.on_failure(
            fake_self,
            exc=ConnectionError("error"),
            task_id="task-test",
            args=args,
            kwargs=kwargs,
            einfo=None,
        )


class TestOrchestrateTaskOnFailure:
    """Unit-test _OrchestrateTask.on_failure lock-management logic."""

    @CACHE_OVERRIDE
    def test_lock_released_on_terminal_failure(self):
        """Terminal failure (retries == max_retries) must delete the lock."""
        from django.core.cache import cache

        app_id = "TerminalApp-001"
        lock_key = f"orchestrate_lock:{app_id}"

        cache.add(lock_key, "task-abc", 600)
        assert cache.get(lock_key) is not None, "Lock should be set before on_failure"

        _invoke_on_failure(retries=3, max_retries=3, args=[app_id], kwargs={})

        assert cache.get(lock_key) is None, "Dedup lock must be released after max_retries exhausted"

    @CACHE_OVERRIDE
    def test_lock_kept_during_retry(self):
        """Mid-retry failure (retries < max_retries) must NOT release the lock."""
        from django.core.cache import cache

        app_id = "RetryApp-001"
        lock_key = f"orchestrate_lock:{app_id}"

        cache.add(lock_key, "task-xyz", 600)
        assert cache.get(lock_key) is not None

        _invoke_on_failure(retries=1, max_retries=3, args=[app_id], kwargs={})

        # Lock must still be held so the next retry is protected (M22)
        assert cache.get(lock_key) is not None, "Dedup lock must be kept alive during retries (M22)"

    @CACHE_OVERRIDE
    def test_lock_released_when_application_id_from_kwargs(self):
        """on_failure extracts application_id from kwargs when args is empty."""
        from django.core.cache import cache

        app_id = "KwargsApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.add(lock_key, "task-k", 600)

        _invoke_on_failure(retries=3, max_retries=3, args=[], kwargs={"application_id": app_id})

        assert cache.get(lock_key) is None

    @CACHE_OVERRIDE
    def test_no_lock_no_crash_when_application_id_missing(self):
        """on_failure must not crash when no application_id is available."""
        # Should not raise even if no lock was set and no application_id given
        _invoke_on_failure(retries=3, max_retries=3, args=[], kwargs={})

    @CACHE_OVERRIDE
    def test_lock_released_at_exactly_max_retries(self):
        """Boundary: retries == max_retries (not just >)."""
        from django.core.cache import cache

        app_id = "BoundaryApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.add(lock_key, "task-b", 600)

        _invoke_on_failure(retries=3, max_retries=3, args=[app_id], kwargs={})

        assert cache.get(lock_key) is None

    @CACHE_OVERRIDE
    def test_lock_kept_at_zero_retries(self):
        """First failure attempt (retries=0, max_retries=3) must not release the lock."""
        from django.core.cache import cache

        app_id = "ZeroRetryApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.add(lock_key, "task-z", 600)

        _invoke_on_failure(retries=0, max_retries=3, args=[app_id], kwargs={})

        assert cache.get(lock_key) is not None


class TestOnFailureStuckCleanup:
    """Terminal failure must also reset the stuck-PROCESSING application (S1-F4).

    Before the fix on_failure only deleted the dedup lock; the application
    stayed PROCESSING forever because the designed cleanup path was never
    invoked on terminal failure.
    """

    @CACHE_OVERRIDE
    def test_terminal_failure_calls_stuck_cleanup_and_releases_lock(self):
        from django.core.cache import cache

        app_id = "CleanupApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.add(lock_key, "task-c", 600)

        with patch("apps.agents.tasks._cleanup_stuck_application") as mock_cleanup:
            _invoke_on_failure(retries=3, max_retries=3, args=[app_id], kwargs={})

        mock_cleanup.assert_called_once_with(app_id, clear_lock=True)
        assert cache.get(lock_key) is None, "Lock must be released on terminal failure"

    @CACHE_OVERRIDE
    def test_cleanup_error_never_masks_failure_and_lock_still_released(self):
        from django.core.cache import cache

        app_id = "CleanupBoomApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.add(lock_key, "task-cb", 600)

        with patch(
            "apps.agents.tasks._cleanup_stuck_application",
            side_effect=RuntimeError("cleanup boom"),
        ):
            # Must not raise: a cleanup error never masks the original failure.
            _invoke_on_failure(retries=3, max_retries=3, args=[app_id], kwargs={})

        assert cache.get(lock_key) is None, "Lock release must survive a cleanup error"

    @CACHE_OVERRIDE
    def test_mid_retry_failure_does_not_run_stuck_cleanup(self):
        with patch("apps.agents.tasks._cleanup_stuck_application") as mock_cleanup:
            _invoke_on_failure(retries=1, max_retries=3, args=["MidRetryApp-001"], kwargs={})

        mock_cleanup.assert_not_called()


class TestOrchestrateRetryReentrancy:
    """A Celery autoretry re-executes the body with the SAME task id (S1-F4).

    The dedup lock is deliberately kept across infrastructure-error retries
    (M22), so the retry's own ``cache.add`` fails.  The body must recognise
    its own task id in the lock value and proceed instead of returning a
    bogus ``dedup_lock_held`` success that strands the app in PROCESSING.
    """

    def _run_task(self, app_id, task_id):
        """Execute the task body eagerly with mocked DB/orchestrator deps."""
        from apps.agents.tasks import orchestrate_pipeline_task

        agent_run = MagicMock()
        agent_run.id = "run-001"
        agent_run.status = "completed"
        agent_run.total_time_ms = 123
        agent_run.steps = []

        with (
            patch("apps.agents.models.AgentRun") as mock_run_model,
            patch("apps.agents.services.orchestrator.PipelineOrchestrator") as mock_orch,
            patch("apps.loans.models.AuditLog"),
        ):
            mock_run_model.objects.filter.return_value.exists.return_value = False
            mock_orch.return_value.orchestrate.return_value = agent_run
            result = orchestrate_pipeline_task.apply(args=[app_id], task_id=task_id)
        return result.result, mock_orch

    @CACHE_OVERRIDE
    def test_own_retry_reenters_lock_and_runs_pipeline(self):
        """Lock held by OUR OWN task id (autoretry re-entry) → pipeline runs."""
        from django.core.cache import cache

        app_id = "ReentryApp-001"
        task_id = "reentry-task-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.set(lock_key, task_id, 600)

        result, mock_orch = self._run_task(app_id, task_id)

        assert result.get("skipped") is not True, "Own retry must not skip itself"
        assert result.get("agent_run_id") == "run-001"
        mock_orch.return_value.orchestrate.assert_called_once_with(app_id)
        # Success path releases the lock as usual.
        assert cache.get(lock_key) is None

    @CACHE_OVERRIDE
    def test_foreign_lock_holder_still_skips(self):
        """Lock held by ANOTHER task id → still dedup-skips, lock untouched."""
        from django.core.cache import cache

        app_id = "ForeignLockApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        cache.set(lock_key, "someone-elses-task", 600)

        result, mock_orch = self._run_task(app_id, "my-task-001")

        assert result == {"skipped": True, "reason": "dedup_lock_held"}
        mock_orch.return_value.orchestrate.assert_not_called()
        assert cache.get(lock_key) == "someone-elses-task"

    @CACHE_OVERRIDE
    def test_uncontended_lock_acquired_and_pipeline_runs(self):
        """No lock held → normal acquisition path keeps working."""
        from django.core.cache import cache

        app_id = "FreshApp-001"
        lock_key = f"orchestrate_lock:{app_id}"
        assert cache.get(lock_key) is None

        result, mock_orch = self._run_task(app_id, "fresh-task-001")

        assert result.get("agent_run_id") == "run-001"
        mock_orch.return_value.orchestrate.assert_called_once_with(app_id)
        assert cache.get(lock_key) is None
