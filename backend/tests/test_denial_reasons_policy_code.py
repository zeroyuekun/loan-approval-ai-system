"""Unit tests for EmailGenerator._format_denial_reasons policy-code path.

Covers the new branch that surfaces a REASON_CODE_MAP entry when
LoanDecision.reasoning is prefixed with [Rxx] — used for policy-gate
denials (e.g. age-at-maturity R71) that don't produce SHAP values.
"""

from unittest.mock import patch

from apps.email_engine.services.email_generator import EmailGenerator


def _make_generator() -> EmailGenerator:
    """Skip API-key validation by patching the Anthropic client init."""
    with patch("apps.email_engine.services.email_generator.anthropic.Anthropic"):
        return EmailGenerator()


def test_policy_reason_code_is_expanded_to_human_text():
    gen = _make_generator()
    reasoning = "[R71] Applicant would be 70.0 years old at loan maturity; policy limit is 67."
    result = gen._format_denial_reasons(feature_importances=None, shap_values=None, reasoning=reasoning)
    assert "67-year policy limit" in result or "age at loan maturity" in result.lower()


def test_reasoning_without_policy_code_falls_back_to_generic():
    gen = _make_generator()
    reasoning = "Credit assessment flagged multiple risk factors"
    result = gen._format_denial_reasons(feature_importances=None, shap_values=None, reasoning=reasoning)
    assert result == "Credit assessment criteria not met"


def test_no_reasoning_and_no_shap_uses_generic_fallback():
    gen = _make_generator()
    result = gen._format_denial_reasons(feature_importances=None, shap_values=None, reasoning=None)
    assert result == "Credit assessment criteria not met"


def test_policy_code_takes_precedence_over_shap():
    gen = _make_generator()
    reasoning = "[R71] Age policy limit"
    shap_values = {"credit_score": -0.5, "debt_to_income": -0.3}
    result = gen._format_denial_reasons(feature_importances=None, shap_values=shap_values, reasoning=reasoning)
    assert "67-year policy limit" in result or "age at loan maturity" in result.lower()


def test_unknown_policy_code_falls_back_to_shap():
    gen = _make_generator()
    reasoning = "[R99] Unknown code"
    shap_values = {"credit_score": -0.8}
    feature_importances = {"credit_score": 0.8}
    result = gen._format_denial_reasons(
        feature_importances=feature_importances, shap_values=shap_values, reasoning=reasoning
    )
    assert result != ""
    # Should not equal generic fallback because SHAP values are present
    assert result != "Credit assessment criteria not met"
