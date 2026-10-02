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

import pytest

from apps.ml_engine.services.scoring.decision_assembly import assemble_decision
from apps.ml_engine.tests.predictor_stub import approving_tier, build_stub_predictor


def test_assemble_decision_has_no_group_threshold_input():
    """The decision rule takes the model's threshold and nothing keyed on the applicant's group."""
    mv = SimpleNamespace(id="mv", optimal_threshold=0.6)
    with patch("apps.ml_engine.services.scoring.decision_assembly.get_tier", return_value=approving_tier()):
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
    return build_stub_predictor(
        monkeypatch,
        features={"employment_type": "self_employed", "purpose": "personal", "loan_amount": 20000},
        probability=0.45,
        threshold=0.87,
        # What the live artefact carries: self-employed approved at p >= 0.45.
        group_thresholds={"self_employed": 0.45, "payg_permanent": 0.87},
    )


def test_scoring_ignores_group_thresholds_in_an_existing_artefact(stub_predictor):
    result = stub_predictor.predict(MagicMock())

    # p=0.45 clears the legacy self-employed cut-off but not the model's 0.87.
    assert result["prediction"] == "denied"
    assert result["threshold_used"] == 0.87
