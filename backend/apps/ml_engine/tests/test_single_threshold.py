"""One approval threshold for every applicant.

The trainer used to fit a per-employment-type threshold on the TEST split
(lowering a group's cut-off until its approval rate reached 80% of the best
group's, floor 0.05) and the scorer applied it. The live bundle carried
self_employed 0.45 against 0.87 for everyone else, while the fairness gate and
training_metadata described a single threshold (the metadata key was read
before it was computed, so it was always {}).

Owner decision: one threshold, chosen on the validation split, for every
applicant. Scoring ignores any group_thresholds left in existing artefacts, so
the live model changes behaviour without retraining.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from apps.ml_engine.services.scoring import predictor as predictor_mod
from apps.ml_engine.services.scoring.decision_assembly import assemble_decision
from apps.ml_engine.services.scoring.predictor import ModelPredictor


def _approving_tier():
    tier = MagicMock()
    tier.approved = True
    tier.pd_score = 0.1
    tier.segment = "personal"
    tier.to_dict.return_value = {"tier": "B", "approved": True}
    return tier


def test_assemble_decision_has_no_group_threshold_input():
    """The decision rule takes the model's threshold and nothing keyed on the applicant's group."""
    mv = SimpleNamespace(id="mv", optimal_threshold=0.6)
    with patch("apps.ml_engine.services.scoring.decision_assembly.get_tier", return_value=_approving_tier()):
        with pytest.raises(TypeError):
            assemble_decision(
                probability_positive=0.55,
                model_version=mv,
                group_thresholds={"self_employed": 0.4},
                employment_type="self_employed",
                drift_warnings=[],
                segment="personal",
            )


@pytest.fixture
def stub_predictor(monkeypatch):
    """A ModelPredictor whose bundle still carries legacy group thresholds."""
    p = ModelPredictor.__new__(ModelPredictor)
    p.model_version = SimpleNamespace(id="mv-legacy", optimal_threshold=0.87, algorithm="xgb")
    p.model = MagicMock()
    p.model.predict_proba.return_value = np.array([[0.55, 0.45]])
    p.feature_cols = []
    p.feature_bounds = {}
    p.reference_distribution = {}
    p.imputation_values = {}
    p.conformal_scores = np.array([])
    p.consistency_checker = MagicMock()
    p.consistency_checker.check_all.return_value = {"consistent": True, "warnings": [], "errors": []}
    p._metrics_service = MagicMock()
    # What the live artefact carries: self-employed approved at p >= 0.45.
    p.group_thresholds = {"self_employed": 0.45, "payg_permanent": 0.87}

    features = {"employment_type": "self_employed", "purpose": "personal", "loan_amount": 20000}
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
    monkeypatch.setattr("apps.ml_engine.services.scoring.decision_assembly.get_tier", lambda **k: _approving_tier())
    return p


def test_scoring_ignores_group_thresholds_in_an_existing_artefact(stub_predictor):
    result = stub_predictor.predict(MagicMock())

    # p=0.45 clears the legacy self-employed cut-off but not the model's 0.87.
    assert result["prediction"] == "denied"
    assert result["threshold_used"] == 0.87
