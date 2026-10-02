"""Model card must state the validation-split caveat for the overfitting gap.

The validation split that `overfitting_gap_val` is computed on is the same
split used for XGBoost early stopping, probability calibration and threshold
choice, so the gap can understate true overfitting. `_limitations` is a pure
function of `training_metadata`, so these are plain unit tests — no DB or
active ModelVersion required.
"""

from __future__ import annotations

from apps.ml_engine.services.governance.model_card import ModelCardGenerator


def test_limitations_include_validation_split_caveat_when_gap_present():
    limitations = ModelCardGenerator._limitations({"overfitting_gap_val": 0.07})
    assert any("early stopping" in item and "calibration" in item for item in limitations)


def test_limitations_omit_validation_split_caveat_when_gap_absent():
    limitations = ModelCardGenerator._limitations({})
    assert not any("early stopping" in item for item in limitations)


def test_limitations_always_include_the_baseline_entries():
    limitations = ModelCardGenerator._limitations({"overfitting_gap_val": 0.07})
    assert any("synthetic data" in item for item in limitations)
    assert any("time-to-default" in item for item in limitations)
