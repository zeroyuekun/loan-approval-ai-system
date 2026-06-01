"""Boundary-parity (M4) + monotonic requires_human_review (L18) tests."""

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
