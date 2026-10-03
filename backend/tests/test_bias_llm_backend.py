"""The bias verdict can run on the local Ollama server (BIAS_LLM_BACKEND=ollama)."""

from unittest.mock import MagicMock

from apps.agents.services.bias import helpers
from apps.agents.services.bias.core import BiasDetector
from apps.agents.services.bias.marketing import MarketingBiasDetector, MarketingEmailReviewer
from apps.agents.services.bias.reviewer import AIEmailReviewer
from apps.email_engine.services.llm_client import OpenAICompatibleLLMClient


def test_default_backend_is_anthropic(settings, monkeypatch):
    settings.BIAS_LLM_BACKEND = "anthropic"
    sentinel = object()
    monkeypatch.setattr(helpers, "make_anthropic_client", lambda: sentinel)
    assert helpers._make_bias_llm_client() is sentinel


def test_ollama_backend_builds_local_client(settings):
    settings.BIAS_LLM_BACKEND = "ollama"
    settings.BIAS_OLLAMA_MODEL = "qwen2.5:7b"
    client = helpers._make_bias_llm_client()
    assert isinstance(client, OpenAICompatibleLLMClient)
    assert client.provider == "ollama"


def test_ollama_backend_names_the_local_model(settings):
    """Every bias agent must name the local model, never a Claude id Ollama cannot serve."""
    settings.BIAS_LLM_BACKEND = "ollama"
    settings.BIAS_OLLAMA_MODEL = "qwen2.5:7b"
    assert AIEmailReviewer().model == "qwen2.5:7b"
    assert MarketingEmailReviewer().model == "qwen2.5:7b"
    assert helpers.bias_model(BiasDetector().client, "claude-sonnet-4-6") == "qwen2.5:7b"
    assert helpers.bias_model(MarketingBiasDetector().client, "claude-sonnet-4-6") == "qwen2.5:7b"


def test_anthropic_backend_keeps_claude_models(settings):
    settings.BIAS_LLM_BACKEND = "anthropic"
    assert helpers.bias_model(MagicMock(provider="anthropic"), "claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert helpers.bias_model(None, "claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_detector_sends_local_model_to_ollama(settings, monkeypatch):
    settings.BIAS_LLM_BACKEND = "ollama"
    settings.BIAS_OLLAMA_MODEL = "qwen2.5:7b"
    seen = {}

    def fake_call(client, fallback, *args, **kwargs):
        seen.update(kwargs)
        return {"score": 80, "categories": ["Prohibited Language"], "analysis": "genuine"}

    monkeypatch.setattr("apps.agents.services.bias.core._call_with_fallback", fake_call)
    email = "Dear Sam,\n\nAs a single mother, your budget is too stretched for this loan.\n\nKind regards"
    result = BiasDetector().analyze(email, {"loan_amount": 30000, "purpose": "personal", "decision": "denied"})
    assert seen["model"] == "qwen2.5:7b"
    assert result["flagged"] is True
