"""Tests for seed_predictions management command.

The command generates AU-calibrated synthetic predictions against a target
ModelVersion and weights timestamps for weekday-business + evening peak.
With --seed 42 + --count 200 the day-of-week distribution is deterministic.
"""

import joblib
import numpy as np
import pytest
from datetime import timedelta
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from sklearn.linear_model import LogisticRegression

from apps.ml_engine.models import ModelVersion, PredictionLog


@pytest.fixture
def active_model(tmp_path):
    bundle_path = tmp_path / "seed_stub.joblib"
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
            "feature_distributions": {"credit_score": [600, 700, 800]},
        },
        "imputation_values": {"credit_score": 650.0},
        "conformal_scores": [],
        "feature_bounds": {},
        "group_thresholds": {},
    }
    joblib.dump(bundle, bundle_path)

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        mv = ModelVersion.objects.create(
            algorithm="rf", version="test-seed",
            file_path=str(bundle_path), is_active=True,
            optimal_threshold=0.5,
            training_metadata={"reference_probabilities": [0.2, 0.5, 0.8]},
        )
    return mv, tmp_path, model


def _patch_predictor(monkeypatch, model, feature_cols):
    """Monkeypatch ModelPredictor so tests don't need a real bundle pipeline.

    The seed command now batches via predictor._transform + predictor.model.predict_proba
    instead of per-row predictor.predict(); we replace __init__ + _transform with
    lightweight stubs and the test's fitted LogisticRegression handles predict_proba.
    """

    def _fake_init(self, model_version=None, **kwargs):
        self.model_version = model_version
        self.model = model
        self.feature_cols = feature_cols

    def _fake_transform(self, df):
        return df  # passthrough — test DataFrames already have the right columns

    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor.__init__",
        _fake_init,
    )
    monkeypatch.setattr(
        "apps.ml_engine.services.predictor.ModelPredictor._transform",
        _fake_transform,
    )


@pytest.mark.django_db
def test_seed_creates_n_predictions_within_window(active_model, monkeypatch):
    mv, tmp_path, model = active_model

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [650] * num_records}),
    )
    _patch_predictor(monkeypatch, model, ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command(
            "seed_predictions",
            "--model-id", str(mv.id),
            "--count", "30",
            "--spread-days", "7",
            "--seed", "42",
            "--no-trigger-drift",
        )

    rows = PredictionLog.objects.filter(model_version=mv)
    assert rows.count() == 30

    now = timezone.now()
    earliest = now - timedelta(days=7, hours=1)
    for r in rows:
        assert earliest <= r.created_at <= now


@pytest.mark.django_db
def test_seed_day_of_week_distribution_is_deterministic(active_model, monkeypatch):
    """Fixed seed + count produces a repeatable day-of-week shape (Tue-Thu peak)."""
    mv, tmp_path, model = active_model

    import pandas as pd
    monkeypatch.setattr(
        "apps.ml_engine.services.data_generator.DataGenerator.generate",
        lambda self, num_records=100, random_seed=42, label_noise_rate=0.05:
            pd.DataFrame({"credit_score": [650] * num_records}),
    )
    _patch_predictor(monkeypatch, model, ["credit_score"])

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        call_command(
            "seed_predictions",
            "--model-id", str(mv.id),
            "--count", "200",
            "--spread-days", "7",
            "--seed", "42",
            "--no-trigger-drift",
        )

    rows = list(PredictionLog.objects.filter(model_version=mv))
    assert len(rows) == 200

    dow_counts = [0] * 7
    for r in rows:
        dow_counts[r.created_at.weekday()] += 1
    assert all(c >= 1 for c in dow_counts), f"all weekdays should appear: {dow_counts}"
    top_two = sorted(range(7), key=lambda i: -dow_counts[i])[:2]
    # Tue=1, Wed=2, Thu=3 are spec-defined heaviest.
    assert set(top_two) <= {1, 2, 3}, f"top two days should be Tue/Wed/Thu: {dow_counts}"


@pytest.mark.django_db
def test_seed_arg_validation(active_model):
    """Out-of-range count or spread-days are rejected."""
    from django.core.management.base import CommandError
    mv, tmp_path, _model = active_model

    with override_settings(ML_MODELS_DIR=str(tmp_path)):
        with pytest.raises((CommandError, SystemExit)):
            call_command("seed_predictions", "--model-id", str(mv.id), "--count", "0")
        with pytest.raises((CommandError, SystemExit)):
            call_command("seed_predictions", "--model-id", str(mv.id), "--count", "100000")
        with pytest.raises((CommandError, SystemExit)):
            call_command("seed_predictions", "--model-id", str(mv.id), "--count", "10", "--spread-days", "0")
        with pytest.raises((CommandError, SystemExit)):
            call_command("seed_predictions", "--model-id", str(mv.id), "--count", "10", "--spread-days", "365")
