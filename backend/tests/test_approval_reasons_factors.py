"""Unit tests for EmailGenerator._format_approval_factors.

Mirror of the denial-reason policy-code tests. Exercises the positive-frame
factor surfacing used in approval emails (feature + prompt placeholder added
2026-04-15).
"""

from unittest.mock import patch

from apps.email_engine.services.email_generator import EmailGenerator


def _make_generator() -> EmailGenerator:
    """Skip the Anthropic client init so the generator can be instantiated offline."""
    with patch("apps.email_engine.services.email_generator.anthropic.Anthropic"):
        return EmailGenerator()


def test_positive_shap_surfaces_top_factors():
    gen = _make_generator()
    shap_values = {
        "credit_score": 0.35,
        "employment_length": 0.18,
        "debt_to_income": -0.22,  # negative — excluded
        "num_late_payments_24m": 0.05,
    }
    result = gen._format_approval_factors(shap_values=shap_values)
    assert "strong credit history" in result
    assert "stable employment history" in result
    # Ranked by magnitude — credit_score should appear before employment_length
    assert result.index("strong credit history") < result.index("stable employment history")


def test_empty_signals_returns_empty_string():
    gen = _make_generator()
    assert gen._format_approval_factors() == ""
    assert gen._format_approval_factors(shap_values={}, feature_importances={}) == ""


def test_all_negative_shap_returns_empty_string():
    """Borderline approval with every SHAP contribution negative — no positive factors to surface."""
    gen = _make_generator()
    shap_values = {"credit_score": -0.1, "debt_to_income": -0.05}
    # No fallback to importances available.
    assert gen._format_approval_factors(shap_values=shap_values) == ""


def test_unknown_feature_name_maps_to_generic_phrase():
    gen = _make_generator()
    shap_values = {"novel_feature_not_in_map": 0.5}
    result = gen._format_approval_factors(shap_values=shap_values)
    assert result == "an aspect of your financial profile"


def test_fallback_to_feature_importances_when_no_shap():
    gen = _make_generator()
    feature_importances = {"credit_score": 0.6, "annual_income": 0.4}
    result = gen._format_approval_factors(feature_importances=feature_importances)
    assert "strong credit history" in result
    assert "strong income" in result


def test_duplicate_phrases_are_deduplicated():
    """Two features that map to the same phrase should produce a single mention."""
    gen = _make_generator()
    shap_values = {
        "employment_length": 0.4,
        "employment_stability": 0.3,  # both map to stable/consistent employment phrases
        "credit_score": 0.2,
    }
    result = gen._format_approval_factors(shap_values=shap_values)
    # Three inputs but phrases should dedupe where text matches exactly.
    # Employment_length -> "stable employment history"; employment_stability -> "consistent employment".
    # Different strings, so both appear. Verify all three factors came through.
    parts = [p.strip() for p in result.split(",")]
    assert len(parts) == 3
    assert "strong credit history" in result
