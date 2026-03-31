"""Comprehensive tests for prediction feature engineering and input validation."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from apps.ml_engine.services.predictor import FEATURE_BOUNDS, ModelPredictor, compute_risk_grade


class TestPredictorFeatureEngineering:
    """Test that derived features match between predictor and trainer."""

    def test_derived_features_match_trainer(self):
        """ModelPredictor._add_derived_features should produce the same columns as trainer."""
        from apps.ml_engine.services.trainer import ModelTrainer

        # Build a minimal dataframe with all required columns
        df = pd.DataFrame(
            {
                "annual_income": [80000.0],
                "credit_score": [750],
                "loan_amount": [25000.0],
                "loan_term_months": [36],
                "debt_to_income": [2.0],
                "employment_length": [5],
                "has_cosigner": [0],
                "property_value": [0.0],
                "deposit_amount": [0.0],
                "monthly_expenses": [2200.0],
                "existing_credit_card_limit": [5000.0],
                "number_of_dependants": [1],
                "employment_type": ["payg_permanent"],
                "applicant_type": ["single"],
                "has_hecs": [0],
                "has_bankruptcy": [0],
                "state": ["NSW"],
                "num_credit_enquiries_6m": [1],
                "worst_arrears_months": [0],
                "num_defaults_5yr": [0],
                "credit_history_months": [120],
                "total_open_accounts": [3],
                "num_bnpl_accounts": [0],
                "is_existing_customer": [0],
                "savings_balance": [10000.0],
                "salary_credit_regularity": [0.8],
                "num_dishonours_12m": [0],
                "avg_monthly_savings_rate": [0.10],
                "days_in_overdraft_12m": [0],
                "rba_cash_rate": [4.10],
                "unemployment_rate": [3.8],
                "property_growth_12m": [5.0],
                "consumer_confidence": [95.0],
                "income_verification_gap": [1.0],
                "document_consistency_score": [0.9],
            }
        )

        # Run both transformations
        predictor_result = ModelPredictor._add_derived_features(df.copy())
        trainer = ModelTrainer()
        trainer_result = trainer.add_derived_features(df.copy())

        # Both should produce the same derived columns
        derived_cols = [
            "lvr",
            "loan_to_income",
            "credit_card_burden",
            "expense_to_income",
            "lvr_x_dti",
            "income_credit_interaction",
            "serviceability_ratio",
            "employment_stability",
            "deposit_ratio",
            "monthly_repayment_ratio",
            "net_monthly_surplus",
            "income_per_dependant",
            "credit_score_x_tenure",
            "enquiry_intensity",
            "bureau_risk_score",
            "rate_stress_buffer",
        ]
        for col in derived_cols:
            assert col in predictor_result.columns, f"Predictor missing: {col}"
            assert col in trainer_result.columns, f"Trainer missing: {col}"
            pred_val = predictor_result[col].iloc[0]
            train_val = trainer_result[col].iloc[0]
            assert abs(pred_val - train_val) < 1e-6, f"Mismatch on {col}: predictor={pred_val}, trainer={train_val}"

    def test_handles_missing_optional_fields(self):
        """Predictor should handle NaN in optional fields gracefully."""
        df = pd.DataFrame(
            {
                "annual_income": [80000.0],
                "credit_score": [750],
                "loan_amount": [25000.0],
                "loan_term_months": [36],
                "debt_to_income": [2.0],
                "employment_length": [5],
                "has_cosigner": [0],
                "property_value": [0.0],
                "deposit_amount": [0.0],
                "monthly_expenses": [np.nan],
                "existing_credit_card_limit": [np.nan],
                "number_of_dependants": [1],
                "employment_type": ["payg_permanent"],
                "applicant_type": ["single"],
                "has_hecs": [0],
                "has_bankruptcy": [0],
                "state": ["NSW"],
                "num_credit_enquiries_6m": [1],
                "worst_arrears_months": [0],
                "num_defaults_5yr": [0],
                "credit_history_months": [120],
                "total_open_accounts": [3],
                "num_bnpl_accounts": [0],
                "is_existing_customer": [0],
                "savings_balance": [np.nan],
                "salary_credit_regularity": [np.nan],
                "num_dishonours_12m": [np.nan],
                "avg_monthly_savings_rate": [np.nan],
                "days_in_overdraft_12m": [np.nan],
                "rba_cash_rate": [4.10],
                "unemployment_rate": [3.8],
                "property_growth_12m": [5.0],
                "consumer_confidence": [95.0],
                "income_verification_gap": [1.0],
                "document_consistency_score": [0.9],
            }
        )
        result = ModelPredictor._add_derived_features(df)
        # Key derived features should not be NaN
        assert not result["lvr"].isna().any()
        assert not result["loan_to_income"].isna().any()

    def test_input_validation_catches_out_of_range(self):
        """FEATURE_BOUNDS should define valid ranges for key features."""
        assert FEATURE_BOUNDS["credit_score"] == (0, 1200)
        assert FEATURE_BOUNDS["annual_income"][0] == 0
        assert FEATURE_BOUNDS["loan_amount"][1] == 5_000_000
        assert FEATURE_BOUNDS["loan_term_months"] == (1, 600)

        # Verify negative credit score is out of bounds
        low, high = FEATURE_BOUNDS["credit_score"]
        assert -100 < low  # -100 is outside valid range

    def test_feature_bounds_for_new_fields(self):
        """New bureau and macro fields should have defined bounds."""
        new_fields = [
            "num_credit_enquiries_6m",
            "worst_arrears_months",
            "num_defaults_5yr",
            "credit_history_months",
            "total_open_accounts",
            "num_bnpl_accounts",
            "savings_balance",
            "salary_credit_regularity",
            "num_dishonours_12m",
            "avg_monthly_savings_rate",
            "days_in_overdraft_12m",
            "rba_cash_rate",
            "unemployment_rate",
            "property_growth_12m",
            "consumer_confidence",
            "income_verification_gap",
            "document_consistency_score",
        ]
        for field in new_fields:
            assert field in FEATURE_BOUNDS, f"Missing FEATURE_BOUNDS for {field}"
            low, high = FEATURE_BOUNDS[field]
            assert low < high, f"Invalid bounds for {field}: ({low}, {high})"


class TestRiskGradeComprehensive:
    """Extended tests for risk grade mapping."""

    def test_extreme_high_probability(self):
        assert compute_risk_grade(1.0) == "AAA"

    def test_extreme_low_probability(self):
        assert compute_risk_grade(0.0) == "CCC"

    def test_boundary_values(self):
        # PD = 0.005 boundary: PD < 0.005 => AAA, PD >= 0.005 => AA
        # probability 0.996 => PD 0.004 < 0.005 => AAA
        assert compute_risk_grade(0.996) == "AAA"
        # probability 0.995 => PD 0.005, not < 0.005 => AA
        assert compute_risk_grade(0.995) == "AA"

    def test_all_grades_reachable(self):
        grades = set()
        for prob in [0.999, 0.993, 0.98, 0.94, 0.88, 0.75, 0.50, 0.20]:
            grades.add(compute_risk_grade(prob))
        assert len(grades) >= 5, f"Not all grades reachable, got: {grades}"

    def test_monotonic_grades(self):
        """Higher probability should give same or better grade."""
        grade_order = ["CCC", "B", "BB", "BBB", "A", "AA", "AAA"]
        probs = [0.1, 0.3, 0.5, 0.7, 0.85, 0.95, 0.99, 0.999]
        grades = [compute_risk_grade(p) for p in probs]
        indices = [grade_order.index(g) for g in grades]
        for i in range(len(indices) - 1):
            assert indices[i] <= indices[i + 1], (
                f"Grade should improve: {grades[i]} at {probs[i]} vs {grades[i + 1]} at {probs[i + 1]}"
            )
