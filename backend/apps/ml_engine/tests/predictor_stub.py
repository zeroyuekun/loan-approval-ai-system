"""A ModelPredictor with the bundle and every side helper stubbed out.

Lets a test drive the real ``ModelPredictor.predict`` decision path
(validation, clipping, decision assembly) without a model artefact.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from apps.ml_engine.services.scoring import predictor as predictor_mod
from apps.ml_engine.services.scoring.predictor import ModelPredictor


def approving_tier():
    tier = MagicMock()
    tier.approved = True
    tier.pd_score = 0.1
    tier.segment = "personal"
    tier.to_dict.return_value = {"tier": "B", "approved": True}
    return tier


def build_stub_predictor(monkeypatch, *, features, probability, threshold, feature_cols=(), **attrs):
    p = ModelPredictor.__new__(ModelPredictor)
    p.model_version = SimpleNamespace(id="mv-stub", optimal_threshold=threshold, algorithm="xgb")
    p.model = MagicMock()
    p.model.predict_proba.return_value = np.array([[1.0 - probability, probability]])
    p.feature_cols = list(feature_cols)
    p.feature_bounds = {}
    p.reference_distribution = {}
    p.imputation_values = {}
    p.conformal_scores = np.array([])
    p.consistency_checker = MagicMock()
    p.consistency_checker.check_all.return_value = {"consistent": True, "warnings": [], "errors": []}
    p._metrics_service = MagicMock()
    for name, value in attrs.items():
        setattr(p, name, value)

    monkeypatch.setattr(predictor_mod, "_build_prediction_features_helper", lambda *a, **k: dict(features))
    monkeypatch.setattr(predictor_mod, "_derive_underwriter_features_helper", lambda f: None)
    monkeypatch.setattr(p, "_transform", lambda df: df)
    monkeypatch.setattr(
        predictor_mod,
        "_compute_shap_attribution_helper",
        lambda **k: {"feature_importances": {}, "shap_values": {}, "shap_available": False},
    )
    monkeypatch.setattr(predictor_mod, "_run_stress_scenarios_helper", lambda *a, **k: [])
    monkeypatch.setattr(predictor_mod, "_compute_conformal_interval_helper", lambda *a, **k: None)
    monkeypatch.setattr(predictor_mod, "_search_counterfactuals_helper", lambda *a, **k: [])
    monkeypatch.setattr(predictor_mod, "_score_challengers_shadow_helper", lambda **k: None)
    monkeypatch.setattr(
        predictor_mod,
        "_apply_policy_overlay_helper",
        lambda **k: (k["prediction_label"], {"passed": True, "mode": "off"}),
    )
    monkeypatch.setattr("apps.ml_engine.services.scoring.decision_assembly.get_tier", lambda **k: approving_tier())
    return p
