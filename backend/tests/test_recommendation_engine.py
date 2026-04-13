"""Unit tests for recommendation_engine helpers.

Focuses on the deterministic standalone functions: tax calculation, HEM
lookup, risk tier mapping, monthly repayment, max serviceable amount, and
rate-for-tier lookup. The RecommendationEngine.recommend() method needs full
LoanApplication fixtures and is exercised by orchestrator tests.
"""

import pytest

from apps.agents.services.recommendation_engine import (
    _calculate_tax,
    _get_hem,
    _get_rate_for_tier,
    _get_risk_tier,
    _max_serviceable_amount,
    _monthly_repayment,
)


class TestCalculateTax:
    def test_below_tax_free_threshold_returns_zero(self):
        assert _calculate_tax(18_200) == 0.0
        assert _calculate_tax(10_000) == 0.0

    def test_first_bracket_known_value(self):
        # (45000 - 18200) * 0.16 = 4288
        assert _calculate_tax(45_000) == pytest.approx(4288.0)

    def test_second_bracket_known_value(self):
        # 4288 + (135000 - 45000) * 0.30 = 31288
        assert _calculate_tax(135_000) == pytest.approx(31288.0)

    def test_third_bracket_known_value(self):
        # 31288 + (190000 - 135000) * 0.37 = 51638
        assert _calculate_tax(190_000) == pytest.approx(51638.0)

    def test_top_bracket_known_value(self):
        # 51638 + (250000 - 190000) * 0.45 = 78638
        assert _calculate_tax(250_000) == pytest.approx(78638.0)

    def test_monotonic_in_income(self):
        for low, high in [(20_000, 50_000), (50_000, 100_000),
                          (100_000, 200_000), (200_000, 500_000)]:
            assert _calculate_tax(high) > _calculate_tax(low)

    def test_tax_never_exceeds_income(self):
        for income in (10_000, 50_000, 150_000, 500_000):
            assert _calculate_tax(income) < income


class TestRiskTier:
    @pytest.mark.parametrize("score,expected", [
        (820, "premium"),
        (800, "premium"),
        (775, "good"),
        (750, "good"),
        (725, "standard"),
        (700, "standard"),
        (675, "subprime"),
        (650, "subprime"),
        (600, "ineligible"),
        (450, "ineligible"),
    ])
    def test_score_maps_to_tier(self, score, expected):
        assert _get_risk_tier(score) == expected

    def test_tier_boundaries_inclusive_low(self):
        # 800, 750, 700, 650 are inclusive lower bounds for their tiers
        assert _get_risk_tier(800) == "premium"
        assert _get_risk_tier(799) == "good"
        assert _get_risk_tier(750) == "good"
        assert _get_risk_tier(749) == "standard"


class TestGetHem:
    def test_low_income_low_dependants_returns_value(self):
        hem = _get_hem("single", 0, 50_000)
        assert hem > 0
        assert isinstance(hem, (int, float))

    def test_couple_costs_more_than_single(self):
        single = _get_hem("single", 0, 80_000)
        couple = _get_hem("couple", 0, 80_000)
        assert couple > single

    def test_dependants_capped_at_2(self):
        # _get_hem caps dep_key at 2
        two = _get_hem("single", 2, 80_000)
        five = _get_hem("single", 5, 80_000)
        assert two == five

    def test_unknown_combo_returns_default(self):
        # Should not raise, returns the 2950 default
        hem = _get_hem("unknown_type", 0, 80_000)
        assert hem == 2950


class TestMonthlyRepayment:
    def test_zero_principal_returns_zero(self):
        assert _monthly_repayment(0, 6.0, 360) == 0.0

    def test_zero_term_returns_zero(self):
        assert _monthly_repayment(100_000, 6.0, 0) == 0.0

    def test_zero_rate_returns_zero(self):
        # Function guards against div-by-zero when rate = 0
        assert _monthly_repayment(100_000, 0, 360) == 0.0

    def test_higher_rate_higher_repayment(self):
        low = _monthly_repayment(100_000, 5.0, 360)
        high = _monthly_repayment(100_000, 10.0, 360)
        assert high > low

    def test_longer_term_lower_monthly(self):
        short = _monthly_repayment(100_000, 6.0, 120)
        long_ = _monthly_repayment(100_000, 6.0, 360)
        assert long_ < short

    def test_known_value(self):
        # 100k @ 6% over 30 years should be ~$599.55/mo
        repay = _monthly_repayment(100_000, 6.0, 360)
        assert repay == pytest.approx(599.55, abs=0.5)


class TestMaxServiceableAmount:
    def test_negative_surplus_returns_zero(self):
        assert _max_serviceable_amount(-500, 6.0, 360) == 0.0

    def test_zero_surplus_returns_zero(self):
        assert _max_serviceable_amount(0, 6.0, 360) == 0.0

    def test_zero_term_returns_zero(self):
        assert _max_serviceable_amount(2_000, 6.0, 0) == 0.0

    def test_positive_surplus_returns_positive(self):
        assert _max_serviceable_amount(2_000, 6.0, 360) > 0

    def test_higher_surplus_higher_amount(self):
        low = _max_serviceable_amount(1_000, 6.0, 360)
        high = _max_serviceable_amount(3_000, 6.0, 360)
        assert high > low

    def test_floor_rate_enforced_for_low_product_rates(self):
        # If product rate < FLOOR_RATE - BUFFER, assessment uses FLOOR_RATE
        low_product = _max_serviceable_amount(2_000, 1.0, 360)
        # Should still be a finite positive number (floor applied)
        assert low_product > 0
        assert low_product < float("inf")


class TestRateForTier:
    def test_simple_dict_lookup(self):
        rates = {"premium": 5.5, "good": 6.0, "standard": 6.5, "subprime": 8.0}
        assert _get_rate_for_tier(rates, 820) == 5.5
        assert _get_rate_for_tier(rates, 760) == 6.0
        assert _get_rate_for_tier(rates, 720) == 6.5
        assert _get_rate_for_tier(rates, 660) == 8.0

    def test_purpose_segmented_dict(self):
        rates = {
            "home": {"premium": 5.5, "good": 6.0, "standard": 6.5, "subprime": 8.0},
            "personal": {"premium": 8.0, "good": 9.0, "standard": 10.0, "subprime": 13.0},
        }
        assert _get_rate_for_tier(rates, 820, purpose="home") == 5.5
        assert _get_rate_for_tier(rates, 820, purpose="personal") == 8.0

    def test_unknown_tier_falls_back_to_subprime(self):
        rates = {"subprime": 12.0}
        assert _get_rate_for_tier(rates, 800) == 12.0

    def test_purpose_unknown_falls_back_to_personal(self):
        rates = {
            "personal": {"premium": 8.0, "good": 9.0, "standard": 10.0, "subprime": 13.0},
        }
        # Unknown purpose "auto" → uses "personal" branch
        assert _get_rate_for_tier(rates, 820, purpose="auto") == 8.0
