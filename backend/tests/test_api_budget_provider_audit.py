"""The APICallLog cross-border (Privacy Act APP 8) record must reflect WHERE the
prompt was actually processed, derived from the client's provider:

  * hosted providers (Anthropic, Groq) are US  -> a cross-border disclosure;
  * local Ollama runs on-prem in Australia      -> NOT a cross-border disclosure.

A hardcoded "US" would manufacture a false cross-border record for local
inference, so this pins the per-provider derivation.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.agents.services.api_budget import guarded_api_call


def _fake_client(provider):
    """A stub LLM client whose .messages.create returns a minimal usage-bearing
    response, tagged with the given provider (as the real adapters expose)."""
    client = MagicMock()
    client.provider = provider
    client.messages.create.return_value = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    return client


@pytest.mark.django_db
@patch("apps.agents.services.api_budget.ApiBudgetGuard")
def test_apicalllog_destination_country_reflects_provider(mock_guard_cls):
    # Neutralise the Redis-backed budget guard so no broker is required.
    mock_guard_cls.return_value = MagicMock()
    from apps.agents.models import APICallLog

    msgs = [{"role": "user", "content": "hi"}]

    # Local Ollama -> AU (on-prem; not a cross-border disclosure).
    guarded_api_call(_fake_client("ollama"), model="loan-email", messages=msgs)
    ollama_log = APICallLog.objects.get(provider="ollama")
    assert ollama_log.destination_country == "AU"

    # Hosted Groq -> US (cross-border).
    guarded_api_call(_fake_client("groq"), model="llama-3.1-8b-instant", messages=msgs)
    assert APICallLog.objects.get(provider="groq").destination_country == "US"

    # Default/Anthropic -> US.
    guarded_api_call(_fake_client("anthropic"), model="claude-sonnet-4-6", messages=msgs)
    assert APICallLog.objects.get(provider="anthropic").destination_country == "US"
