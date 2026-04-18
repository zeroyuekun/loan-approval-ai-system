"""Unit tests for per-application prediction diagnostics.

Covers the two pure functions carved out of `ModelPredictor`:

- `check_feature_drift(features, reference_distribution)` — flags applicant
  values that are z>3 or z>4 standard deviations from the training mean. This
  is a single-application check, distinct from batch PSI/CSI monitoring in
  `drift_monitor.py`.

- `run_stress_scenarios(features, threshold, model, transform_fn, feature_cols)`
  — runs four APS-110-flavoured adverse scenarios (income −15%, property
  value −20%, credit score −50, combined) and reports probability + decision
  per scenario. Distinct from `stress_testing.py` which is portfolio-level.

Both functions are pure — no Django ORM, no module state — so tests can use
plain in-memory mocks.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from apps.ml_engine.services.prediction_diagnostics import (
    check_feature_drift,
    run_stress_scenarios,
)

# ---------------------------------------------------------------------------
# check_feature_drift
# ---------------------------------------------------------------------------


class TestCheckFeatureDrift:
    def test_empty_reference_returns_no_warnings(self):
        assert check_feature_drift({"annual_income": 80_000}, {}) == []
        assert check_feature_drift({"annual_income": 80_000}, None) == []

    def test_in_range_values_yield_no_warnings(self):
        ref = {"annual_income": {"mean": 80_000, "std": 20_000}}
        warnings = check_feature_drift({"annual_income": 85_000}, ref)
        assert warnings == []

    def test_z_above_3_emits_warning_severity(self):
        ref = {"annual_income": {"mean": 80_000, "std": 10_000}}
        # 115_000 is 3.5 std above the mean
        warnings = check_feature_drift({"annual_income": 115_000}, ref)
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "warning"
        assert warnings[0]["feature"] == "annual_income"
        assert warnings[0]["z_score"] == 3.5

    def test_z_above_4_emits_drift_severity(self):
        ref = {"annual_income": {"mean": 80_000, "std": 10_000}}
        # 130_000 is 5 std above the mean
        warnings = check_feature_drift({"annual_income": 130_000}, ref)
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "drift"
        assert "standard deviations" in warnings[0]["message"]

    def test_missing_feature_value_skipped(self):
        ref = {"annual_income": {"mean": 80_000, "std": 10_000}}
        assert check_feature_drift({}, ref) == []
        assert check_feature_drift({"annual_income": None}, ref) == []

    def test_non_numeric_value_skipped(self):
        ref = {"annual_income": {"mean": 80_000, "std": 10_000}}
        assert check_feature_drift({"annual_income": "high"}, ref) == []

    def test_tiny_std_skipped_to_avoid_divide_by_near_zero(self):
        ref = {"flag": {"mean": 0.5, "std": 0.0001}}
        # Would be an astronomical z-score; must be skipped, not reported
        assert check_feature_drift({"flag": 1.0}, ref) == []


# ---------------------------------------------------------------------------
# run_stress_scenarios
# ---------------------------------------------------------------------------


def _identity_transform(df: pd.DataFrame) -> pd.DataFrame:
    return df


def _make_mock_model(probability_sequence):
    """Mock that returns predict_proba outputs in sequence: [[1-p, p], ...]."""
    calls = iter(probability_sequence)
    model = MagicMock()

    def _predict_proba(_df):
        p = next(calls)
        return [[1 - p, p]]

    model.predict_proba.side_effect = _predict_proba
    return model


class TestRunStressScenarios:
    def _base_features(self):
        return {
            "annual_income": 100_000.0,
            "loan_amount": 400_000.0,
            "debt_to_income": 4.0,
            "property_value": 500_000.0,
            "credit_score": 750,
            "purpose": "home",
            "lmi_premium": 0.0,
            "effective_loan_amount": 400_000.0,
        }

    def test_happy_path_returns_base_and_four_scenarios(self):
        features = self._base_features()
        model = _make_mock_model([0.92, 0.80, 0.70, 0.60, 0.40])  # base + 4

        result = run_stress_scenarios(
            features,
            threshold=0.5,
            model=model,
            transform_fn=_identity_transform,
            feature_cols=list(features.keys()),
        )

        assert result["base_probability"] == 0.92
        assert set(result["scenarios"].keys()) == {
            "income_minus_15pct",
            "property_minus_20pct",
            "credit_minus_50",
            "combined_stress",
        }

    def test_income_shock_decreases_probability(self):
        features = self._base_features()
        model = _make_mock_model([0.92, 0.80, 0.70, 0.60, 0.40])

        result = run_stress_scenarios(
            features,
            threshold=0.5,
            model=model,
            transform_fn=_identity_transform,
            feature_cols=list(features.keys()),
        )

        scen = result["scenarios"]["income_minus_15pct"]
        assert scen["probability"] == 0.80
        assert scen["change"] == round(0.80 - 0.92, 4)
        assert scen["decision"] == "approved"

    def test_threshold_determines_decision(self):
        features = self._base_features()
        # Combined stress drops to 0.40 — below threshold 0.5 → denied
        model = _make_mock_model([0.92, 0.80, 0.70, 0.60, 0.40])

        result = run_stress_scenarios(
            features,
            threshold=0.5,
            model=model,
            transform_fn=_identity_transform,
            feature_cols=list(features.keys()),
        )

        assert result["scenarios"]["combined_stress"]["decision"] == "denied"

    def test_property_scenario_recomputes_lmi(self):
        # LVR at property*0.8 = 400k / 400k = 1.0 → 3% LMI
        features = self._base_features()
        model = _make_mock_model([0.92, 0.80, 0.70, 0.60, 0.40])

        captured = []

        def _capture_transform(df: pd.DataFrame) -> pd.DataFrame:
            captured.append(df.iloc[0].to_dict())
            return df

        run_stress_scenarios(
            features,
            threshold=0.5,
            model=model,
            transform_fn=_capture_transform,
            feature_cols=list(features.keys()),
        )

        # property_minus_20pct is the 3rd transform call (after base + income)
        property_scenario = captured[2]
        # LVR 400k/400k = 1.00 > 0.90 → 3% rate
        assert property_scenario["lmi_premium"] == round(400_000 * 0.03, 2)

    def test_zero_income_sets_maximum_dti(self):
        features = self._base_features()
        features["annual_income"] = 0.0
        # Any probability sequence will do — we're checking the features.
        model = _make_mock_model([0.5] * 5)
        captured = []

        def _capture_transform(df: pd.DataFrame) -> pd.DataFrame:
            captured.append(df.iloc[0].to_dict())
            return df

        run_stress_scenarios(
            features,
            threshold=0.5,
            model=model,
            transform_fn=_capture_transform,
            feature_cols=list(features.keys()),
        )

        # income_minus_15pct with 0 * 0.85 = 0 → DTI sentinel 999
        income_scenario = captured[1]
        assert income_scenario["debt_to_income"] == 999.0

    def test_model_failure_returns_partial_result_without_raising(self):
        features = self._base_features()
        model = MagicMock()
        model.predict_proba.side_effect = RuntimeError("boom")

        result = run_stress_scenarios(
            features,
            threshold=0.5,
            model=model,
            transform_fn=_identity_transform,
            feature_cols=list(features.keys()),
        )

        # Fail-open: return an empty-ish result; never propagate.
        assert result["base_probability"] is None
        assert result["scenarios"] == {}
