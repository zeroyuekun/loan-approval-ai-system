"""Cost accounting must be PROVIDER-keyed for free backends, not model-tag-keyed.

Two phantom-spend bugs this pins shut:

* ``estimate_cost_usd`` fell back to Sonnet pricing for any UNLISTED model tag,
  so a future Ollama tag (not in MODEL_PRICING) would accrue Sonnet-rate spend
  against the shared $5/day cap — exhausting it at ~125 calls and flipping the
  REAL Claude services to template fallbacks at $0 actual spend.
* ``record_call`` applied a ``max(1, …)`` 1-cent-per-call floor even to $0
  free-backend calls, draining $2.00 of phantom spend per 200 calls.

The fix keys $0 pricing off the client's ``provider`` (groq/ollama), which
``guarded_api_call`` already reads for the APICallLog destination. Free calls
still consume call slots against the daily call limit — only the dollar
accounting is zeroed. A free call also reserves 0 cents up front, so a call
killed mid-flight cannot leave a phantom hold on the cost counter.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import redis

from apps.agents.services.api_budget import ApiBudgetGuard, _estimate_reserve_cents, estimate_cost_usd, guarded_api_call

_UNLISTED_TAG = "totally-unknown-tag"  # deliberately NOT in MODEL_PRICING


def _cost_key():
    return ApiBudgetGuard()._daily_key("cost_cents")


def _guard():
    """ApiBudgetGuard with a pre-injected mock Redis client, pipeline and reserve script."""
    g = ApiBudgetGuard()
    g._redis = MagicMock()
    g._redis.exists.return_value = False
    g._redis.register_script.return_value = MagicMock(return_value=[1, 0, 1])
    pipe = MagicMock()
    g._redis.pipeline.return_value = pipe
    return g, pipe


def _cost_incrby_deltas(pipe):
    """All incrby deltas applied to the cost_cents key on the pipeline."""
    return [c.args[1] for c in pipe.incrby.call_args_list if c.args[0] == _cost_key()]


# ---------------------------------------------------------------------------
# estimate_cost_usd: provider-keyed zeroing
# ---------------------------------------------------------------------------


def test_unlisted_tag_on_free_provider_costs_zero():
    """An UNLISTED model tag on a free provider must estimate $0 — no Sonnet
    fallback phantom spend for a future Ollama/Groq tag."""
    assert estimate_cost_usd(8000, 2048, _UNLISTED_TAG, provider="ollama") == 0.0
    assert estimate_cost_usd(8000, 2048, _UNLISTED_TAG, provider="groq") == 0.0


def test_unlisted_tag_on_default_provider_still_falls_back_to_sonnet():
    """Anthropic (default) path is unchanged: unknown tags conservatively
    fall back to Sonnet pricing (> $0)."""
    cost = estimate_cost_usd(8000, 2048, _UNLISTED_TAG)
    assert cost == pytest.approx((8000 * 3.00 + 2048 * 15.00) / 1_000_000)
    assert cost > 0


# ---------------------------------------------------------------------------
# record_call: no 1-cent floor for free providers
# ---------------------------------------------------------------------------


def test_record_call_free_provider_reconcile_releases_full_reservation():
    """Successful reconcile on a free provider: cost settles at 0 cents (no
    1c floor) — the full reservation is given back."""
    guard, pipe = _guard()
    guard.record_call(
        input_tokens=8000,
        output_tokens=2048,
        model=_UNLISTED_TAG,
        reserved_cents=5,
        provider="ollama",
    )
    # cost_cents = 0 (no floor) -> delta = 0 - 5 = -5
    assert _cost_incrby_deltas(pipe) == [-5]


def test_record_call_free_provider_unreserved_adds_zero_cost():
    """Unreserved fallback path on a free provider: 0 cents recorded (the
    delta-zero short-circuit means no cost incrby at all)."""
    guard, pipe = _guard()
    guard.record_call(input_tokens=8000, output_tokens=2048, model=_UNLISTED_TAG, reserved_cents=None, provider="groq")
    assert _cost_incrby_deltas(pipe) == []
    # The call slot is still consumed (call-count accounting unchanged).
    pipe.incr.assert_called_once()


# ---------------------------------------------------------------------------
# reserve: a free call holds no money but still takes a call slot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["ollama", "groq"])
def test_free_provider_reserves_zero_cents(provider):
    assert _estimate_reserve_cents(_UNLISTED_TAG, 1024, provider=provider) == 0


def test_paid_provider_keeps_the_reserve_floor():
    assert _estimate_reserve_cents("claude-sonnet-4-6", 1024, provider="anthropic") >= 5


def test_zero_cent_reservation_holds_no_money_but_takes_a_call_slot():
    guard, _ = _guard()
    assert guard.reserve_budget(estimated_cost_cents=0, provider="ollama") == 0
    cents, calls = guard._redis.register_script.return_value.call_args.kwargs["args"][:2]
    assert (cents, calls) == (0, 1)


def test_reconcile_after_a_zero_cent_reservation_does_not_count_the_call_twice():
    guard, pipe = _guard()
    guard.record_call(input_tokens=700, output_tokens=60, model=_UNLISTED_TAG, reserved_cents=0, provider="ollama")
    pipe.incr.assert_not_called()
    assert _cost_incrby_deltas(pipe) == []


def test_failure_after_a_zero_cent_reservation_gives_the_call_slot_back():
    guard, pipe = _guard()
    guard._redis.exists.return_value = True
    guard.record_call(model=_UNLISTED_TAG, reserved_cents=0, released=True, provider="ollama")
    pipe.decr.assert_called_once_with(guard._daily_key("calls"))
    assert _cost_incrby_deltas(pipe) == []


def test_redis_outage_reserves_nothing_and_says_so():
    guard, _ = _guard()
    guard._redis.exists.side_effect = redis.ConnectionError("down")
    assert guard.reserve_budget(estimated_cost_cents=5) is None


def test_record_call_paid_provider_keeps_one_cent_floor():
    """Pin current paid-path behavior: a near-$0 call on the anthropic
    provider still floors to 1 cent per call."""
    guard, pipe = _guard()
    guard.record_call(
        input_tokens=10,
        output_tokens=5,
        model="claude-sonnet-4-6",  # 10/5 tokens round to 0 cents
        reserved_cents=5,
        provider="anthropic",
    )
    # cost_cents = max(1, 0) = 1 -> delta = 1 - 5 = -4
    assert _cost_incrby_deltas(pipe) == [-4]


# ---------------------------------------------------------------------------
# guarded_api_call: provider flows end-to-end into the budget accounting
# ---------------------------------------------------------------------------


def _fake_client(provider):
    client = MagicMock()
    client.provider = provider
    client.messages.create.return_value = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    return client


@pytest.mark.django_db
@patch("apps.agents.services.api_budget.ApiBudgetGuard")
def test_guarded_api_call_passes_provider_to_record_call(mock_guard_cls):
    """End-to-end: an ollama client with an UNLISTED tag must record its call
    provider-keyed, so the budget math zeroes it."""
    guard = mock_guard_cls.return_value

    guarded_api_call(_fake_client("ollama"), model=_UNLISTED_TAG, messages=[{"role": "user", "content": "hi"}])

    assert guard.record_call.call_count == 1
    assert guard.record_call.call_args.kwargs["provider"] == "ollama"
    assert guard.reserve_budget.call_args.kwargs["estimated_cost_cents"] == 0


@pytest.mark.django_db
@patch("apps.agents.services.api_budget.ApiBudgetGuard")
def test_guarded_api_call_passes_provider_on_failure_release(mock_guard_cls):
    """The failure-release record_call must also be provider-keyed."""
    guard = mock_guard_cls.return_value
    client = _fake_client("ollama")
    client.messages.create.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        guarded_api_call(client, model=_UNLISTED_TAG, messages=[{"role": "user", "content": "hi"}])

    assert guard.record_call.call_count == 1
    kwargs = guard.record_call.call_args.kwargs
    assert kwargs["provider"] == "ollama"
    assert kwargs["released"] is True
