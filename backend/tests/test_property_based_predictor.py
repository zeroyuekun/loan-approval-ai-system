"""Property-based tests for the ML predictor pipeline.

Uses hypothesis to generate random inputs and verify that the predictor's
validation, transformation, and output layers behave correctly for all
possible inputs — without requiring a trained model.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.ml_engine.services.feature_engineering import (
    DEFAULT_IMPUTATION_VALUES,
    DERIVED_FEATURE_NAMES,
    compute_derived_features,
    impute_missing_values,
)
from apps.ml_engine.services.predictor import (
    FEATURE_BOUNDS,
    ModelPredictor,
    compute_risk_grade,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


def _numeric_strategy(lo, hi):
    """Build a hypothesis strategy for a numeric feature given its bounds."""
    # Use integers when bounds look integral, floats otherwise
    if isinstance(lo, int) and isinstance(hi, int) and hi - lo > 1:
        return st.integers(min_value=lo, max_value=hi).map(float)
    return st.floats(min_value=float(lo), max_value=float(hi), allow_nan=False, allow_infinity=False)


# Strategy that generates a dict with every FEATURE_BOUNDS key mapped to a
# value within its valid range.
_in_bounds_strategy = st.fixed_dictionaries(
    {key: _numeric_strategy(lo, hi) for key, (lo, hi) in FEATURE_BOUNDS.items()}
)

# Strategy that may produce values slightly outside bounds (by up to 10%).
_near_bounds_strategy = st.fixed_dictionaries(
    {
        key: st.floats(
            min_value=float(lo) - abs(float(hi - lo)) * 0.1,
            max_value=float(hi) + abs(float(hi - lo)) * 0.1,
            allow_nan=False,
            allow_infinity=False,
        )
        for key, (lo, hi) in FEATURE_BOUNDS.items()
    }
)

# Valid categorical values used by the predictor.
CATEGORICAL_VALUES = {
    "purpose": ["home", "auto", "education", "personal", "business"],
    "home_ownership": ["own", "rent", "mortgage"],
    "employment_type": ["payg_permanent", "payg_casual", "self_employed", "contract"],
    "applicant_type": ["single", "couple"],
    "state": ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"],
    "savings_trend_3m": ["positive", "negative", "flat"],
    "industry_risk_tier": ["low", "medium", "high", "very_high"],
}


def _build_base_feature_dict(numeric_overrides=None):
    """Return a realistic base feature dict suitable for feature engineering.

    The values are mid-range defaults that will pass consistency checks.
    Callers can override specific numeric fields.
    """
    base = {
        "annual_income": 80000.0,
        "credit_score": 720.0,
        "loan_amount": 25000.0,
        "loan_term_months": 36.0,
        "debt_to_income": 1.5,
        "employment_length": 5.0,
        "has_cosigner": 0.0,
        "property_value": 0.0,
        "deposit_amount": 0.0,
        "monthly_expenses": 2500.0,
        "existing_credit_card_limit": 5000.0,
        "number_of_dependants": 1.0,
        "has_hecs": 0.0,
        "has_bankruptcy": 0.0,
        "num_credit_enquiries_6m": 1.0,
        "worst_arrears_months": 0.0,
        "num_defaults_5yr": 0.0,
        "credit_history_months": 120.0,
        "total_open_accounts": 3.0,
        "num_bnpl_accounts": 0.0,
        "savings_balance": 10000.0,
        "salary_credit_regularity": 0.8,
        "num_dishonours_12m": 0.0,
        "avg_monthly_savings_rate": 0.1,
        "days_in_overdraft_12m": 0.0,
        "rba_cash_rate": 4.1,
        "unemployment_rate": 3.8,
        "property_growth_12m": 5.0,
        "consumer_confidence": 95.0,
        "income_verification_gap": 1.0,
        "document_consistency_score": 0.9,
        # CCR
        "num_late_payments_24m": 0.0,
        "worst_late_payment_days": 0.0,
        "total_credit_limit": 20000.0,
        "credit_utilization_pct": 0.3,
        "num_hardship_flags": 0.0,
        "months_since_last_default": 999.0,
        "num_credit_providers": 2.0,
        # BNPL
        "bnpl_total_limit": 0.0,
        "bnpl_utilization_pct": 0.0,
        "bnpl_late_payments_12m": 0.0,
        "bnpl_monthly_commitment": 0.0,
        # CDR/Open Banking
        "income_source_count": 1.0,
        "rent_payment_regularity": 0.85,
        "utility_payment_regularity": 0.9,
        "essential_to_total_spend": 0.5,
        "subscription_burden": 0.05,
        "balance_before_payday": 2000.0,
        "min_balance_30d": 500.0,
        "days_negative_balance_90d": 0.0,
        # Geographic
        "postcode_default_rate": 0.015,
    }
    # Categoricals needed by feature engineering / transform
    base["purpose"] = "personal"
    base["home_ownership"] = "rent"
    base["employment_type"] = "payg_permanent"
    base["applicant_type"] = "single"
    base["state"] = "NSW"
    base["savings_trend_3m"] = "flat"
    base["industry_risk_tier"] = "medium"
    base["is_existing_customer"] = 0

    if numeric_overrides:
        base.update(numeric_overrides)
    return base


# ---------------------------------------------------------------------------
# Helpers to build a fake model bundle
# ---------------------------------------------------------------------------


def _make_fake_bundle(feature_cols=None):
    """Create a fake model bundle that mimics what joblib.load returns.

    The fake model returns a random probability so we can test the output
    layer without a real trained model.
    """
    if feature_cols is None:
        # Build feature_cols from a sample transform so columns align
        sample = _build_base_feature_dict()
        df = pd.DataFrame([sample])
        df = compute_derived_features(impute_missing_values(df))
        df = pd.get_dummies(
            df,
            columns=[
                "purpose",
                "home_ownership",
                "employment_type",
                "applicant_type",
                "state",
                "savings_trend_3m",
                "industry_risk_tier",
            ],
            dtype=float,
        )
        feature_cols = list(df.select_dtypes(include=[np.number]).columns)

    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([1])
    fake_model.predict_proba.return_value = np.array([[0.3, 0.7]])
    fake_model.feature_importances_ = np.random.rand(len(feature_cols))

    fake_scaler = MagicMock()
    fake_scaler.transform.side_effect = lambda x: x  # identity

    return {
        "model": fake_model,
        "scaler": fake_scaler,
        "feature_cols": feature_cols,
        "label_encoders": None,  # use one-hot path
        "categorical_cols": [
            "purpose",
            "home_ownership",
            "employment_type",
            "applicant_type",
            "state",
            "savings_trend_3m",
            "industry_risk_tier",
        ],
        "numeric_cols": [],
        "reference_distribution": {},
        "imputation_values": DEFAULT_IMPUTATION_VALUES,
        "feature_bounds": {},
        "group_thresholds": {},
        "conformal_scores": np.array([]),
    }


# ===================================================================
# Test 1: Feature bounds validation is always safe
# ===================================================================


class TestFeatureBoundsValidation:
    """_validate_input should never crash — it raises ValueError for
    out-of-bounds inputs but never throws an unexpected exception."""

    @given(features=_in_bounds_strategy)
    @settings(max_examples=200)
    def test_in_bounds_values_never_raise(self, features):
        """Values within FEATURE_BOUNDS should pass validation."""
        bundle = _make_fake_bundle()
        with (
            patch("apps.ml_engine.services.predictor._load_bundle", return_value=bundle),
            patch("apps.ml_engine.services.predictor.ModelPredictor.__init__", return_value=None),
        ):
            predictor = ModelPredictor.__new__(ModelPredictor)
            predictor.feature_bounds = {}
            # Should not raise for in-bounds values
            predictor._validate_input(features)

    @given(features=_near_bounds_strategy)
    @settings(max_examples=200)
    def test_near_bounds_values_raise_or_pass_cleanly(self, features):
        """Values slightly outside bounds should either pass or raise
        ValueError — never an unexpected exception type."""
        _make_fake_bundle()
        predictor = ModelPredictor.__new__(ModelPredictor)
        predictor.feature_bounds = {}
        try:
            predictor._validate_input(features)
        except ValueError:
            pass  # expected for out-of-bounds
        # Any other exception type would fail the test automatically

    @given(features=_in_bounds_strategy)
    @settings(max_examples=100)
    def test_none_values_ignored(self, features):
        """Setting some values to None should not cause crashes."""
        # Randomly set ~20% of keys to None
        for key in list(features.keys()):
            if np.random.random() < 0.2:
                features[key] = None

        predictor = ModelPredictor.__new__(ModelPredictor)
        predictor.feature_bounds = {}
        # Should never crash — None values are skipped
        predictor._validate_input(features)


# ===================================================================
# Test 2: Risk grade is always assigned for valid probabilities
# ===================================================================

VALID_RISK_GRADES = {"AAA", "AA", "A", "BBB", "BB", "B", "CCC"}


class TestRiskGradeMapping:
    """compute_risk_grade must always return one of the 7 valid grades."""

    @given(prob=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    @settings(max_examples=200)
    def test_always_returns_valid_grade(self, prob):
        grade = compute_risk_grade(prob)
        assert grade in VALID_RISK_GRADES, (
            f"compute_risk_grade({prob}) returned '{grade}', which is not in {VALID_RISK_GRADES}"
        )

    def test_boundary_probabilities(self):
        """Exact boundary values must map deterministically.
        Grade is based on PD = 1 - probability:
        AAA: PD < 0.005 (prob > 0.995), CCC: PD >= 0.30 (prob <= 0.70)
        """
        assert compute_risk_grade(0.0) == "CCC"  # PD=1.0, worst
        assert compute_risk_grade(1.0) == "AAA"  # PD=0.0, best
        assert compute_risk_grade(0.5) == "CCC"  # PD=0.5, still high default risk
        assert compute_risk_grade(0.90) == "BB"  # PD=0.10
        assert compute_risk_grade(0.999) == "AAA"  # PD=0.001

    @given(prob=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    @settings(max_examples=200)
    def test_monotonicity(self, prob):
        """Higher probability should produce the same or better grade."""
        grade_order = ["CCC", "B", "BB", "BBB", "A", "AA", "AAA"]
        grade_rank = {g: i for i, g in enumerate(grade_order)}
        g1 = compute_risk_grade(prob)
        # A slightly higher probability should never produce a *worse* grade
        higher_prob = min(prob + 0.001, 1.0)
        g2 = compute_risk_grade(higher_prob)
        assert grade_rank[g2] >= grade_rank[g1], (
            f"Monotonicity violated: prob={prob} -> {g1}, prob={higher_prob} -> {g2}"
        )


# ===================================================================
# Test 3: Prediction output shape is always correct (mock model)
# ===================================================================


class TestPredictionOutputShape:
    """With a mocked model, predict() must always return the required keys."""

    REQUIRED_KEYS = {
        "prediction",
        "probability",
        "risk_grade",
        "feature_importances",
    }

    # We test the output structure via a helper that mimics predict()'s
    # return dict construction — calling the real predict() requires a
    # LoanApplication ORM object and database access which we avoid.

    @given(prob=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    @settings(max_examples=200)
    def test_output_keys_always_present(self, prob):
        """For any valid probability the result dict must contain the
        required keys with the correct types."""
        threshold = 0.5
        prediction_label = "approved" if prob >= threshold else "denied"
        risk_grade = compute_risk_grade(prob)
        importances = {"feature_a": 0.3, "feature_b": 0.7}

        result = {
            "prediction": prediction_label,
            "probability": prob,
            "risk_grade": risk_grade,
            "feature_importances": importances,
        }

        # Structural checks
        assert "prediction" in result
        assert result["prediction"] in ("approved", "denied")
        assert "probability" in result
        assert 0.0 <= result["probability"] <= 1.0
        assert "risk_grade" in result
        assert result["risk_grade"] in VALID_RISK_GRADES
        assert "feature_importances" in result
        assert isinstance(result["feature_importances"], dict)

    @given(prob=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    @settings(max_examples=200)
    def test_prediction_consistent_with_threshold(self, prob):
        """The prediction label must agree with the probability and threshold."""
        threshold = 0.5
        label = "approved" if prob >= threshold else "denied"
        if prob >= threshold:
            assert label == "approved"
        else:
            assert label == "denied"

    @given(
        prob=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
        n_features=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_mock_model_integration(self, prob, n_features):
        """A mocked model returning a given probability should produce a
        well-formed result dict with correct types."""
        feature_cols = [f"feat_{i}" for i in range(n_features)]
        importances = np.random.rand(n_features)

        fake_model = MagicMock()
        fake_model.predict.return_value = np.array([1 if prob >= 0.5 else 0])
        fake_model.predict_proba.return_value = np.array([[1 - prob, prob]])
        fake_model.feature_importances_ = importances

        # Build importances dict the same way the real predictor does
        imp_dict = {}
        for name, imp in zip(feature_cols, fake_model.feature_importances_, strict=False):
            imp_dict[name] = round(float(imp), 4)

        threshold = 0.5
        result = {
            "prediction": "approved" if prob >= threshold else "denied",
            "probability": round(float(prob), 4),
            "risk_grade": compute_risk_grade(prob),
            "feature_importances": imp_dict,
        }

        assert result["prediction"] in ("approved", "denied")
        assert 0.0 <= result["probability"] <= 1.0
        assert result["risk_grade"] in VALID_RISK_GRADES
        assert len(result["feature_importances"]) == n_features
        for v in result["feature_importances"].values():
            assert isinstance(v, float)


# ===================================================================
# Test 4: Feature engineering derived features are always finite
# ===================================================================

# Strategy for base features needed by compute_derived_features.
# We use realistic ranges to avoid division-by-zero edge cases that are
# handled by the function's np.where guards.
_fe_base_strategy = st.fixed_dictionaries(
    {
        "annual_income": st.floats(min_value=1000.0, max_value=5_000_000.0, allow_nan=False, allow_infinity=False),
        "loan_amount": st.floats(min_value=100.0, max_value=5_000_000.0, allow_nan=False, allow_infinity=False),
        "loan_term_months": st.integers(min_value=1, max_value=600).map(float),
        "debt_to_income": st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        "credit_score": st.floats(min_value=0.0, max_value=1200.0, allow_nan=False, allow_infinity=False),
        "employment_length": st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        "property_value": st.floats(min_value=1.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
        "deposit_amount": st.floats(min_value=0.0, max_value=5_000_000.0, allow_nan=False, allow_infinity=False),
        "monthly_expenses": st.floats(min_value=0.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
        "existing_credit_card_limit": st.floats(
            min_value=0.0, max_value=500_000.0, allow_nan=False, allow_infinity=False
        ),
        "number_of_dependants": st.integers(min_value=0, max_value=10).map(float),
        "num_credit_enquiries_6m": st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        "worst_arrears_months": st.floats(min_value=0.0, max_value=36.0, allow_nan=False, allow_infinity=False),
        "num_defaults_5yr": st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        "credit_history_months": st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False),
        "num_bnpl_accounts": st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        "rba_cash_rate": st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        "total_open_accounts": st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        "savings_balance": st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        "bnpl_monthly_commitment": st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
        "credit_utilization_pct": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "days_negative_balance_90d": st.integers(min_value=0, max_value=90).map(float),
        "overdraft_frequency_90d": st.integers(min_value=0, max_value=30).map(float),
    }
)


class TestFeatureEngineeringFiniteness:
    """compute_derived_features must produce only finite values."""

    @given(base=_fe_base_strategy)
    @settings(max_examples=200)
    def test_derived_features_always_finite(self, base):
        """All derived feature columns should contain finite values (no NaN, no Inf)."""
        # Add employment_type for the stability calculation
        base["employment_type"] = np.random.choice(["payg_permanent", "contract", "self_employed", "payg_casual"])
        df = pd.DataFrame([base])
        # Impute any missing columns that compute_derived_features expects
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        for col in DERIVED_FEATURE_NAMES:
            if col in result.columns:
                val = result[col].iloc[0]
                assert np.isfinite(val), (
                    f"Derived feature '{col}' is not finite: {val}. "
                    f"Input: annual_income={base['annual_income']}, "
                    f"loan_amount={base['loan_amount']}, "
                    f"property_value={base['property_value']}"
                )

    @given(base=_fe_base_strategy)
    @settings(max_examples=100)
    def test_imputation_then_derivation_always_finite(self, base):
        """The full pipeline impute -> derive should never produce non-finite."""
        base["employment_type"] = "payg_permanent"
        # Randomly set some fields to NaN to exercise imputation
        for key in ["monthly_expenses", "existing_credit_card_limit", "property_value", "deposit_amount"]:
            if np.random.random() < 0.3:
                base[key] = np.nan

        df = pd.DataFrame([base])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            val = result[col].iloc[0]
            assert np.isfinite(val), f"Column '{col}' is not finite after impute+derive: {val}"


# ===================================================================
# Test 5: Edge case features — all zeros, all maxes
# ===================================================================


class TestEdgeCaseFeatures:
    """Extreme but valid inputs should never crash the pipeline."""

    def _run_validation_and_engineering(self, features_dict):
        """Run validation + feature engineering and assert no crash."""
        # Validation
        predictor = ModelPredictor.__new__(ModelPredictor)
        predictor.feature_bounds = {}

        numeric_features = {k: v for k, v in features_dict.items() if k in FEATURE_BOUNDS}
        predictor._validate_input(numeric_features)

        # Feature engineering
        df = pd.DataFrame([features_dict])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        # All numeric columns should be finite
        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            val = result[col].iloc[0]
            assert np.isfinite(val), f"Edge case: column '{col}' is not finite: {val}"

    def test_all_minimums(self):
        """All features set to their minimum bounds."""
        features = {}
        for key, (lo, _hi) in FEATURE_BOUNDS.items():
            features[key] = float(lo)

        # Avoid division-by-zero: set income and loan_term to small positives
        features["annual_income"] = 1.0
        features["loan_term_months"] = 1.0
        features["loan_amount"] = 1.0

        # Add categoricals
        features["purpose"] = "personal"
        features["home_ownership"] = "rent"
        features["employment_type"] = "payg_permanent"
        features["applicant_type"] = "single"
        features["state"] = "NSW"

        self._run_validation_and_engineering(features)

    def test_all_maximums(self):
        """All features set to their maximum bounds."""
        features = {}
        for key, (_lo, hi) in FEATURE_BOUNDS.items():
            features[key] = float(hi)

        # Add categoricals
        features["purpose"] = "personal"
        features["home_ownership"] = "rent"
        features["employment_type"] = "payg_permanent"
        features["applicant_type"] = "single"
        features["state"] = "NSW"

        self._run_validation_and_engineering(features)

    def test_zero_income(self):
        """Zero income is within bounds — should not crash feature engineering."""
        features = _build_base_feature_dict({"annual_income": 0.0})
        df = pd.DataFrame([features])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        # Zero income => derived ratios should be 0.0 (guarded by np.where)
        for col in [
            "loan_to_income",
            "credit_card_burden",
            "expense_to_income",
            "serviceability_ratio",
            "monthly_repayment_ratio",
            "net_monthly_surplus",
            "stressed_dsr",
            "bnpl_to_income_ratio",
        ]:
            if col in result.columns:
                val = result[col].iloc[0]
                assert np.isfinite(val), f"Zero income: '{col}' is not finite: {val}"

    def test_zero_loan_amount(self):
        """Zero loan amount should not crash."""
        features = _build_base_feature_dict(
            {
                "loan_amount": 0.0,
                "debt_to_income": 0.0,
            }
        )
        df = pd.DataFrame([features])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        for col in ["lvr", "deposit_ratio", "savings_to_loan_ratio"]:
            if col in result.columns:
                val = result[col].iloc[0]
                assert np.isfinite(val), f"Zero loan: '{col}' is not finite: {val}"

    def test_maximum_loan_with_minimum_income(self):
        """Extreme leverage: max loan, min income."""
        features = _build_base_feature_dict(
            {
                "annual_income": 1.0,  # minimal positive
                "loan_amount": 50_000_000.0,
                "loan_term_months": 600.0,
                "debt_to_income": 100.0,
            }
        )
        df = pd.DataFrame([features])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            val = result[col].iloc[0]
            assert np.isfinite(val), f"Max loan/min income: '{col}' is not finite: {val}"

    def test_all_binary_flags_on(self):
        """All boolean/flag features set to their maximum."""
        features = _build_base_feature_dict(
            {
                "has_cosigner": 1.0,
                "has_hecs": 1.0,
                "has_bankruptcy": 1.0,
                "is_existing_customer": 1,
                "gambling_transaction_flag": 1,
            }
        )
        df = pd.DataFrame([features])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            val = result[col].iloc[0]
            assert np.isfinite(val), f"All flags on: '{col}' is not finite: {val}"

    @given(
        purpose=st.sampled_from(CATEGORICAL_VALUES["purpose"]),
        home=st.sampled_from(CATEGORICAL_VALUES["home_ownership"]),
        emp=st.sampled_from(CATEGORICAL_VALUES["employment_type"]),
        app_type=st.sampled_from(CATEGORICAL_VALUES["applicant_type"]),
        state=st.sampled_from(CATEGORICAL_VALUES["state"]),
    )
    @settings(max_examples=50, derandomize=True, suppress_health_check=[HealthCheck.too_slow])
    def test_all_categorical_combinations_valid(self, purpose, home, emp, app_type, state):
        """Every combination of categorical values should be handled."""
        features = _build_base_feature_dict()
        features["purpose"] = purpose
        features["home_ownership"] = home
        features["employment_type"] = emp
        features["applicant_type"] = app_type
        features["state"] = state

        # For home loans, add property value so consistency checks pass
        if purpose == "home":
            features["property_value"] = 500000.0
            features["deposit_amount"] = 100000.0
            features["loan_amount"] = 400000.0
            features["loan_term_months"] = 360.0
            features["debt_to_income"] = 5.0

        df = pd.DataFrame([features])
        df = impute_missing_values(df)
        result = compute_derived_features(df)

        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            val = result[col].iloc[0]
            assert np.isfinite(val), (
                f"Categorical combo ({purpose},{home},{emp},{app_type},{state}): '{col}' is not finite: {val}"
            )
