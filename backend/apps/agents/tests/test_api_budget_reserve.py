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
