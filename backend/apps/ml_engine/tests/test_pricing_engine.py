"""Parametrised tests for the risk-based pricing engine (D4).

Tests cover:
- Exact boundary assignments (PD at each tier cutoff) for both personal + home
- Segment normalisation (D2 constants, purpose strings, unified fallback)
- Decline behaviour at the top end
- Numerical edge cases (negative PD clamp, PD > 1.0)
- PricingTier semantic behaviour (approved/midpoint/band_label/to_dict)
"""

from __future__ import annotations

import pytest

from apps.ml_engine.services.pricing_engine import (
    PricingTier,
    get_tier,
)


# ---------------------------------------------------------------------------
# Personal-loan tier boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pd_score,expected_tier,expected_band",
    [
        (0.0, "A", (7.0, 9.5)),
        (0.02, "A", (7.0, 9.5)),
        (0.03, "A", (7.0, 9.5)),           # exact boundary → tier A
        (0.031, "B", (9.5, 14.0)),
        (0.07, "B", (9.5, 14.0)),          # exact boundary → tier B
        (0.10, "C", (14.0, 19.0)),
        (0.15, "C", (14.0, 19.0)),         # exact boundary → tier C
        (0.20, "D", (19.0, 24.0)),
        (0.25, "D", (19.0, 24.0)),         # exact boundary → tier D
        (0.26, "Decline", None),
        (0.50, "Decline", None),
    ],
)
def test_personal_tier_assignment(pd_score, expected_tier, expected_band):
    tier = get_tier(pd_score, "personal")
    assert tier.tier == expected_tier
    assert tier.segment == "personal"
    if expected_band is None:
        assert tier.rate_min is None
        assert tier.rate_max is None
        assert not tier.approved
    else:
        assert (tier.rate_min, tier.rate_max) == expected_band
        assert tier.approved


# ---------------------------------------------------------------------------
# Home-loan tier boundaries (tighter risk bands, lower PDs)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pd_score,expected_tier,expected_band",
    [
        (0.0, "A", (6.0, 6.5)),
        (0.005, "A", (6.0, 6.5)),
        (0.01, "A", (6.0, 6.5)),           # exact → A
        (0.02, "B", (6.5, 7.2)),
        (0.03, "B", (6.5, 7.2)),           # exact → B
        (0.05, "C", (7.2, 8.0)),
        (0.06, "C", (7.2, 8.0)),           # exact → C
        (0.08, "D", (8.0, 9.0)),
        (0.10, "D", (8.0, 9.0)),           # exact → D (top of home band)
        (0.11, "Decline", None),
        (0.30, "Decline", None),
    ],
)
def test_home_tier_assignment(pd_score, expected_tier, expected_band):
    tier = get_tier(pd_score, "home")
    assert tier.tier == expected_tier
    assert tier.segment == "home"
    if expected_band is None:
        assert not tier.approved
    else:
        assert (tier.rate_min, tier.rate_max) == expected_band
        assert tier.approved


# ---------------------------------------------------------------------------
# Segment normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_segment,resolved_segment",
    [
        ("home", "home"),
        ("home_owner_occupier", "home"),
        ("owner_occupier", "home"),
        ("investment", "home"),
        ("home_investor", "home"),
        ("investor", "home"),
        ("personal", "personal"),
        ("auto", "personal"),
        ("education", "personal"),
        ("unified", "personal"),
        ("HOME", "home"),            # case-insensitive
        ("Personal", "personal"),
    ],
)
def test_segment_normalisation(input_segment, resolved_segment):
    tier = get_tier(0.02, input_segment)
    assert tier.segment == resolved_segment


def test_unknown_segment_raises():
    with pytest.raises(ValueError, match="Unknown segment"):
        get_tier(0.02, "cryptocurrency_margin_loan")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_negative_pd_clamps_to_zero():
    # Numerical noise should not throw; clamp to 0 and return tier A.
    tier = get_tier(-0.001, "personal")
    assert tier.tier == "A"
    assert tier.pd_score == 0.0


def test_pd_above_one_routes_to_decline():
    tier = get_tier(1.5, "personal")
    assert tier.tier == "Decline"
    assert not tier.approved


def test_none_segment_defaults_to_personal():
    tier = get_tier(0.05, None)
    assert tier.segment == "personal"
    assert tier.tier == "B"


def test_non_numeric_pd_raises():
    with pytest.raises(ValueError, match="pd_score must be numeric"):
        get_tier("very-risky", "personal")


# ---------------------------------------------------------------------------
# PricingTier semantic helpers
# ---------------------------------------------------------------------------


def test_pricing_tier_midpoint():
    tier = get_tier(0.02, "personal")
    # Tier A: 7.0–9.5% → mid = 8.25
    assert tier.midpoint() == 8.25


def test_pricing_tier_midpoint_none_for_decline():
    tier = get_tier(0.30, "personal")
    assert tier.midpoint() is None


def test_pricing_tier_band_label_formatting():
    tier = get_tier(0.02, "personal")
    assert tier.band_label() == "7.0%–9.5%"


def test_decline_tier_band_label_is_not_offered():
    assert get_tier(0.30, "personal").band_label() == "Not offered"


def test_pricing_tier_to_dict_contract():
    tier = get_tier(0.05, "personal")
    d = tier.to_dict()
    required_keys = {
        "tier",
        "segment",
        "pd_score",
        "rate_min",
        "rate_max",
        "rate_midpoint",
        "rate_band",
        "approved",
        "rationale",
    }
    assert required_keys.issubset(d.keys())
    assert d["approved"] is True
    assert d["tier"] == "B"
    assert d["rate_midpoint"] == 11.75


def test_pricing_tier_rationale_includes_pd_and_tier():
    tier = get_tier(0.005, "home")
    assert "0.0050" in tier.rationale
    assert "home tier A" in tier.rationale


def test_decline_rationale_explains_cutoff_reason():
    tier = get_tier(0.30, "home")
    assert "exceeds maximum priced tier cutoff" in tier.rationale


# ---------------------------------------------------------------------------
# Cross-segment sanity checks
# ---------------------------------------------------------------------------


def test_home_is_more_conservative_than_personal_at_same_pd():
    # At PD 0.05:
    #   personal → Tier B (9.5–14%)
    #   home     → Tier C (7.2–8%)
    # Home requires TIGHTER PD bands, but rates are LOWER because home
    # loans are secured. This test pins the business-logic direction.
    personal = get_tier(0.05, "personal")
    home = get_tier(0.05, "home")
    assert home.rate_max < personal.rate_max
    # Personal at PD 0.05 is still approved at tier B, home falls to C
    # (both approved).
    assert home.approved
    assert personal.approved


def test_home_pd_ceiling_is_lower_than_personal():
    # PD 0.20: personal approved (tier D), home declined.
    assert get_tier(0.20, "personal").approved
    assert not get_tier(0.20, "home").approved
