"""Tests for the backfill_reference_distribution management command.

Patches an existing model bundle that lacks probability_distribution +
feature_distributions, then re-runs to verify idempotent refusal and
--force overwrite.

ModelPredictor is fully monkeypatched in every test so the management
command's new pipeline (predictor._transform → predictor.model.predict_proba)
works without requiring a real trained bundle on disk.
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
    """Build a fitted LR model + ModelVersion + saved bundle missing the new keys.

    ML_MODELS_DIR is overridden to tmp_path so ModelVersion.clean() accepts the
    bundle path, and _validate_model_path in the management command does too.
    """
    bundle_path = tmp_path / "stub.joblib"

    X = np.array([[600], [700], [800], [550], [720]])
    y = np.array([0, 1, 1, 0, 1])
    model = LogisticRegression().fit(X, y)
    bundle = {
        "model": model,
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": {"credit_score": {"percentiles": [600, 700, 800]}},
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        mv = ModelVersion.objects.create(
            algorithm="rf", version="test-backfill",
            file_path=str(bundle_path), is_active=True,
            training_metadata={},
        )

    yield mv, bundle_path, tmp_path


def _patch_predictor(monkeypatch, model, feature_cols):
    """Monkeypatch ModelPredictor so tests don't need a real trained bundle.

    Replaces __init__ with a lightweight initialiser that sets the minimal
    attributes the backfill command depends on, and makes _transform a
    passthrough so the DataFrame flows through unchanged.
    """

    def _fake_init(self, model_version=None, **kwargs):
        self.model_version = model_version
        self.model = model
        self.feature_cols = feature_cols

    def _fake_transform(self, df):
        # Passthrough — test DataFrames already have the right columns.
        return df

    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.__init__",
        _fake_init,
    )
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor._transform",
        _fake_transform,
    )


@pytest.mark.django_db
def test_backfill_populates_missing_fields(stub_model, monkeypatch):
    """Bundle gets probability_distribution + feature_distributions; metadata gets reference_probabilities."""
    mv, bundle_path, tmp_path = stub_model

    X = np.array([[600], [700], [800], [550], [720]])
    y = np.array([0, 1, 1, 0, 1])
    model = LogisticRegression().fit(X, y)
    _patch_predictor(monkeypatch, model, ["credit_score"])

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [600, 650, 700, 750, 800] * (num_records // 5)}),
    )

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_reference_distribution", "--all-active", "--sample", "20")

    bundle = joblib.load(bundle_path)
    rd = bundle["reference_distribution"]
    assert "probability_distribution" in rd
    assert len(rd["probability_distribution"]) > 0
    assert "feature_distributions" in rd
    assert "credit_score" in rd["feature_distributions"]
    assert "credit_score" in rd
    assert "percentiles" in rd["credit_score"]

    mv.refresh_from_db()
    assert "reference_probabilities" in (mv.training_metadata or {})


@pytest.mark.django_db
def test_backfill_refuses_without_force_when_present(stub_model, monkeypatch, capsys):
    mv, bundle_path, tmp_path = stub_model
    bundle = joblib.load(bundle_path)
    bundle["reference_distribution"]["probability_distribution"] = [0.5, 0.6]
    joblib.dump(bundle, bundle_path)

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [700] * num_records}),
    )

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_reference_distribution", "--all-active", "--sample", "10")

    out = capsys.readouterr().out
    assert "skipping" in out.lower() or "already populated" in out.lower() or "skip" in out.lower()
    bundle_after = joblib.load(bundle_path)
    assert bundle_after["reference_distribution"]["probability_distribution"] == [0.5, 0.6]


@pytest.mark.django_db
def test_backfill_force_overwrites(stub_model, monkeypatch):
    mv, bundle_path, tmp_path = stub_model
    bundle = joblib.load(bundle_path)
    bundle["reference_distribution"]["probability_distribution"] = [0.5]
    joblib.dump(bundle, bundle_path)

    X = np.array([[600], [700], [800], [550], [720]])
    y = np.array([0, 1, 1, 0, 1])
    model = LogisticRegression().fit(X, y)
    _patch_predictor(monkeypatch, model, ["credit_score"])

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [600, 700, 800, 750, 650] * (num_records // 5)}),
    )

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command("backfill_reference_distribution", "--all-active", "--sample", "20", "--force")

    bundle_after = joblib.load(bundle_path)
    assert len(bundle_after["reference_distribution"]["probability_distribution"]) > 1
