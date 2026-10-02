"""I8 — circuit breakers are per provider and trip only on transient failures.

One global breaker key was tripped by ANY exception from any provider,
including non-transient 4xx such as a free-tier 413 "request too large".
Three Groq emails in a row therefore blocked Anthropic bias, NBO and
marketing calls for ten minutes, and a failing paid API blocked the free
local backend.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from django.test import override_settings

from apps.agents.services.api_budget import ApiBudgetGuard, CircuitOpen, guarded_api_call, is_transient_failure
from apps.email_engine.services.exceptions import EmailBackendError, RateLimited


class _FakeRedis:
    """Just enough of redis-py for the breaker keys."""

    def __init__(self):
        self.store = {}

    def exists(self, key):
        return key in self.store

    def ttl(self, key):
        return 600

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, seconds):
        return True

    def setex(self, key, seconds, value):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    def get(self, key):
        return self.store.get(key)


def _guard(fake):
    g = ApiBudgetGuard()
    g._redis = fake
    return g


@override_settings(AI_CIRCUIT_BREAKER_THRESHOLD=3, AI_DAILY_CALL_LIMIT=500, AI_DAILY_BUDGET_LIMIT_USD=5.0)
def test_breaker_is_scoped_to_the_failing_provider():
    fake = _FakeRedis()
    guard = _guard(fake)
    for _ in range(3):
        guard.record_failure("groq")

    with pytest.raises(CircuitOpen):
        guard.check_budget(provider="groq")
    guard.check_budget(provider="anthropic")  # unaffected
    guard.check_budget(provider="ollama")  # unaffected


@override_settings(AI_CIRCUIT_BREAKER_THRESHOLD=3)
def test_success_resets_only_its_own_provider():
    fake = _FakeRedis()
    guard = _guard(fake)
    guard.record_failure("groq")
    guard.record_failure("anthropic")
    guard.record_success("anthropic")
    assert any("groq" in k for k in fake.store)
    assert not any("anthropic" in k for k in fake.store)


def _status_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message="x", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (EmailBackendError("groq API error 413: too large", status_code=413), False),
        (EmailBackendError("groq API error 400", status_code=400), False),
        (EmailBackendError("groq API error 503", status_code=503), True),
        (EmailBackendError("ollama request failed: connection refused"), True),  # transport
        (RateLimited(), True),
        (TimeoutError(), True),
        (ConnectionError(), True),
        (_status_error(anthropic.BadRequestError, 400), False),
        (_status_error(anthropic.AuthenticationError, 401), False),
        (_status_error(anthropic.RateLimitError, 429), True),
        (_status_error(anthropic.InternalServerError, 500), True),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), True),
        (ValueError("bug"), False),
    ],
)
def test_transient_classification(exc, transient):
    assert is_transient_failure(exc) is transient


def _client(provider, exc):
    client = MagicMock()
    client.provider = provider
    client.messages.create.side_effect = exc
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("exc", "should_trip"),
    [
        (EmailBackendError("groq API error 413", status_code=413), False),
        (EmailBackendError("groq API error 502", status_code=502), True),
    ],
)
def test_guarded_call_counts_only_transient_failures(exc, should_trip):
    guard = MagicMock()
    guard.reserve_budget.return_value = 0
    with patch("apps.agents.services.api_budget.ApiBudgetGuard", return_value=guard):
        with pytest.raises(type(exc)):
            guarded_api_call(_client("groq", exc), model="m", messages=[{"role": "user", "content": "x"}])
    if should_trip:
        guard.record_failure.assert_called_once_with("groq")
    else:
        guard.record_failure.assert_not_called()


@pytest.mark.django_db
def test_guarded_call_success_resets_its_provider():
    guard = MagicMock()
    guard.reserve_budget.return_value = 0
    client = MagicMock()
    client.provider = "ollama"
    client.messages.create.return_value = SimpleNamespace(usage=None)
    with patch("apps.agents.services.api_budget.ApiBudgetGuard", return_value=guard):
        guarded_api_call(client, model="m", messages=[{"role": "user", "content": "x"}])
    guard.record_success.assert_called_once_with("ollama")
    _, kwargs = guard.reserve_budget.call_args
    assert kwargs.get("provider") == "ollama"
