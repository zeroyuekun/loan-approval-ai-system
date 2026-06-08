"""L17: public ModelPredictor seam for cross-app counterfactual construction.

The agents orchestrator must not reach into ModelPredictor's private
``_transform`` across an app boundary. These tests assert a stable public
``transform`` seam and a ``build_counterfactual_engine`` factory.
"""

from unittest.mock import MagicMock

import pandas as pd

from apps.ml_engine.services.scoring.predictor import ModelPredictor


def test_build_counterfactual_engine_uses_public_transform(monkeypatch):
    p = ModelPredictor.__new__(ModelPredictor)  # bypass bundle load
    p.model = MagicMock()
    p.feature_cols = ["credit_score", "loan_amount"]
    p.model_version = MagicMock()
    p.model_version.optimal_threshold = 0.5
    called = {}
    monkeypatch.setattr(p, "_transform", lambda df: called.setdefault("hit", df) or df)
    df = pd.DataFrame([{"credit_score": 500, "loan_amount": 200000.0}])
    import apps.ml_engine.services.scoring.counterfactual_engine as cf_mod

    monkeypatch.setattr(cf_mod, "CounterfactualEngine", MagicMock(), raising=False)
    engine = p.build_counterfactual_engine(df, original_loan_amount=200000.0)
    assert engine is not None


def test_public_transform_delegates_to_private(monkeypatch):
    p = ModelPredictor.__new__(ModelPredictor)
    monkeypatch.setattr(p, "_transform", lambda df: "TRANSFORMED")
    assert p.transform(pd.DataFrame()) == "TRANSFORMED"
