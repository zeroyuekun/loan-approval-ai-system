"""Regression tests for api_budget Redis-fallback behaviour (F-04).

The process-local fallback counter must:
1. Reset to 0 once Redis recovers, so a transient outage does not permanently
   brick a Celery worker.
2. Be thread-safe under concurrent increment, because Celery IO workers run
   with concurrency > 1 and unlocked ``+=`` is not atomic on multi-threaded
   Python.
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
import redis

from apps.agents.services import api_budget
from apps.agents.services.api_budget import ApiBudgetGuard, BudgetExhausted


@pytest.fixture(autouse=True)
def reset_counter():
    api_budget._REDIS_FALLBACK_CALLS = 0
    yield
    api_budget._REDIS_FALLBACK_CALLS = 0


class _FakeRedis:
    """Minimal healthy-Redis stub — no circuit breaker, zero spend, zero calls."""

    def exists(self, _):
        return False

    def ttl(self, _):
        return 0

    def get(self, _):
        return b"0"


def test_fallback_counter_resets_after_redis_recovers():
    """After 20 Redis-unavailable calls plus one successful call, counter is 0."""
    guard = ApiBudgetGuard()

    # Simulate 20 Redis outage calls — each warns, none raise (limit is 20).
    with patch.object(guard, "_get_redis", side_effect=redis.RedisError("down")):
        for _ in range(20):
            guard.check_budget()

    assert api_budget._REDIS_FALLBACK_CALLS == 20

    # Redis recovers — the next call should succeed and reset the counter.
    with patch.object(guard, "_get_redis", return_value=_FakeRedis()):
        guard.check_budget()

    assert api_budget._REDIS_FALLBACK_CALLS == 0, "Counter must reset once Redis becomes available again"


def test_fallback_counter_is_thread_safe():
    """1000 concurrent increments during a simulated Redis outage count to exactly 1000."""
    guard = ApiBudgetGuard()

    def _one_call():
        with patch.object(guard, "_get_redis", side_effect=redis.RedisError("down")):
            try:
                guard.check_budget()
            except BudgetExhausted:
                pass

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(_one_call) for _ in range(1000)]
        for f in futures:
            f.result()

    # Exactly 1000 increments expected; race conditions would undercount.
    assert api_budget._REDIS_FALLBACK_CALLS == 1000, (
        f"Race in counter increment: expected 1000, got {api_budget._REDIS_FALLBACK_CALLS}"
    )
