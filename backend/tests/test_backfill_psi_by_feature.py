"""Tests for the backfill_psi_by_feature management command.

Mirror of the test_backfill_reference_distribution structure: stub
ModelVersion with a bundle that has feature_distributions but no
training_metadata.psi_by_feature, run command, assert mirror is now
populated. Then re-run and verify idempotent refusal + --force overwrite.
"""

import joblib
import numpy as np
import pytest
from django.core.management import call_command
from django.test import override_settings
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import ModelVersion


@pytest.fixture
def stub_model(tmp_path):
    bundle_path = tmp_path / "psi_stub.joblib"
    X = np.array([[600], [700], [800], [550], [720]])
    y = np.array([0, 1, 1, 0, 1])
    model = LogisticRegression().fit(X, y)
    bundle = {
        "model": model,
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": {
            "probability_distribution": [0.2, 0.5, 0.8],
            "feature_distributions": {"credit_score": [600, 650, 700, 750, 800]},
        },
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        mv = ModelVersion.objects.create(
            algorithm="rf", version="psi-stub",
            file_path=str(bundle_path), is_active=True,
            optimal_threshold=0.5,
            training_metadata={"reference_probabilities": [0.2, 0.5, 0.8]},
        )
    return mv, bundle_path, tmp_path


def _patch_predictor(monkeypatch, model, feature_cols):
    """Stub ModelPredictor so tests don't need a full bundle pipeline."""

    def _fake_init(self, model_version=None, **kwargs):
        self.model_version = model_version
        self.model = model
        self.feature_cols = feature_cols

    def _fake_transform(self, df):
        return df

    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.__init__",
        _fake_init,
    )
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor._transform",
        _fake_transform,
    )


def _fitted_test_model():
    """Tiny fitted model the predictor stub returns."""
    return LogisticRegression().fit(np.array([[600], [700], [800]]), np.array([0, 1, 1]))


@pytest.mark.django_db
def test_backfill_populates_psi_by_feature(stub_model, monkeypatch):
    mv, _bundle_path, tmp_path = stub_model

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [620, 660, 690, 740, 780] * (num_records // 5)}),
    )
    _patch_predictor(monkeypatch, _fitted_test_model(), ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_psi_by_feature", "--all-active", "--sample", "20")

    mv.refresh_from_db()
    psi = (mv.training_metadata or {}).get("psi_by_feature") or {}
    assert "credit_score" in psi
    assert isinstance(psi["credit_score"], float)


@pytest.mark.django_db
def test_backfill_refuses_without_force_when_present(stub_model, monkeypatch, capsys):
    mv, _bundle_path, tmp_path = stub_model
    mv.training_metadata = {**(mv.training_metadata or {}), "psi_by_feature": {"credit_score": 0.5}}
    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        mv.save(update_fields=["training_metadata"])

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [700] * num_records}),
    )
    _patch_predictor(monkeypatch, _fitted_test_model(), ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_psi_by_feature", "--all-active", "--sample", "10")

    out = capsys.readouterr().out
    assert "skip" in out.lower() or "already populated" in out.lower()
    mv.refresh_from_db()
    assert (mv.training_metadata or {}).get("psi_by_feature") == {"credit_score": 0.5}


@pytest.mark.django_db
def test_backfill_force_overwrites(stub_model, monkeypatch):
    mv, _bundle_path, tmp_path = stub_model
    mv.training_metadata = {**(mv.training_metadata or {}), "psi_by_feature": {"credit_score": 0.5}}
    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        mv.save(update_fields=["training_metadata"])

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [620, 660, 690, 740, 780] * (num_records // 5)}),
    )
    _patch_predictor(monkeypatch, _fitted_test_model(), ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_psi_by_feature", "--all-active", "--sample", "20", "--force")

    mv.refresh_from_db()
    psi = (mv.training_metadata or {}).get("psi_by_feature") or {}
    assert psi != {"credit_score": 0.5}
    assert "credit_score" in psi
