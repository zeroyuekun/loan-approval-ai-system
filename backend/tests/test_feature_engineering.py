"""Tests for the shared feature engineering module.

Verifies that compute_derived_features and impute_missing_values produce
correct, bounded, and consistent results — the core contract that prevents
training/serving skew.
"""

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.feature_engineering import (
    DEFAULT_IMPUTATION_VALUES,
    DERIVED_FEATURE_NAMES,
    compute_derived_features,
    impute_missing_values,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def complete_feature_row():
    """A single-row dict with all columns needed by compute_derived_features.

    Values represent a typical Australian home loan applicant.
    """
    return {
        "annual_income": 85000.0,
        "credit_score": 780,
        "loan_amount": 550000.0,
        "loan_term_months": 360,
        "debt_to_income": 3.5,
        "employment_length": 5,
        "has_cosigner": 0,
        "property_value": 700000.0,
        "deposit_amount": 150000.0,
        "monthly_expenses": 3200.0,
        "existing_credit_card_limit": 8000.0,
        "number_of_dependants": 1,
        "has_hecs": 0,
        "has_bankruptcy": 0,
        "purpose": "home",
        "home_ownership": "mortgage",
        "employment_type": "payg_permanent",
        "applicant_type": "couple",
        "state": "NSW",
        # Bureau features
        "num_credit_enquiries_6m": 2,
        "worst_arrears_months": 0,
        "num_defaults_5yr": 0,
        "credit_history_months": 144,
        "total_open_accounts": 4,
        "num_bnpl_accounts": 0,
        # Behavioural features
        "is_existing_customer": 1,
        "savings_balance": 25000.0,
        "salary_credit_regularity": 0.95,
        "num_dishonours_12m": 0,
        "avg_monthly_savings_rate": 0.12,
        "days_in_overdraft_12m": 0,
        # Macroeconomic
        "rba_cash_rate": 4.10,
        "unemployment_rate": 3.8,
        "property_growth_12m": 5.0,
        "consumer_confidence": 95.0,
        # Application integrity
        "income_verification_gap": 1.0,
        "document_consistency_score": 0.92,
    }


@pytest.fixture(scope="module")
def single_row_df(complete_feature_row):
    """DataFrame with one complete row."""
    return pd.DataFrame([complete_feature_row])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeDerivedFeatures:
    def test_compute_derived_features_creates_all_columns(self, single_row_df):
        """All 16 DERIVED_FEATURE_NAMES must be present after computation."""
        result = compute_derived_features(single_row_df)
        for col in DERIVED_FEATURE_NAMES:
            assert col in result.columns, f"Missing derived column: {col}"

    def test_zero_income_no_division_error(self, complete_feature_row):
        """annual_income=0 must not produce inf or NaN in any derived feature."""
        row = {**complete_feature_row, "annual_income": 0.0}
        df = pd.DataFrame([row])
        result = compute_derived_features(df)
        for col in DERIVED_FEATURE_NAMES:
            val = result[col].iloc[0]
            assert np.isfinite(val), f"Derived feature '{col}' is not finite ({val}) when income=0"

    def test_zero_property_value_lvr_is_zero(self, complete_feature_row):
        """property_value=0 must produce lvr=0 and lvr_x_dti=0."""
        row = {**complete_feature_row, "property_value": 0.0}
        df = pd.DataFrame([row])
        result = compute_derived_features(df)
        assert result["lvr"].iloc[0] == 0.0
        assert result["lvr_x_dti"].iloc[0] == 0.0

    def test_home_loan_lvr_correct(self, complete_feature_row):
        """loan=550000, property=700000 must give LVR ~= 0.7857."""
        row = {**complete_feature_row, "loan_amount": 550000.0, "property_value": 700000.0}
        df = pd.DataFrame([row])
        result = compute_derived_features(df)
        expected_lvr = 550000.0 / 700000.0
        assert result["lvr"].iloc[0] == pytest.approx(expected_lvr, rel=1e-6)

    @pytest.mark.parametrize(
        "emp_type,expected_weight",
        [
            ("payg_permanent", 1.0),
            ("contract", 0.7),
            ("self_employed", 0.6),
            ("payg_casual", 0.4),
        ],
    )
    def test_employment_stability_weights(self, complete_feature_row, emp_type, expected_weight):
        """Each employment type with employment_length=5 must produce the
        correct stability score = weight * log1p(5)."""
        row = {**complete_feature_row, "employment_type": emp_type, "employment_length": 5}
        df = pd.DataFrame([row])
        result = compute_derived_features(df)
        expected = expected_weight * np.log1p(5)
        assert result["employment_stability"].iloc[0] == pytest.approx(expected, rel=1e-6)

    def test_bureau_risk_score_formula(self, complete_feature_row):
        """Known inputs must produce the exact bureau_risk_score."""
        row = {
            **complete_feature_row,
            "num_credit_enquiries_6m": 3,
            "worst_arrears_months": 2,
            "num_defaults_5yr": 1,
            "num_bnpl_accounts": 2,
        }
        df = pd.DataFrame([row])
        result = compute_derived_features(df)
        expected = 3 * 0.3 + 2 * 0.4 + 1 * 0.2 + 2 * 0.1
        assert result["bureau_risk_score"].iloc[0] == pytest.approx(expected, rel=1e-9)


class TestImputeMissingValues:
    def test_impute_missing_values_fills_nan(self):
        """DataFrame with NaN in optional fields must have no NaN after
        imputation for those fields."""
        data = {
            "annual_income": [80000.0],
            "monthly_expenses": [np.nan],
            "existing_credit_card_limit": [np.nan],
            "property_value": [np.nan],
            "deposit_amount": [np.nan],
            "num_credit_enquiries_6m": [np.nan],
            "worst_arrears_months": [np.nan],
            "savings_balance": [np.nan],
        }
        df = pd.DataFrame(data)
        result = impute_missing_values(df)
        for col in data:
            assert result[col].notna().all(), f"Column '{col}' still has NaN after imputation"

    def test_impute_custom_values(self):
        """Custom imputation dict must override defaults."""
        data = {
            "monthly_expenses": [np.nan],
            "savings_balance": [np.nan],
        }
        custom = {
            "monthly_expenses": 9999.0,
            "savings_balance": 42.0,
        }
        df = pd.DataFrame(data)
        result = impute_missing_values(df, imputation_values=custom)
        assert result["monthly_expenses"].iloc[0] == 9999.0
        assert result["savings_balance"].iloc[0] == 42.0


class TestBatchConsistency:
    def test_batch_500_rows_consistent(self):
        """Generate 500 rows from DataGenerator, run compute_derived_features,
        and verify no NaN in derived output columns."""
        from apps.ml_engine.services.data_generator import DataGenerator

        gen = DataGenerator()
        df = gen.generate(num_records=500, random_seed=42)

        # Impute first, then compute derived features
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        for col in DERIVED_FEATURE_NAMES:
            nan_count = result[col].isna().sum()
            assert nan_count == 0, f"Derived column '{col}' has {nan_count} NaN values in 500-row batch"
            inf_count = np.isinf(result[col]).sum()
            assert inf_count == 0, f"Derived column '{col}' has {inf_count} inf values in 500-row batch"
