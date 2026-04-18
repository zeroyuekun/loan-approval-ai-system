"""Per-prediction SHAP attribution helper.

Carved out of `ModelPredictor.predict()` during Arm C Phase 1. Returns the
global `feature_importances_` plus per-prediction SHAP values, wrapped in a
fail-open exception guard so inference never crashes if the SHAP library hits
an edge case (e.g. a non-tree model, library version mismatch).

Handles the three SHAP return shapes observed in production:
- `list[ndarray, ndarray]` — legacy sklearn / SHAP <0.45
- `ndarray` of shape `(n_samples, n_features, 2)` — SHAP >=0.45 multi-output
- `ndarray` of shape `(n_samples, n_features)` — XGBoost log-odds single output

If the incoming model is a calibrated wrapper exposing
`get_underlying_estimator()`, the underlying booster is fed to TreeExplainer —
SHAP operates on the raw trees, not the isotonic layer, so the baseline
naturally differs from the calibrated probability (logged at DEBUG).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import shap

__all__ = ["compute_shap_attribution"]

logger = logging.getLogger(__name__)


_SHAP_MODEL_NOTE = (
    "Feature attributions computed on base model before probability calibration"
)


def compute_shap_attribution(
    *,
    model,
    df: pd.DataFrame,
    feature_cols: list,
    positive_probability: float,
) -> dict:
    """Return the four-key attribution dict consumed by the predictor result.

    Keys: `feature_importances`, `shap_values`, `shap_available`, `shap_model_note`.
    """
    importances: dict[str, float] = {}
    if hasattr(model, "feature_importances_"):
        for name, imp in zip(feature_cols, model.feature_importances_, strict=False):
            importances[name] = round(float(imp), 4)

    shap_values_dict: dict[str, float] = {}
    shap_available = False
    try:
        underlying = (
            model.get_underlying_estimator()
            if hasattr(model, "get_underlying_estimator")
            else model
        )
        explainer = shap.TreeExplainer(underlying)
        sv = explainer.shap_values(df[feature_cols])

        if isinstance(sv, list):
            sv = sv[1]
        elif hasattr(sv, "ndim") and sv.ndim == 3:
            sv = sv[:, :, 1]

        for name, val in zip(feature_cols, sv[0], strict=False):
            shap_values_dict[name] = round(float(val), 4)
        shap_available = True

        if abs(float(np.array(explainer.expected_value).flat[0]) - positive_probability) > 0.05:
            logger.debug(
                "SHAP expected value (%.3f) diverges from calibrated probability (%.3f) — values are from uncalibrated base model",
                float(np.array(explainer.expected_value).flat[0]),
                positive_probability,
            )
    except Exception:
        logger.warning("SHAP computation failed, returning empty shap_values", exc_info=True)

    return {
        "feature_importances": importances,
        "shap_values": shap_values_dict,
        "shap_available": shap_available,
        "shap_model_note": _SHAP_MODEL_NOTE,
    }
