"""Unit tests for the SHAP attribution helper.

`compute_shap_attribution` is the block carved out of `ModelPredictor.predict()`
during Arm C Phase 1. It computes:

- `feature_importances` — global importance dict from `model.feature_importances_`
  (empty if the attribute is absent).
- `shap_values` — per-prediction SHAP values for the positive class.
- `shap_available` — True if SHAP computation succeeded, False if it raised.

Handles three SHAP return shapes:
- list-of-arrays (legacy sklearn / SHAP <0.45)
- 3D ndarray (SHAP >=0.45 multi-output)
- 2D ndarray (XGBoost log-odds, single output)

And peels calibrated-model wrappers via `get_underlying_estimator()` so the
tree explainer sees the raw booster, not the IsotonicRegression layer.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from apps.ml_engine.services.shap_attribution import compute_shap_attribution


def _model_with_importances(importances):
    m = MagicMock()
    m.feature_importances_ = np.array(importances)
    # Ensure hasattr(m, "get_underlying_estimator") is False — pure model.
    del m.get_underlying_estimator
    return m


def _df(feature_cols, values):
    return pd.DataFrame([dict(zip(feature_cols, values, strict=False))])


class TestComputeShapAttribution:
    def test_feature_importances_populated_when_attribute_present(self):
        model = _model_with_importances([0.1, 0.7, 0.2])
        feature_cols = ["a", "b", "c"]
        df = _df(feature_cols, [1, 2, 3])

        # SHAP will be called — mock it to return a simple 2D array.
        with patch("apps.ml_engine.services.shap_attribution.shap.TreeExplainer") as TE:
            TE.return_value.shap_values.return_value = np.array([[0.01, 0.02, 0.03]])
            TE.return_value.expected_value = 0.5
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert result["feature_importances"] == {"a": 0.1, "b": 0.7, "c": 0.2}
        assert result["shap_available"] is True
        assert set(result["shap_values"].keys()) == {"a", "b", "c"}

    def test_no_feature_importances_attribute_returns_empty_dict(self):
        model = MagicMock(spec=[])  # spec=[] strips all attrs including feature_importances_
        feature_cols = ["a", "b"]
        df = _df(feature_cols, [1, 2])

        with patch("apps.ml_engine.services.shap_attribution.shap.TreeExplainer") as TE:
            TE.return_value.shap_values.return_value = np.array([[0.01, 0.02]])
            TE.return_value.expected_value = 0.5
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert result["feature_importances"] == {}
        assert result["shap_available"] is True

    def test_shap_list_of_arrays_selects_positive_class(self):
        """SHAP <0.45 returns a 2-item list; helper must pick index 1 (positive class)."""
        model = _model_with_importances([0.5, 0.5])
        feature_cols = ["a", "b"]
        df = _df(feature_cols, [1, 2])

        with patch("apps.ml_engine.services.shap_attribution.shap.TreeExplainer") as TE:
            TE.return_value.shap_values.return_value = [
                np.array([[-0.1, -0.2]]),  # negative class
                np.array([[0.1, 0.2]]),  # positive class
            ]
            TE.return_value.expected_value = 0.5
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert result["shap_values"] == {"a": 0.1, "b": 0.2}

    def test_shap_3d_array_selects_positive_class_slice(self):
        """SHAP >=0.45 returns a 3D array (n_samples, n_features, 2)."""
        model = _model_with_importances([0.5, 0.5])
        feature_cols = ["a", "b"]
        df = _df(feature_cols, [1, 2])

        # Shape: 1 sample, 2 features, 2 classes. Positive = [..., 1].
        sv = np.array([[[-0.1, 0.1], [-0.2, 0.2]]])

        with patch("apps.ml_engine.services.shap_attribution.shap.TreeExplainer") as TE:
            TE.return_value.shap_values.return_value = sv
            TE.return_value.expected_value = 0.5
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert result["shap_values"] == {"a": 0.1, "b": 0.2}

    def test_shap_2d_array_used_directly(self):
        """XGBoost log-odds returns a flat 2D array (n_samples, n_features)."""
        model = _model_with_importances([0.5, 0.5])
        feature_cols = ["a", "b"]
        df = _df(feature_cols, [1, 2])

        sv = np.array([[0.3, 0.4]])

        with patch("apps.ml_engine.services.shap_attribution.shap.TreeExplainer") as TE:
            TE.return_value.shap_values.return_value = sv
            TE.return_value.expected_value = 0.5
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert result["shap_values"] == {"a": 0.3, "b": 0.4}

    def test_calibrated_model_unwrapped_for_tree_explainer(self):
        """If model has `get_underlying_estimator`, that is what goes into TreeExplainer."""
        base = MagicMock(name="base_xgb")
        calibrated = SimpleNamespace(
            feature_importances_=np.array([0.5, 0.5]),
            get_underlying_estimator=lambda: base,
        )
        feature_cols = ["a", "b"]
        df = _df(feature_cols, [1, 2])

        with patch("apps.ml_engine.services.shap_attribution.shap.TreeExplainer") as TE:
            TE.return_value.shap_values.return_value = np.array([[0.01, 0.02]])
            TE.return_value.expected_value = 0.5
            compute_shap_attribution(
                model=calibrated,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        TE.assert_called_once_with(base)

    def test_shap_failure_returns_available_false(self):
        """If SHAP raises, helper returns shap_available=False with empty dict, not crash."""
        model = _model_with_importances([0.5, 0.5])
        feature_cols = ["a", "b"]
        df = _df(feature_cols, [1, 2])

        with patch(
            "apps.ml_engine.services.shap_attribution.shap.TreeExplainer",
            side_effect=RuntimeError("not a tree model"),
        ):
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert result["shap_available"] is False
        assert result["shap_values"] == {}
        # feature_importances still populated from the attribute lookup which didn't fail
        assert result["feature_importances"] == {"a": 0.5, "b": 0.5}

    def test_result_keys_present_on_failure_too(self):
        """All four contract keys must be present even on SHAP failure."""
        model = MagicMock(spec=[])
        feature_cols = ["a"]
        df = _df(feature_cols, [1])

        with patch(
            "apps.ml_engine.services.shap_attribution.shap.TreeExplainer",
            side_effect=RuntimeError("nope"),
        ):
            result = compute_shap_attribution(
                model=model,
                df=df,
                feature_cols=feature_cols,
                positive_probability=0.5,
            )

        assert set(result.keys()) == {
            "feature_importances",
            "shap_values",
            "shap_available",
            "shap_model_note",
        }
