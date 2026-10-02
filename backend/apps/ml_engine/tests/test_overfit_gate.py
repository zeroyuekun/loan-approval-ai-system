"""Tests for the validation-split overfitting gate.

Task 1: the trainer records `val_auc` and `overfitting_gap_val` (train AUC
minus validation AUC) in `training_metadata`, so overfitting can be judged
before the test set is ever read.
"""

from __future__ import annotations

import pytest

from apps.ml_engine.services.datagen.data_generator import DataGenerator


@pytest.fixture
def small_csv(tmp_path):
    """A small but trainable synthetic dataset written to a temp CSV."""
    gen = DataGenerator()
    df = gen.generate(num_records=500, random_seed=99)
    path = tmp_path / "loans.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.mark.django_db
def test_training_metadata_records_validation_auc_and_gap(small_csv):
    from apps.ml_engine.services.training.trainer import ModelTrainer

    _model, metrics = ModelTrainer().train(small_csv, algorithm="rf", use_reject_inference=False)
    meta = metrics["training_metadata"]

    assert "val_auc" in meta
    assert "overfitting_gap_val" in meta
    assert 0.0 <= meta["val_auc"] <= 1.0
    assert meta["overfitting_gap_val"] == round(meta["train_auc"] - meta["val_auc"], 4)
