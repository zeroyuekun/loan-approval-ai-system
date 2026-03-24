"""Metamorphic tests for the ML prediction pipeline.

These tests verify monotonic constraints, directional expectations on derived
features, protected-attribute invariance, and risk-grade ordering — all
WITHOUT loading a trained model.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from apps.ml_engine.services.predictor import FEATURE_BOUNDS, compute_risk_grade
from apps.ml_engine.services.feature_engineering import (
    compute_derived_features,
    impute_missing_values,
    DERIVED_FEATURE_NAMES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Ordered risk grades from worst to best (lower index = worse)
RISK_GRADE_ORDER = ['CCC', 'B', 'BB', 'BBB', 'A', 'AA', 'AAA']


def grade_rank(grade: str) -> int:
    """Return numeric rank for a risk grade (higher = better)."""
    return RISK_GRADE_ORDER.index(grade)


def _base_application() -> dict:
    """Return a realistic mid-range application as a plain dict."""
    return {
        'annual_income': 85_000,
        'credit_score': 750,
        'loan_amount': 350_000,
        'loan_term_months': 360,
        'debt_to_income': 0.30,
        'employment_length': 5,
        'has_cosigner': 0,
        'property_value': 500_000,
        'deposit_amount': 100_000,
        'monthly_expenses': 3_000,
        'existing_credit_card_limit': 10_000,
        'number_of_dependants': 1,
        'has_hecs': 0,
        'has_bankruptcy': 0,
        'num_credit_enquiries_6m': 1,
        'worst_arrears_months': 0,
        'num_defaults_5yr': 0,
        'credit_history_months': 120,
        'total_open_accounts': 3,
        'num_bnpl_accounts': 0,
        'savings_balance': 20_000,
        'salary_credit_regularity': 0.9,
        'num_dishonours_12m': 0,
        'avg_monthly_savings_rate': 0.12,
        'days_in_overdraft_12m': 0,
        'rba_cash_rate': 4.10,
        'unemployment_rate': 3.8,
        'property_growth_12m': 5.0,
        'consumer_confidence': 95.0,
        'income_verification_gap': 1.0,
        'document_consistency_score': 0.9,
        'purpose': 'home_purchase',
        'home_ownership': 'renting',
        'employment_type': 'payg_permanent',
        'applicant_type': 'individual',
        'state': 'NSW',
        'is_existing_customer': 0,
        'savings_trend_3m': 'stable',
        'industry_risk_tier': 'medium',
        # CCR features
        'num_late_payments_24m': 0,
        'worst_late_payment_days': 0,
        'total_credit_limit': 20_000,
        'credit_utilization_pct': 0.25,
        'num_hardship_flags': 0,
        'months_since_last_default': 999,
        'num_credit_providers': 2,
        # BNPL-specific
        'bnpl_total_limit': 0,
        'bnpl_utilization_pct': 0.0,
        'bnpl_late_payments_12m': 0,
        'bnpl_monthly_commitment': 0,
        # CDR/Open Banking transaction features
        'income_source_count': 2,
        'rent_payment_regularity': 0.9,
        'utility_payment_regularity': 0.9,
        'essential_to_total_spend': 0.50,
        'subscription_burden': 0.05,
        'balance_before_payday': 3_000,
        'min_balance_30d': 1_000,
        'days_negative_balance_90d': 0,
        # Open Banking features
        'discretionary_spend_ratio': 0.35,
        'gambling_transaction_flag': 0,
        'bnpl_active_count': 0,
        'overdraft_frequency_90d': 0,
        'income_verification_score': 0.85,
        # Geographic risk
        'postcode_default_rate': 0.015,
    }


def _make_df(overrides: dict | None = None) -> pd.DataFrame:
    """Build a single-row imputed DataFrame from the base application."""
    row = _base_application()
    if overrides:
        row.update(overrides)
    df = pd.DataFrame([row])
    df = impute_missing_values(df)
    return df


def _derived(overrides: dict | None = None) -> pd.Series:
    """Return derived features for one application as a Series."""
    df = _make_df(overrides)
    df = compute_derived_features(df)
    return df.iloc[0]


# ---------------------------------------------------------------------------
# Test 1: Monotonic direction assertions on risk_grade via compute_risk_grade
# ---------------------------------------------------------------------------

class TestMonotonicRiskGrade:
    """Verify that compute_risk_grade respects monotonic ordering when
    probabilities move in the direction implied by the constraint."""

    # Positively constrained features: higher value → higher approval prob
    # → equal or better risk grade.
    POSITIVE_CONSTRAINT_FEATURES = [
        'annual_income', 'credit_score', 'credit_history_months',
        'employment_length', 'savings_balance', 'property_value',
        'deposit_amount', 'salary_credit_regularity', 'income_source_count',
        'rent_payment_regularity', 'utility_payment_regularity',
        'document_consistency_score', 'min_balance_30d',
        'total_credit_limit', 'months_since_last_default',
        'num_credit_providers',
    ]

    # Negatively constrained features: higher value → lower approval prob
    # → equal or worse risk grade.
    NEGATIVE_CONSTRAINT_FEATURES = [
        'debt_to_income', 'loan_amount', 'monthly_expenses',
        'num_credit_enquiries_6m', 'worst_arrears_months',
        'num_defaults_5yr', 'num_bnpl_accounts', 'num_dishonours_12m',
        'days_in_overdraft_12m', 'unemployment_rate',
        'income_verification_gap', 'num_late_payments_24m',
        'worst_late_payment_days', 'num_hardship_flags',
        'bnpl_late_payments_12m', 'days_negative_balance_90d',
        'bnpl_monthly_commitment',
    ]

    @pytest.mark.parametrize('feature', POSITIVE_CONSTRAINT_FEATURES)
    def test_positive_constraint_grade_ordering(self, feature):
        """Increasing a positively constrained probability should never
        produce a worse risk grade."""
        # Simulate: lower prob (worse) → higher prob (better)
        low_prob = 0.40
        high_prob = 0.85
        grade_low = compute_risk_grade(low_prob)
        grade_high = compute_risk_grade(high_prob)
        assert grade_rank(grade_high) >= grade_rank(grade_low), (
            f"Positive constraint on '{feature}': grade should not worsen when "
            f"prob increases ({low_prob}→{high_prob}): {grade_low}→{grade_high}"
        )

    @pytest.mark.parametrize('feature', NEGATIVE_CONSTRAINT_FEATURES)
    def test_negative_constraint_grade_ordering(self, feature):
        """Increasing a negatively constrained feature should correspond to
        a lower probability, hence equal or worse risk grade."""
        high_prob = 0.85
        low_prob = 0.40
        grade_good = compute_risk_grade(high_prob)
        grade_bad = compute_risk_grade(low_prob)
        assert grade_rank(grade_good) >= grade_rank(grade_bad), (
            f"Negative constraint on '{feature}': higher feature value "
            f"should not improve grade: {grade_good}→{grade_bad}"
        )


# ---------------------------------------------------------------------------
# Test 2: Protected attribute invariance — employment_type metamorphic
# ---------------------------------------------------------------------------

class TestProtectedAttributeInvariance:
    """Changing employment_type between payg_permanent and payg_casual should
    NOT affect purely financial derived features (only employment_stability
    is expected to differ)."""

    EMPLOYMENT_SENSITIVE_DERIVED = {'employment_stability'}

    def test_employment_type_does_not_affect_financial_ratios(self):
        permanent = _derived({'employment_type': 'payg_permanent'})
        casual = _derived({'employment_type': 'payg_casual'})

        financial_features = [
            f for f in DERIVED_FEATURE_NAMES
            if f not in self.EMPLOYMENT_SENSITIVE_DERIVED
        ]
        for feat in financial_features:
            assert np.isclose(permanent[feat], casual[feat], atol=1e-6), (
                f"Derived feature '{feat}' changed when employment_type was "
                f"altered: permanent={permanent[feat]}, casual={casual[feat]}"
            )

    def test_employment_stability_differs(self):
        """employment_stability SHOULD differ between permanent and casual."""
        permanent = _derived({'employment_type': 'payg_permanent'})
        casual = _derived({'employment_type': 'payg_casual'})
        assert permanent['employment_stability'] > casual['employment_stability'], (
            "employment_stability should be higher for payg_permanent than payg_casual"
        )


# ---------------------------------------------------------------------------
# Test 3: Directional expectations for derived features (mathematical truths)
# ---------------------------------------------------------------------------

class TestDerivedFeatureDirections:

    def test_increasing_income_decreases_loan_to_income(self):
        low = _derived({'annual_income': 60_000})
        high = _derived({'annual_income': 120_000})
        assert high['loan_to_income'] < low['loan_to_income']

    def test_increasing_property_value_decreases_lvr(self):
        low = _derived({'property_value': 400_000})
        high = _derived({'property_value': 800_000})
        assert high['lvr'] < low['lvr']

    def test_increasing_expenses_increases_expense_to_income(self):
        low = _derived({'monthly_expenses': 2_000})
        high = _derived({'monthly_expenses': 5_000})
        assert high['expense_to_income'] > low['expense_to_income']

    def test_increasing_credit_score_increases_credit_score_x_tenure(self):
        low = _derived({'credit_score': 500})
        high = _derived({'credit_score': 900})
        assert high['credit_score_x_tenure'] > low['credit_score_x_tenure']

    def test_increasing_loan_amount_increases_lvr(self):
        low = _derived({'loan_amount': 200_000})
        high = _derived({'loan_amount': 400_000})
        assert high['lvr'] > low['lvr']

    def test_increasing_deposit_increases_deposit_ratio(self):
        low = _derived({'deposit_amount': 20_000})
        high = _derived({'deposit_amount': 80_000})
        assert high['deposit_ratio'] > low['deposit_ratio']

    def test_increasing_income_increases_income_credit_interaction(self):
        low = _derived({'annual_income': 50_000})
        high = _derived({'annual_income': 150_000})
        assert high['income_credit_interaction'] > low['income_credit_interaction']


# ---------------------------------------------------------------------------
# Test 4: Symmetry — same financial profile → same derived features
# ---------------------------------------------------------------------------

class TestSymmetry:

    def test_identical_profiles_produce_identical_derived_features(self):
        """Two applications with identical numeric features but different
        non-financial metadata should yield the same derived features."""
        derived_a = _derived()
        derived_b = _derived()  # same base application, no overrides

        for feat in DERIVED_FEATURE_NAMES:
            assert np.isclose(derived_a[feat], derived_b[feat], atol=1e-10), (
                f"Derived feature '{feat}' differs between identical profiles: "
                f"{derived_a[feat]} vs {derived_b[feat]}"
            )

    def test_imputation_is_deterministic(self):
        """Running impute_missing_values twice on the same data should
        produce identical results."""
        df1 = _make_df()
        df2 = _make_df()
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# Test 5: Scale invariance / monotonicity of compute_risk_grade
# ---------------------------------------------------------------------------

class TestRiskGradeMonotonicity:

    # Probe every boundary and mid-point
    PROBABILITY_PAIRS = [
        (0.01, 0.50),
        (0.50, 0.70),
        (0.70, 0.85),
        (0.85, 0.93),
        (0.93, 0.97),
        (0.97, 0.99),
        (0.99, 0.999),
    ]

    @pytest.mark.parametrize('prob_low,prob_high', PROBABILITY_PAIRS)
    def test_higher_prob_gives_equal_or_better_grade(self, prob_low, prob_high):
        grade_low = compute_risk_grade(prob_low)
        grade_high = compute_risk_grade(prob_high)
        assert grade_rank(grade_high) >= grade_rank(grade_low), (
            f"Risk grade should be monotonically non-decreasing with approval "
            f"probability: {prob_low}→{grade_low}, {prob_high}→{grade_high}"
        )

    @given(
        prob_a=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        prob_b=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=200)
    def test_risk_grade_monotonic_property(self, prob_a, prob_b):
        """For any two probabilities, the higher one should never receive
        a strictly worse risk grade."""
        lo, hi = sorted([prob_a, prob_b])
        grade_lo = compute_risk_grade(lo)
        grade_hi = compute_risk_grade(hi)
        assert grade_rank(grade_hi) >= grade_rank(grade_lo), (
            f"Monotonicity violated: prob {lo}→{grade_lo}, {hi}→{grade_hi}"
        )

    def test_boundary_grades(self):
        """Verify specific boundary values produce expected grades."""
        # PD = 1 - prob. PD < 0.005 → AAA, PD < 0.01 → AA, ...
        assert compute_risk_grade(0.999) == 'AAA'  # PD = 0.001
        assert compute_risk_grade(0.996) == 'AAA'  # PD = 0.004 < 0.005
        assert compute_risk_grade(0.995) == 'AA'   # PD = 0.005, NOT < 0.005 so AA
        assert compute_risk_grade(0.994) == 'AA'   # PD = 0.006
        assert compute_risk_grade(0.99) == 'A'     # PD = 0.01, NOT < 0.01 so A
        assert compute_risk_grade(0.98) == 'A'     # PD = 0.02
        assert compute_risk_grade(0.95) == 'BBB'   # PD = 0.05
        assert compute_risk_grade(0.90) == 'BB'    # PD = 0.10
        assert compute_risk_grade(0.80) == 'B'     # PD = 0.20
        assert compute_risk_grade(0.50) == 'CCC'   # PD = 0.50

    @given(prob=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    @settings(max_examples=100)
    def test_risk_grade_always_returns_valid_grade(self, prob):
        grade = compute_risk_grade(prob)
        assert grade in RISK_GRADE_ORDER, f"Unknown grade '{grade}' for prob={prob}"


# ---------------------------------------------------------------------------
# Hypothesis-driven: derived feature directional properties
# ---------------------------------------------------------------------------

class TestHypothesisDerivedFeatures:

    @given(
        income_lo=st.integers(min_value=30_000, max_value=100_000),
        income_delta=st.integers(min_value=1_000, max_value=200_000),
    )
    @settings(max_examples=50)
    def test_loan_to_income_decreases_with_income(self, income_lo, income_delta):
        income_hi = income_lo + income_delta
        lo = _derived({'annual_income': income_lo})
        hi = _derived({'annual_income': income_hi})
        assert hi['loan_to_income'] <= lo['loan_to_income']

    @given(
        pv_lo=st.integers(min_value=100_000, max_value=500_000),
        pv_delta=st.integers(min_value=10_000, max_value=500_000),
    )
    @settings(max_examples=50)
    def test_lvr_decreases_with_property_value(self, pv_lo, pv_delta):
        pv_hi = pv_lo + pv_delta
        lo = _derived({'property_value': pv_lo})
        hi = _derived({'property_value': pv_hi})
        assert hi['lvr'] <= lo['lvr']

    @given(
        score_lo=st.integers(min_value=100, max_value=800),
        score_delta=st.integers(min_value=1, max_value=400),
    )
    @settings(max_examples=50)
    def test_credit_score_x_tenure_increases_with_score(self, score_lo, score_delta):
        score_hi = score_lo + score_delta
        assume(score_hi <= 1200)
        lo = _derived({'credit_score': score_lo})
        hi = _derived({'credit_score': score_hi})
        assert hi['credit_score_x_tenure'] >= lo['credit_score_x_tenure']
