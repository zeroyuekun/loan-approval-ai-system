"""Guards for the adaptive-only-model sampling-parameter fix.

Opus 4.7+ and Fable 5 reject temperature/top_p/top_k with a 400 — they are
adaptive-thinking only. The senior bias reviewers pass temperature=0, so
without a central strip every senior review would 400 the moment a real
ANTHROPIC_API_KEY is set, and silently fall through to human escalation.
These tests pin the family-based strip (including dated and platform-prefixed
model IDs), the Opus 4.8 / Fable 5 pricing, and the configurable reviewer
model with its blank-value fallback.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.agents.services import api_budget
from apps.agents.services.api_budget import estimate_cost_usd, guarded_api_call
from apps.agents.services.bias.helpers import DEFAULT_REVIEWER_MODEL, _reviewer_model


def _stub_client():
    """An LLM client stub; inspect kwargs via client.messages.create.call_args."""
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return client


@pytest.fixture
def no_side_effects():
    """Neutralise the Redis budget guard and the APICallLog audit write."""
    with (
        patch("apps.agents.services.api_budget.ApiBudgetGuard"),
        patch("apps.agents.models.APICallLog"),
    ):
        yield


def test_adaptive_only_families_pinned():
    """Membership changes here must be deliberate (and priced in MODEL_PRICING)."""
    assert api_budget._SAMPLING_PARAMS_REMOVED_FAMILIES == (
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
    )


def test_strips_sampling_params_for_adaptive_only_models(no_side_effects):
    """temperature/top_p/top_k must NOT reach the API for adaptive-only models,
    including dated snapshots and platform-prefixed (Bedrock-style) IDs."""
    models = [
        variant
        for family in api_budget._SAMPLING_PARAMS_REMOVED_FAMILIES
        for variant in (family, f"{family}-20260301", f"anthropic.{family}")
    ]
    for model in models:
        client = _stub_client()
        guarded_api_call(
            client,
            model=model,
            max_tokens=64,
            temperature=0.0,
            top_p=0.5,
            top_k=10,
            messages=[{"role": "user", "content": "x"}],
        )
        sent = client.messages.create.call_args.kwargs
        assert "temperature" not in sent, model
        assert "top_p" not in sent, model
        assert "top_k" not in sent, model
        assert sent["model"] == model


def test_keeps_sampling_params_for_models_that_accept_them(no_side_effects):
    """Sonnet/Haiku and the Groq/Ollama models still accept temperature."""
    for model in ("claude-sonnet-4-6", "claude-haiku-4-5-20251001", "llama-3.1-8b-instant"):
        client = _stub_client()
        guarded_api_call(
            client,
            model=model,
            max_tokens=64,
            temperature=0.3,
            messages=[{"role": "user", "content": "x"}],
        )
        assert client.messages.create.call_args.kwargs["temperature"] == 0.3, model


def test_adaptive_only_models_are_priced_not_default_fallback():
    """Every settable adaptive-only model needs a real MODEL_PRICING row, or the
    $5/day budget guard counts it at the (cheaper) Sonnet fallback price."""
    assert api_budget.MODEL_PRICING["claude-opus-4-8"] == {"input": 5.00, "output": 25.00}
    assert api_budget.MODEL_PRICING["claude-fable-5"] == {"input": 10.00, "output": 50.00}
    # 1M input + 1M output
    assert estimate_cost_usd(1_000_000, 1_000_000, "claude-opus-4-8") == 30.0
    assert estimate_cost_usd(1_000_000, 1_000_000, "claude-fable-5") == 60.0


@override_settings(BIAS_REVIEWER_MODEL="claude-fable-5")
def test_senior_reviewers_use_configured_model():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        from apps.agents.services.bias.marketing import MarketingEmailReviewer
        from apps.agents.services.bias.reviewer import AIEmailReviewer

        assert AIEmailReviewer().model == "claude-fable-5"
        assert MarketingEmailReviewer().model == "claude-fable-5"


@override_settings(BIAS_REVIEWER_MODEL="")
def test_blank_reviewer_model_falls_back_to_default():
    """A set-but-blank BIAS_REVIEWER_MODEL= line in .env must not reach the API
    as model='' — it falls back to the default."""
    assert _reviewer_model() == DEFAULT_REVIEWER_MODEL == "claude-opus-4-8"


def test_reviewer_has_no_client_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        from apps.agents.services.bias.reviewer import AIEmailReviewer

        assert AIEmailReviewer().client is None
