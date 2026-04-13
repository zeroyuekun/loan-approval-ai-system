"""Unit tests for UnderwritingEngine — HEM lookup and class constants.

The compute_approval method is an 11-step pipeline against APRA-calibrated
thresholds; full coverage there belongs in a separate integration suite. These
tests focus on the deterministic, isolated parts: HEM table lookup, state
multipliers, income shading, and the constants the rest of the codebase
depends on.
"""

import pytest

from apps.ml_engine.services.underwriting_engine import UnderwritingEngine


@pytest.fixture
def engine():
    return UnderwritingEngine()


class TestGetHem:
    def test_single_no_deps_mid_income_returns_known_value(self, engine):
        # ("single", 0, "mid") = 2050; NSW multiplier = 1.15 → 2357
        hem = engine.get_hem("single", 0, 80_000, "NSW")
        assert hem == int(2050 * 1.15)

    def test_qld_baseline_no_multiplier_applied(self, engine):
        # QLD multiplier = 1.00, so HEM equals the base table value
        hem = engine.get_hem("single", 0, 80_000, "QLD")
        assert hem == 2050

    def test_couple_costs_more_than_single_same_inputs(self, engine):
        single = engine.get_hem("single", 2, 80_000, "NSW")
        couple = engine.get_hem("couple", 2, 80_000, "NSW")
        assert couple > single

    def test_more_dependants_costs_more(self, engine):
        zero = engine.get_hem("single", 0, 80_000, "NSW")
        three = engine.get_hem("single", 3, 80_000, "NSW")
        assert three > zero

    def test_high_income_uses_high_bracket(self, engine):
        low = engine.get_hem("single", 0, 50_000, "QLD")  # "low" bracket = 1600
        high = engine.get_hem("single", 0, 150_000, "QLD")  # "high" bracket = 2500
        assert high > low

    def test_dependants_capped_at_4(self, engine):
        # Spec: dep_key = min(dependants, 4)
        four = engine.get_hem("single", 4, 80_000, "NSW")
        ten = engine.get_hem("single", 10, 80_000, "NSW")
        assert ten == four

    def test_unknown_state_falls_back_to_unity_multiplier(self, engine):
        hem_unknown = engine.get_hem("single", 0, 80_000, "ZZ")
        hem_qld = engine.get_hem("single", 0, 80_000, "QLD")
        assert hem_unknown == hem_qld

    def test_returns_int(self, engine):
        assert isinstance(engine.get_hem("single", 0, 80_000, "NSW"), int)

    @pytest.mark.parametrize(
        "annual_income,expected_bracket_value",
        [
            (30_000, 1400),  # very_low
            (50_000, 1600),  # low
            (90_000, 2050),  # mid
            (150_000, 2500),  # high
            (250_000, 3000),  # very_high
        ],
    )
    def test_income_brackets(self, engine, annual_income, expected_bracket_value):
        # QLD baseline (no multiplier)
        hem = engine.get_hem("single", 0, annual_income, "QLD")
        assert hem == expected_bracket_value


class TestConstants:
    def test_apra_buffer_is_three_percent(self):
        assert UnderwritingEngine.ASSESSMENT_BUFFER == 0.03

    def test_floor_rate_matches_big4(self):
        assert UnderwritingEngine.FLOOR_RATE == 0.0575

    def test_credit_card_monthly_rate_three_percent(self):
        assert UnderwritingEngine.CREDIT_CARD_MONTHLY_RATE == 0.03

    def test_state_multipliers_cover_all_australian_states(self):
        expected = {"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"}
        assert set(UnderwritingEngine.STATE_HEM_MULTIPLIER.keys()) == expected

    def test_income_shading_payg_permanent_full(self):
        assert UnderwritingEngine.INCOME_SHADING["payg_permanent"] == 1.00

    def test_income_shading_self_employed_lowest(self):
        shadings = UnderwritingEngine.INCOME_SHADING
        assert shadings["self_employed"] < shadings["payg_permanent"]
        assert shadings["self_employed"] < shadings["contract"]


class TestInit:
    def test_init_no_benchmarks(self):
        eng = UnderwritingEngine()
        assert eng._benchmarks is None

    def test_init_with_benchmarks(self):
        bench = {"some_key": "value"}
        eng = UnderwritingEngine(benchmarks=bench)
        assert eng._benchmarks is bench
