"""Unit tests for BenchmarkResolver — covers the standalone helper methods.

Methods that depend on `sub_populations` (income/loan/credit param resolvers)
are tested with a minimal sub_populations dict matching the production shape.
"""

import numpy as np
import pytest

from apps.ml_engine.services.benchmark_resolver import BenchmarkResolver


@pytest.fixture
def resolver():
    return BenchmarkResolver()


@pytest.fixture
def sub_populations():
    return {
        "first_home_buyer": {
            "income_couple_mean": 110_000,
            "income_single_mean": 75_000,
            "loan_mult_mean": 5.0,
            "loan_mult_std": 1.2,
            "credit_score_mean": 700,
            "credit_score_std": 80,
            "purpose_override": "home",
        }
    }


class TestDefaultBaseRate:
    def test_returns_apra_baseline_when_no_live_data(self, resolver):
        assert resolver.resolve_default_base_rate() == 0.0104

    def test_uses_live_npl_rate_when_provided(self):
        r = BenchmarkResolver(benchmarks={"apra_arrears": {"npl_rate": 0.02}})
        assert r.resolve_default_base_rate() == 0.02


class TestStateIndustryWeights:
    def test_returns_probability_distribution(self, resolver):
        w = resolver.get_state_industry_weights("NSW")
        assert isinstance(w, np.ndarray)
        assert np.isclose(w.sum(), 1.0)
        assert (w >= 0).all()

    def test_returns_correct_length(self, resolver):
        w = resolver.get_state_industry_weights("NSW")
        assert len(w) == len(resolver.ANZSIC_DIVISIONS)

    def test_unknown_state_returns_baseline(self, resolver):
        unknown = resolver.get_state_industry_weights("ZZ")
        # Should still sum to 1 with uniform-ish base weights
        assert np.isclose(unknown.sum(), 1.0)


class TestHelpRepaymentRate:
    def test_zero_income_zero_rate(self, resolver):
        assert resolver.get_help_repayment_rate(0) == 0.0

    def test_returns_float(self, resolver):
        assert isinstance(resolver.get_help_repayment_rate(100_000), float)

    def test_low_income_below_threshold_zero_rate(self, resolver):
        # ATO 2025-26 lowest threshold is around 56k
        assert resolver.get_help_repayment_rate(20_000) == 0.0

    def test_high_income_positive_rate(self, resolver):
        # 200k income should be in a paying bracket
        assert resolver.get_help_repayment_rate(200_000) > 0.0

    def test_rate_monotonic_non_decreasing(self, resolver):
        rates = [resolver.get_help_repayment_rate(i) for i in range(0, 250_000, 10_000)]
        for a, b in zip(rates, rates[1:], strict=False):
            assert b >= a, f"HELP rate must be non-decreasing in income, got {a} → {b}"


class TestIncomeParams:
    def test_returns_mean_sigma_arrays(self, resolver, sub_populations):
        is_couple = np.array([False, True, False])
        state_mult = np.array([1.0, 1.0, 1.0])
        mean, sigma = resolver.resolve_income_params("first_home_buyer", is_couple, state_mult, sub_populations)
        assert mean.shape == (3,)
        assert sigma.shape == (3,)

    def test_couple_higher_mean_than_single(self, resolver, sub_populations):
        is_couple = np.array([True, False])
        state_mult = np.array([1.0, 1.0])
        mean, _ = resolver.resolve_income_params("first_home_buyer", is_couple, state_mult, sub_populations)
        assert mean[0] > mean[1]


class TestLoanMultiplier:
    def test_returns_mean_std(self, resolver, sub_populations):
        mean, std = resolver.resolve_loan_multiplier("first_home_buyer", sub_populations)
        assert mean == 5.0
        assert std == 1.2


class TestCreditScoreParams:
    def test_returns_baseline_without_live_benchmarks(self, resolver, sub_populations):
        mean, std, adj = resolver.resolve_credit_score_params(
            "first_home_buyer", state_credit_adj=15, sub_populations=sub_populations
        )
        assert mean == 700
        assert std == 80
        assert adj == 15


class TestComputeProductRates:
    def test_fallback_returns_cash_rate_plus_spread(self, resolver):
        cash_rate = np.array([4.35, 4.35, 4.35])
        rates = resolver.compute_product_rates(cash_rate, "home", "first_home_buyer", n=3)
        # Without live F6 benchmarks, returns cash_rate + base_spread
        assert (rates > cash_rate).all()


class TestInit:
    def test_init_defaults(self):
        r = BenchmarkResolver()
        assert r._benchmarks is None
        assert r._use_live_macro is False
        assert r._macro_cache == {}

    def test_init_with_args(self):
        r = BenchmarkResolver(benchmarks={"a": 1}, use_live_macro=True)
        assert r._benchmarks == {"a": 1}
        assert r._use_live_macro is True
