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


# ---------------------------------------------------------------------------
# Prompt-caching cost math — cache writes (1.25×) and reads (0.10×)
# ---------------------------------------------------------------------------


def test_estimate_cost_no_caching_unchanged():
    """Without cache fields, cost math matches the pre-caching behavior."""
    from apps.agents.services.api_budget import estimate_cost_usd

    # claude-sonnet-4-6: $3/M input, $15/M output
    # 1000 in + 500 out = 1000*3/1M + 500*15/1M = $0.003 + $0.0075 = $0.0105
    cost = estimate_cost_usd(
        input_tokens=1000, output_tokens=500, model="claude-sonnet-4-6"
    )
    assert cost == round(0.0105, 6)


def test_estimate_cost_cache_write_uses_1_25x_multiplier():
    """cache_creation_input_tokens cost 1.25× the model's normal input
    rate — the one-time write penalty. A 1000-token write on Sonnet
    should cost $3 * 1000 * 1.25 / 1M = $0.00375."""
    from apps.agents.services.api_budget import estimate_cost_usd

    cost = estimate_cost_usd(
        input_tokens=0,
        output_tokens=0,
        model="claude-sonnet-4-6",
        cache_creation_input_tokens=1000,
    )
    expected = round(1000 * 3.00 * 1.25 / 1_000_000, 6)
    assert cost == expected
    assert cost > 0.0  # sanity: actually charges something


def test_estimate_cost_cache_read_uses_0_10x_multiplier():
    """cache_read_input_tokens cost 0.10× the model's normal input
    rate — the cache-hit savings. A 1000-token read on Sonnet should
    cost $3 * 1000 * 0.10 / 1M = $0.0003."""
    from apps.agents.services.api_budget import estimate_cost_usd

    cost = estimate_cost_usd(
        input_tokens=0,
        output_tokens=0,
        model="claude-sonnet-4-6",
        cache_read_input_tokens=1000,
    )
    expected = round(1000 * 3.00 * 0.10 / 1_000_000, 6)
    assert cost == expected


def test_estimate_cost_combined_buckets():
    """Realistic denial-email shape on a cache hit:
    - 4000 cached system tokens read at 0.10×
    -  500 dynamic user tokens at 1.00× (standard input)
    -  800 output tokens at output rate
    All three should add into the final cost."""
    from apps.agents.services.api_budget import estimate_cost_usd

    cost = estimate_cost_usd(
        input_tokens=500,
        output_tokens=800,
        model="claude-sonnet-4-6",
        cache_read_input_tokens=4000,
    )
    # $3 * 500 / 1M + $3 * 4000 * 0.10 / 1M + $15 * 800 / 1M
    # = 0.0015 + 0.0012 + 0.012 = 0.0147
    expected = round(
        (500 * 3.00 + 4000 * 3.00 * 0.10 + 800 * 15.00) / 1_000_000, 6
    )
    assert cost == expected


def test_record_call_passes_cache_tokens_to_cost_math(monkeypatch):
    """record_call must hand cache tokens to estimate_cost_usd so the
    daily Redis budget reflects real Anthropic billing, not the
    un-cached portion only."""
    from apps.agents.services import api_budget

    received = {}

    def fake_estimate(input_tokens, output_tokens, model="", **kw):
        received["args"] = (input_tokens, output_tokens, model)
        received["kw"] = kw
        return 0.001  # any positive cost

    monkeypatch.setattr(api_budget, "estimate_cost_usd", fake_estimate)

    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe
    _guard(r).record_call(
        input_tokens=500,
        output_tokens=200,
        model="claude-sonnet-4-6",
        cache_creation_input_tokens=4000,
        cache_read_input_tokens=0,
    )

    assert received["args"] == (500, 200, "claude-sonnet-4-6")
    assert received["kw"]["cache_creation_input_tokens"] == 4000
    assert received["kw"]["cache_read_input_tokens"] == 0


def test_record_call_total_tokens_includes_cache(monkeypatch):
    """The daily `tokens` Redis counter must include cache_create + cache_read
    so the dashboard reflects total wire activity, not just the un-cached portion."""
    from apps.agents.services import api_budget

    monkeypatch.setattr(
        api_budget, "estimate_cost_usd", lambda *a, **kw: 0.001
    )

    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe
    _guard(r).record_call(
        input_tokens=500,
        output_tokens=200,
        model="claude-sonnet-4-6",
        cache_creation_input_tokens=4000,
        cache_read_input_tokens=100,
    )

    # The tokens key should have been incremented by 500 + 200 + 4000 + 100
    incrby_calls = pipe.incrby.call_args_list
    tokens_increments = [
        call.args[1] for call in incrby_calls if "tokens" in str(call.args[0])
    ]
    assert 4800 in tokens_increments, (
        f"expected total tokens increment of 4800 (500+200+4000+100), "
        f"got {tokens_increments}"
    )


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
