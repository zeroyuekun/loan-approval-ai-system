"""Reliability and local-LLM fixes from the 2026-11-22 senior review."""

import logging

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from apps.agents.services.bias.helpers import _call_with_fallback, coerce_llm_score
from apps.email_engine.services.exceptions import EmailBackendError

# --- Bias verdict robustness -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(-5, 0), (250, 100), ("42", 42), (37.9, 37), ("n/a", 50), (None, 50), ([], 50)],
)
def test_coerce_llm_score(raw, expected):
    assert coerce_llm_score(raw, 50) == expected


def test_soft_time_limit_is_not_swallowed(monkeypatch):
    def boom(*args, **kwargs):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr("apps.agents.services.bias.helpers.guarded_api_call", boom)
    with pytest.raises(SoftTimeLimitExceeded):
        _call_with_fallback(object(), {"score": 1}, "svc", "x")


def test_local_backend_error_falls_back_without_critical_log(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise EmailBackendError("ollama unreachable")

    monkeypatch.setattr("apps.agents.services.bias.helpers.guarded_api_call", boom)
    with caplog.at_level(logging.INFO):
        assert _call_with_fallback(object(), {"score": 1}, "svc", "x") == {"score": 1}
    assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]


def test_bias_timeout_fits_inside_email_task_soft_limit(settings):
    from apps.email_engine.tasks import generate_email_task

    assert settings.BIAS_LLM_TIMEOUT < generate_email_task.soft_time_limit


def test_ollama_bias_client_uses_bounded_timeout(settings):
    from apps.agents.services.bias.helpers import _make_bias_llm_client

    settings.BIAS_LLM_BACKEND = "ollama"
    settings.BIAS_LLM_TIMEOUT = 123
    client = _make_bias_llm_client()
    assert client._http.timeout.read == 123


def test_out_of_range_llm_score_cannot_go_negative(monkeypatch, settings):
    """A local model returning -40 must not produce a negative bias score."""
    from apps.agents.services.bias.core import BiasDetector

    settings.BIAS_LLM_BACKEND = "ollama"
    detector = BiasDetector()
    monkeypatch.setattr(
        detector.prescreener,
        "prescreen_decision_email",
        lambda *a, **k: {
            "deterministic_score": 45,
            "all_clean": False,
            "findings": [{"check_name": "prohibited_language", "details": "flag"}],
        },
    )
    monkeypatch.setattr(
        "apps.agents.services.bias.core._call_with_fallback",
        lambda *a, **k: {"score": -40, "categories": [], "analysis": "x"},
    )
    result = detector.analyze("body", {"loan_amount": 1, "purpose": "personal", "decision": "denied"})
    assert result["llm_raw_score"] == 0
    assert result["score"] == 0


# --- Customer copy follows one AI switch --------------------------------------


def test_template_backend_gives_no_content_client(monkeypatch):
    from apps.email_engine.services.content_llm import make_content_llm_client

    monkeypatch.setenv("EMAIL_LLM_BACKEND", "template")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    assert make_content_llm_client() == (None, "")


def test_offers_and_marketing_follow_email_backend(monkeypatch):
    from apps.agents.services.marketing_agent import MarketingAgent
    from apps.agents.services.next_best_offer import NextBestOfferGenerator

    monkeypatch.setenv("EMAIL_LLM_BACKEND", "template")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    assert NextBestOfferGenerator().client is None
    assert MarketingAgent().client is None


def test_ollama_backend_gives_local_content_client(monkeypatch):
    from apps.email_engine.services.content_llm import make_content_llm_client

    monkeypatch.setenv("EMAIL_LLM_BACKEND", "ollama")
    client, model = make_content_llm_client()
    assert client.provider == "ollama"
    assert model


def test_nbo_template_wording_without_critical_log(caplog):
    from apps.agents.services.next_best_offer import NBO_FALLBACK_MESSAGE, NextBestOfferGenerator

    gen = NextBestOfferGenerator.__new__(NextBestOfferGenerator)
    gen.client, gen.model = None, ""

    class _App:
        pk = 1
        loan_amount = 10000
        credit_score = 700
        annual_income = 80000
        employment_type = "payg_permanent"
        purpose = "personal"

        def get_purpose_display(self):
            return "Personal"

    gen._get_customer_context = lambda application: ""
    with caplog.at_level(logging.INFO):
        result = gen._generate_messaging(_App(), [{"type": "savings", "benefit": "Earn interest"}])
    assert result["personalized_message"] == NBO_FALLBACK_MESSAGE
    assert result["offer_reasoning"] == [{"product_id": "savings", "reasoning": "Earn interest"}]
    assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]


# --- Local Llama is the default AI ------------------------------------------------


def test_llm_defaults_are_local_when_unset():
    """With no LLM variables set, emails are templates and verdicts run on local Llama."""
    import os
    import subprocess
    import sys

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"EMAIL_LLM_BACKEND", "BIAS_LLM_BACKEND", "BIAS_OLLAMA_MODEL", "EMAIL_LLM_MODEL"}
    }
    code = (
        "import django; django.setup(); from django.conf import settings as s; "
        "print(s.EMAIL_LLM_BACKEND, s.BIAS_LLM_BACKEND, s.BIAS_OLLAMA_MODEL)"
    )
    out = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.split()[-3:] == ["template", "ollama", "llama3.1:8b"]


def test_email_generator_defaults_to_template(monkeypatch):
    from apps.email_engine.services.email_generator import EmailGenerator

    monkeypatch.delenv("EMAIL_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    gen = EmailGenerator()
    assert gen.provider == "template"
    assert gen.client is None
