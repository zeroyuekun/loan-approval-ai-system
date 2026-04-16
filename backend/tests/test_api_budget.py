from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from apps.agents.services.api_budget import ApiBudgetGuard, BudgetExhausted, CircuitOpen


def _guard(mock_redis):
    """Create an ApiBudgetGuard with a pre-injected mock Redis client."""
    g = ApiBudgetGuard()
    g._redis = mock_redis
    return g


@override_settings(AI_DAILY_CALL_LIMIT=500)
def test_budget_check_passes():
    """Under daily limit -> check_budget succeeds silently."""
    r = MagicMock()
    r.exists.return_value = False
    r.get.return_value = b"100"
    _guard(r).check_budget()


@override_settings(AI_DAILY_CALL_LIMIT=500)
def test_budget_exhausted():
    """At daily limit -> raises BudgetExhausted."""
    r = MagicMock()
    r.exists.return_value = False
    r.get.side_effect = [b"0", b"500"]  # cost_cents=0 (passes), call_count=500 (triggers)
    with pytest.raises(BudgetExhausted, match="Daily API call limit reached"):
        _guard(r).check_budget()


def test_circuit_open():
    """Circuit breaker key present -> raises CircuitOpen."""
    r = MagicMock()
    r.exists.return_value = True
    r.ttl.return_value = 300
    with pytest.raises(CircuitOpen, match="Circuit breaker open"):
        _guard(r).check_budget()


def test_record_call_increments():
    """record_call increments the daily counter via pipeline."""
    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe
    _guard(r).record_call(input_tokens=500, output_tokens=200)
    pipe.incr.assert_called_once()
    pipe.execute.assert_called_once()


@override_settings(AI_CIRCUIT_BREAKER_THRESHOLD=3, AI_CIRCUIT_BREAKER_COOLDOWN=600)
def test_failures_trip_breaker():
    """After threshold consecutive failures, circuit breaker key is set."""
    r = MagicMock()
    r.incr.return_value = 3
    _guard(r).record_failure()
    r.setex.assert_called_once_with("ai_budget:circuit_breaker", 600, 1)


def test_success_resets_failures():
    """record_success deletes the consecutive failure counter."""
    r = MagicMock()
    _guard(r).record_success()
    r.delete.assert_called_once_with("ai_budget:consecutive_failures")


def test_redis_down_allows_brief_blip():
    """When Redis is unreachable, a single check_budget still passes so a
    Redis blip doesn't immediately kill all traffic."""
    from apps.agents.services import api_budget

    # Reset the process-local counter so other tests don't leak in
    api_budget._REDIS_FALLBACK_CALLS = 0

    r = MagicMock()
    r.exists.side_effect = ConnectionError("Redis connection refused")
    # Should not raise (well below the per-process fallback limit)
    _guard(r).check_budget()


def test_redis_sustained_outage_fails_closed():
    """After the per-process fallback limit, check_budget must raise
    BudgetExhausted to protect the API budget during a Redis outage."""
    from apps.agents.services import api_budget
    from apps.agents.services.api_budget import BudgetExhausted

    api_budget._REDIS_FALLBACK_CALLS = 0

    r = MagicMock()
    r.exists.side_effect = ConnectionError("Redis connection refused")
    guard = _guard(r)

    # Consume the fallback budget
    for _ in range(api_budget._REDIS_FALLBACK_LIMIT):
        guard.check_budget()

    # Next call must raise
    with pytest.raises(BudgetExhausted):
        guard.check_budget()
