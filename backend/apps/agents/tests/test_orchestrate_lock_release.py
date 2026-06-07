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

        assert cache.get(lock_key) is None, (
            "Dedup lock must be released after max_retries exhausted"
        )

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
        assert cache.get(lock_key) is not None, (
            "Dedup lock must be kept alive during retries (M22)"
        )

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
