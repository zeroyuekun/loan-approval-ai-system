"""M5 — atomic budget reservation closes the $5/day spend-cap TOCTOU race.

These tests exercise the Lua-backed `reserve_budget` against a REAL Redis
(the Lua `register_script`/`EVAL` path cannot run on a fakeredis that lacks
Lua). They carry the shared `skip_without_redis` marker so they skip on hosts
with no Redis but run in-container/CI.
"""

import threading

import pytest

from apps.agents.services.api_budget import ApiBudgetGuard, BudgetExhausted
from tests.conftest import skip_without_redis


def _flush_budget_keys(guard):
    """Remove the day's budget counters so each test starts clean."""
    r = guard._get_redis()
    r.delete(guard._daily_key("cost_cents"))
    r.delete(guard._daily_key("calls"))
    r.delete("ai_budget:circuit_breaker")


@skip_without_redis
def test_reserve_budget_atomic_increment(settings):
    settings.AI_DAILY_BUDGET_LIMIT_USD = 5.0
    guard = ApiBudgetGuard()
    _flush_budget_keys(guard)
    r = guard._get_redis()

    guard.reserve_budget(estimated_cost_cents=100)
    guard.reserve_budget(estimated_cost_cents=100)

    # Two reservations of 100c each must increment the counter by exactly 200.
    assert int(r.get(guard._daily_key("cost_cents"))) == 200


@skip_without_redis
def test_reserve_budget_blocks_at_cap_and_rolls_back(settings):
    settings.AI_DAILY_BUDGET_LIMIT_USD = 5.0
    guard = ApiBudgetGuard()
    _flush_budget_keys(guard)
    r = guard._get_redis()

    # Pre-seed $4.99 spent; a 200c reserve would breach the $5.00 cap.
    r.set(guard._daily_key("cost_cents"), 499)

    with pytest.raises(BudgetExhausted):
        guard.reserve_budget(estimated_cost_cents=200)

    # Counter must be rolled back (never leaks the failed reservation).
    assert int(r.get(guard._daily_key("cost_cents"))) == 499


@skip_without_redis
def test_failed_call_release_restores_cost_and_call_counters(settings):
    """A failed guarded call must FULLY release its reservation.

    Phase 4 review bug: record_call applied the `max(1, ...)` cent floor even on
    the release path, leaking 1 cent per failed call, and never decremented the
    calls counter, permanently consuming a daily call slot per failure. After a
    reserve (5c + 1 call) followed by a release (record_call with 0 tokens +
    reserved=5), BOTH counters must return to their pre-reserve values.
    """
    settings.AI_DAILY_BUDGET_LIMIT_USD = 5.0
    guard = ApiBudgetGuard()
    _flush_budget_keys(guard)
    r = guard._get_redis()

    cost_key = guard._daily_key("cost_cents")
    calls_key = guard._daily_key("calls")

    # Pre-existing same-day usage so we assert the release returns to the real
    # baseline, not just to zero.
    r.set(cost_key, 37)
    r.set(calls_key, 4)
    cost_before = int(r.get(cost_key))
    calls_before = int(r.get(calls_key))

    # Reserve 5 cents + 1 call (what guarded_api_call does before the API round-trip).
    reserved = guard.reserve_budget(estimated_cost_cents=5)
    assert reserved == 5
    assert int(r.get(cost_key)) == cost_before + 5
    assert int(r.get(calls_key)) == calls_before + 1

    # Simulate the FAILURE release path: zero tokens, release the reservation
    # (this is exactly what guarded_api_call does in its except block).
    guard.record_call(
        input_tokens=0, output_tokens=0, model="claude-sonnet-4-6", reserved_cents=reserved, released=True
    )

    # Both counters must be fully restored — no 1-cent leak, no consumed call slot.
    assert int(r.get(cost_key)) == cost_before
    assert int(r.get(calls_key)) == calls_before


@skip_without_redis
def test_successful_call_keeps_call_and_reconciles_cost(settings):
    """A successful guarded call keeps the counted call and reconciles cost to actual.

    Regression guard: the release fix must NOT touch the success path. With real
    tokens consumed, the call stays counted (reserve already incremented it) and
    the cost settles at the true cost, not reserve - actual.
    """
    settings.AI_DAILY_BUDGET_LIMIT_USD = 5.0
    guard = ApiBudgetGuard()
    _flush_budget_keys(guard)
    r = guard._get_redis()

    cost_key = guard._daily_key("cost_cents")
    calls_key = guard._daily_key("calls")

    reserved = guard.reserve_budget(estimated_cost_cents=5)
    assert int(r.get(calls_key)) == 1
    assert int(r.get(cost_key)) == 5

    # 10k input + 2k output on sonnet: (10000*3 + 2000*15)/1e6 = $0.06 → 6 cents.
    from apps.agents.services.api_budget import estimate_cost_usd

    expected_cents = max(1, int(estimate_cost_usd(10000, 2000, "claude-sonnet-4-6") * 100))
    guard.record_call(
        input_tokens=10000, output_tokens=2000, model="claude-sonnet-4-6", reserved_cents=reserved
    )

    # Call stays counted (the call happened); cost reconciled to the real value.
    assert int(r.get(calls_key)) == 1
    assert int(r.get(cost_key)) == expected_cents


@skip_without_redis
def test_concurrent_reservations_never_exceed_cap(settings):
    settings.AI_DAILY_BUDGET_LIMIT_USD = 1.0  # $1.00 cap == 100 cents
    guard = ApiBudgetGuard()
    _flush_budget_keys(guard)
    r = guard._get_redis()

    successes = []
    successes_lock = threading.Lock()

    def worker():
        g = ApiBudgetGuard()
        try:
            g.reserve_budget(estimated_cost_cents=5)
            with successes_lock:
                successes.append(1)
        except BudgetExhausted:
            pass

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Successful reservations × 5c must never exceed the $1.00 cap.
    assert len(successes) * 5 <= 100
    assert int(r.get(guard._daily_key("cost_cents"))) <= 100
