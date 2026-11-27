"""BIAS_LLM_BACKEND picks the bias LLM: none (default, rules only), groq, ollama or anthropic."""

from unittest.mock import MagicMock

from apps.agents.services.bias import helpers
from apps.agents.services.bias.core import BiasDetector
from apps.agents.services.bias.marketing import MarketingBiasDetector, MarketingEmailReviewer
from apps.agents.services.bias.reviewer import AIEmailReviewer
from apps.email_engine.services.llm_client import OpenAICompatibleLLMClient


def test_anthropic_backend_builds_claude_client(settings, monkeypatch):
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


def test_none_backend_has_no_client(settings, monkeypatch):
    """BIAS_LLM_BACKEND=none (the default) turns the LLM off, even with keys present."""
    settings.BIAS_LLM_BACKEND = "none"
    settings.GROQ_API_KEY = "gsk-test"
    monkeypatch.setattr(helpers, "make_anthropic_client", lambda: object())
    assert helpers._make_bias_llm_client() is None
    assert BiasDetector().client is None


def test_unknown_backend_does_not_fall_through_to_claude(settings, monkeypatch):
    """A typo must not silently start paid Claude calls."""
    settings.BIAS_LLM_BACKEND = "grok"
    monkeypatch.setattr(helpers, "make_anthropic_client", lambda: object())
    assert helpers._make_bias_llm_client() is None


def test_groq_backend_builds_hosted_client(settings):
    settings.BIAS_LLM_BACKEND = "groq"
    settings.GROQ_API_KEY = "gsk-test"
    settings.BIAS_GROQ_MODEL = "llama-3.1-8b-instant"
    client = helpers._make_bias_llm_client()
    assert isinstance(client, OpenAICompatibleLLMClient)
    assert client.provider == "groq"
    assert client.default_model == "llama-3.1-8b-instant"


def test_groq_backend_without_a_key_has_no_client(settings):
    """No key means no LLM verdict: callers treat the check as unavailable, as for Claude."""
    settings.BIAS_LLM_BACKEND = "groq"
    settings.GROQ_API_KEY = ""
    assert helpers._make_bias_llm_client() is None


def test_groq_backend_names_the_groq_model(settings):
    settings.BIAS_LLM_BACKEND = "groq"
    settings.GROQ_API_KEY = "gsk-test"
    settings.BIAS_GROQ_MODEL = "llama-3.1-8b-instant"
    assert AIEmailReviewer().model == "llama-3.1-8b-instant"
    assert helpers.bias_model(BiasDetector().client, "claude-sonnet-4-6") == "llama-3.1-8b-instant"


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


def test_bias_tool_asks_for_the_analysis_before_the_score():
    """A local model under a json_schema response_format writes fields in schema order.

    With the score first, Llama committed to a number before reading its own
    reasoning and cleared genuine flags (junior score 0 on a "single mother" denial).
    """
    from apps.agents.services.bias.tools import BIAS_ANALYSIS_TOOL

    assert list(BIAS_ANALYSIS_TOOL["input_schema"]["properties"])[0] == "analysis"
    assert list(BIAS_ANALYSIS_TOOL["input_schema"]["properties"])[-1] == "score"


def test_tool_categories_cover_every_protected_attribute_the_prompt_names():
    """Groq rejects a tool call whose categories fall outside the enum.

    The prompt tells the model pregnancy, nationality and family
    responsibilities are protected; if the enum lacked them, a correct verdict
    naming one would come back as a 400 and the real verdict would be lost.
    """
    from apps.agents.services.bias.core import PROTECTED_ATTRIBUTE_RULE
    from apps.agents.services.bias.tools import BIAS_ANALYSIS_TOOL, MARKETING_BIAS_TOOL

    named = {
        "pregnancy": "pregnancy",
        "age": "age",
        "gender": "gender",
        "race": "race",
        "nationality": "nationality",
        "religion": "religion",
        "disability": "disability",
        "marital status": "marital_status",
        "family responsibilities": "family_responsibilities",
    }
    for phrase in named:
        assert phrase in PROTECTED_ATTRIBUTE_RULE.lower(), phrase
    for tool in (BIAS_ANALYSIS_TOOL, MARKETING_BIAS_TOOL):
        enum = tool["input_schema"]["properties"]["categories"]["items"]["enum"]
        assert set(named.values()) <= set(enum), tool["name"]
