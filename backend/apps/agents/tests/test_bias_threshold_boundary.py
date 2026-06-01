"""Boundary-parity (M4) + monotonic requires_human_review (L18) tests."""

import os
from unittest.mock import patch

from apps.agents.services.bias.thresholds import is_severe


def test_score_equal_to_threshold_is_severe():
    # Inclusive bound: a score EQUAL to the review threshold must be severe.
    assert is_severe(70, 70) is True
    assert is_severe(60, 60) is True


def test_score_above_threshold_is_severe():
    assert is_severe(85, 70) is True


def test_score_below_threshold_is_not_severe():
    assert is_severe(69, 70) is False
    assert is_severe(59, 60) is False


@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-123"})
def test_marketing_score_exactly_at_review_threshold_blocks():
    """M4: a marketing email scoring EXACTLY 70 (== MARKETING_BIAS_THRESHOLD_REVIEW)
    must take the severe/block branch, not the moderate-LLM branch."""
    from apps.agents.services.bias.marketing import MarketingBiasDetector

    det = MarketingBiasDetector()
    # Force the deterministic pre-screen to return exactly the review threshold (70)
    # with a non-clean result so it cannot short-circuit on `all_clean`.
    fake_prescreen = {
        "deterministic_score": 70,
        "all_clean": False,
        "findings": [{"check_name": "prohibited_language", "details": "demo"}],
    }
    with patch.object(det.prescreener, "prescreen_marketing_email", return_value=fake_prescreen):
        # If the boundary were exclusive, this would call the LLM; assert it does NOT.
        with patch("apps.agents.services.bias.marketing._call_with_retry") as mock_llm:
            result = det.analyze("body text", {"loan_amount": 10000, "purpose": "personal"})
            mock_llm.assert_not_called()

    assert result["score"] == 70
    assert result["flagged"] is True
    assert result["requires_human_review"] is True
    assert result["score_source"] == "deterministic"
