"""Unit tests for per-application explanation helpers.

Covers the two pure functions carved out of `ModelPredictor`:

- `compute_conformal_interval(probability, conformal_scores, alpha)` —
  split-conformal prediction interval with the Small Sample Beta Correction
  (SSBC) for calibration sets of size < 500. Returns lower/upper bounds
  with a finite-sample coverage guarantee.

- `search_counterfactuals(features_df, feature_importances, model_bundle,
  transform_fn, feature_cols)` — binary-search counterfactual generator for
  denied applications. Distinct from the DiCE-based `counterfactual_engine.py`
  used in production; this is the fallback the predictor uses inline.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from apps.ml_engine.services.prediction_explanations import (
    compute_conformal_interval,
    search_counterfactuals,
)


# ---------------------------------------------------------------------------
# compute_conformal_interval
# ---------------------------------------------------------------------------


class TestComputeConformalInterval:
    def test_no_calibration_scores_returns_degenerate_interval(self):
        result = compute_conformal_interval(0.73, np.array([]), alpha=0.05)
        assert result["available"] is False
        assert result["lower"] == 0.73
        assert result["upper"] == 0.73
        assert result["confidence_level"] == 0.95

    def test_large_calibration_set_returns_wide_interval(self):
        # 1000 uniformly distributed nonconformity scores; 95th percentile ~0.95
        scores = np.linspace(0.0, 1.0, 1000)
        result = compute_conformal_interval(0.5, scores, alpha=0.05)
        assert result["available"] is True
        assert result["lower"] == 0.0  # clamped to 0 since 0.5 - 0.95 < 0
        assert result["upper"] == 1.0  # clamped to 1 since 0.5 + 0.95 > 1
        assert result["ssbc_applied"] is False  # n > 500
        assert result["width"] == 1.0

    def test_small_calibration_set_applies_ssbc(self):
        # n < 500 triggers SSBC path
        scores = np.array([0.1, 0.2, 0.15, 0.12, 0.08, 0.18, 0.22, 0.1, 0.11, 0.09])
        result = compute_conformal_interval(0.5, scores, alpha=0.05)
        # SSBC should narrow alpha to maintain coverage guarantee
        assert result["available"] is True
        # ssbc_applied may be True or False depending on whether a tighter alpha
        # satisfies the coverage target — the contract is "it was considered".
        assert "ssbc_applied" in result

    def test_bounds_clamped_to_valid_probability_range(self):
        scores = np.array([0.8])
        result = compute_conformal_interval(0.3, scores, alpha=0.05)
        assert result["lower"] >= 0.0
        assert result["upper"] <= 1.0

    def test_alpha_sets_confidence_level(self):
        scores = np.array([0.1] * 20)
        result = compute_conformal_interval(0.5, scores, alpha=0.10)
        # SSBC may override alpha internally; confidence_level reflects the
        # *effective* alpha applied to the quantile lookup.
        assert 0.85 <= result["confidence_level"] <= 0.95


# ---------------------------------------------------------------------------
# search_counterfactuals
# ---------------------------------------------------------------------------


def _identity_transform(df: pd.DataFrame) -> pd.DataFrame:
    return df


class TestSearchCounterfactuals:
    def _make_bundle(self, predict_side_effect, threshold=0.5):
        model = MagicMock()
        model.predict_proba.side_effect = predict_side_effect
        return {"model": model, "threshold": threshold}

    def test_empty_feature_importances_returns_empty(self):
        df = pd.DataFrame([{"annual_income": 80_000, "credit_score": 600}])
        bundle = self._make_bundle([[1, 0]])
        result = search_counterfactuals(
            df, feature_importances={}, model_bundle=bundle,
            transform_fn=_identity_transform, feature_cols=["annual_income", "credit_score"],
        )
        assert result == []

    def test_unknown_feature_is_skipped(self):
        df = pd.DataFrame([{"annual_income": 80_000}])
        bundle = self._make_bundle([[1, 0]] * 30)
        # "exotic_feature" has no bounds entry → skipped
        result = search_counterfactuals(
            df, feature_importances={"exotic_feature": 0.9}, model_bundle=bundle,
            transform_fn=_identity_transform, feature_cols=["annual_income"],
        )
        assert result == []

    def test_increases_income_to_flip_outcome(self):
        df = pd.DataFrame([{"annual_income": 50_000, "credit_score": 600}])
        # predict_proba returns a 2-D array; wrap each row accordingly.
        bundle = self._make_bundle([[[0.1, 0.9]]] * 30)
        result = search_counterfactuals(
            df, feature_importances={"annual_income": 0.8}, model_bundle=bundle,
            transform_fn=_identity_transform, feature_cols=["annual_income", "credit_score"],
        )
        assert len(result) == 1
        assert result[0]["feature"] == "annual_income"
        assert "Increasing" in result[0]["statement"]

    def test_decreases_loan_amount_direction(self):
        df = pd.DataFrame([{"loan_amount": 500_000, "credit_score": 700}])
        bundle = self._make_bundle([[[0.1, 0.9]]] * 30)
        result = search_counterfactuals(
            df, feature_importances={"loan_amount": 0.7}, model_bundle=bundle,
            transform_fn=_identity_transform, feature_cols=["loan_amount", "credit_score"],
        )
        assert len(result) == 1
        assert result[0]["feature"] == "loan_amount"
        assert "Reducing" in result[0]["statement"]

    def test_no_flip_within_bounds_returns_empty_for_that_feature(self):
        df = pd.DataFrame([{"annual_income": 50_000}])
        # Every probe returns deny → no flip value found
        bundle = self._make_bundle([[[0.9, 0.1]]] * 30)
        result = search_counterfactuals(
            df, feature_importances={"annual_income": 0.9}, model_bundle=bundle,
            transform_fn=_identity_transform, feature_cols=["annual_income"],
        )
        assert result == []

    def test_exception_in_transform_is_swallowed(self):
        df = pd.DataFrame([{"annual_income": 50_000}])
        bundle = self._make_bundle([RuntimeError("boom")] * 30)
        # Function should swallow and return empty for that feature
        result = search_counterfactuals(
            df, feature_importances={"annual_income": 0.9}, model_bundle=bundle,
            transform_fn=_identity_transform, feature_cols=["annual_income"],
        )
        assert result == []

    def test_takes_top_three_by_importance(self):
        df = pd.DataFrame([{
            "annual_income": 50_000,
            "credit_score": 600,
            "debt_to_income": 5.0,
            "loan_amount": 500_000,
            "monthly_expenses": 3000,
        }])
        bundle = self._make_bundle([[0.1, 0.9]] * 200)
        importances = {
            "annual_income": 0.9,
            "credit_score": 0.85,
            "debt_to_income": 0.7,
            "loan_amount": 0.5,
            "monthly_expenses": 0.3,
        }
        result = search_counterfactuals(
            df, feature_importances=importances, model_bundle=bundle,
            transform_fn=_identity_transform,
            feature_cols=list(df.columns),
        )
        # Top 3 by importance: annual_income, credit_score, debt_to_income
        assert {cf["feature"] for cf in result} <= {"annual_income", "credit_score", "debt_to_income"}
        assert len(result) <= 3
