"""End-to-end drift pipeline integration test.

Builds a tiny model bundle with reference_distribution populated, registers
it as a ModelVersion, seeds 30 predictions via the seed_predictions command,
runs the drift task. Asserts a DriftReport row exists with non-null
psi_score and approval_rate.
"""

import joblib
import numpy as np
import pytest
from django.core.management import call_command
from django.test import override_settings
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog


@pytest.mark.django_db
def test_full_drift_pipeline(tmp_path, monkeypatch):
    bundle_path = tmp_path / "pipeline.joblib"
    X = np.array([[600], [650], [700], [750], [800]])
    y = np.array([0, 0, 1, 1, 1])
    model = LogisticRegression().fit(X, y)
    holdout_probs = model.predict_proba(X)[:, 1].tolist()
    bundle = {
        "model": model,
        "scaler": None,
        "feature_cols": ["credit_score"],
        "categorical_cols": [],
        "numeric_cols": ["credit_score"],
        "reference_distribution": {
            "probability_distribution": holdout_probs,
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
            algorithm="rf", version="integration",
            file_path=str(bundle_path), is_active=True,
            optimal_threshold=0.5,
            training_metadata={"reference_probabilities": holdout_probs},
        )

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": list(np.random.default_rng(42).integers(550, 820, size=num_records))}),
    )

    # Stub the predictor so the seed_predictions command's batch-transform
    # pipeline (predictor._transform → predictor.model.predict_proba) can run
    # against the toy LogisticRegression without requiring full feature engineering.
    def _fake_init(self, model_version=None, **kwargs):
        self.model_version = model_version
        self.model = model
        self.feature_cols = ["credit_score"]
    def _fake_transform(self, df):
        return df  # passthrough
    monkeypatch.setattr("apps.ml_engine.services.predictor.ModelPredictor.__init__", _fake_init)
    monkeypatch.setattr("apps.ml_engine.services.predictor.ModelPredictor._transform", _fake_transform)

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command(
            "seed_predictions",
            "--model-id", str(mv.id),
            "--count", "30",
            "--spread-days", "7",
            "--seed", "42",
            "--trigger-drift",
        )

    assert PredictionLog.objects.filter(model_version=mv).count() == 30
    reports = DriftReport.objects.filter(model_version=mv)
    assert reports.exists(), "drift task did not write a DriftReport"

    r = reports.first()
    assert r.psi_score is not None, "psi_score should be populated"
    assert r.approval_rate is not None, "approval_rate should be populated"
    assert 0.0 <= r.approval_rate <= 1.0
