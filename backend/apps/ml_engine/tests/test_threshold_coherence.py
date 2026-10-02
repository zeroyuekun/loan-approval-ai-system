"""Regression guards for the operating-threshold coherence fix (review finding #1/#4).

Three different operating thresholds used to be in play:
  1. The per-group fairness thresholds were anchored to the *cost-optimal*
     threshold (validation set) — trainer.py group-threshold search.
  2. The value persisted as ``ModelVersion.optimal_threshold`` was the
     *Youden's J* threshold (test set) — train_model.py / tasks.py.
  3. The reported confusion matrix / precision / recall / F1 / fairness DI were
     computed at the model's internal *0.5* cutoff (``model.predict``).

At serving the base threshold was Youden's J but per-group decisions used the
cost-optimal-anchored group thresholds, so the disparate-impact guarantee the
trainer computed did NOT hold at inference, and the displayed metrics described
a classifier the system never runs.

The fix collapses these to ONE operating point: the cost-optimal threshold
chosen on the validation split (``metrics["optimal_threshold"]``). It is
persisted as the base, applied to every applicant (no per-group thresholds),
recorded in training_metadata, and the headline classification + fairness
metrics are reported at it. These tests pin that coherence on both persistence
paths (sync management command and Celery task) and the reporting contract.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import joblib
import pytest
from django.core.management import call_command

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.datagen.data_generator import DataGenerator


@pytest.fixture
def small_csv(tmp_path):
    """A small but trainable synthetic dataset written to a temp CSV."""
    gen = DataGenerator()
    df = gen.generate(num_records=500, random_seed=99)
    path = tmp_path / "loans.csv"
    df.to_csv(path, index=False)
    return str(path)


def _assert_threshold_coherent(mv: ModelVersion) -> None:
    """One operating threshold, recorded where an auditor reads it.

    The persisted base threshold must equal the cost-optimal threshold chosen
    on the validation split, training_metadata must record that single
    threshold as the rule for every applicant, and neither the metadata nor
    the saved bundle may carry per-group thresholds (they were fitted on the
    test split and applied at serving while the metadata showed {}).
    """
    assert mv.optimal_threshold is not None, "optimal_threshold must be persisted"
    meta = mv.training_metadata
    anchor = meta["optimal_threshold"]
    assert mv.optimal_threshold == anchor, (
        f"persisted optimal_threshold ({mv.optimal_threshold}) must equal the threshold training selected ({anchor})"
    )
    assert meta["decision_threshold"] == {
        "value": anchor,
        "applies_to": "all_applicants",
        "selected_on": "validation",
        "method": "cost_optimal",
    }
    assert "group_thresholds" not in meta
    bundle = joblib.load(mv.file_path)
    assert "group_thresholds" not in bundle


@pytest.mark.django_db
def test_command_persists_one_threshold_for_every_applicant(small_csv):
    call_command("train_model", algorithm="rf", data_path=small_csv)
    mv = ModelVersion.objects.filter(is_active=True).order_by("-id").first()
    assert mv is not None
    try:
        _assert_threshold_coherent(mv)
    finally:
        if mv.file_path and os.path.exists(mv.file_path):
            os.unlink(mv.file_path)


@pytest.mark.django_db
def test_celery_task_persists_one_threshold_for_every_applicant(small_csv):
    from apps.ml_engine.tasks import _do_train

    # _do_train takes (task, algorithm, data_path, lock, *, segment); the task
    # and lock are only touched by the outer wrapper, so plain mocks suffice and
    # we avoid standing up redis. Fairness/promotion gates default to "warn"
    # (non-blocking), so a small rf model trains and activates cleanly.
    _do_train(MagicMock(), "rf", small_csv, MagicMock())
    mv = ModelVersion.objects.filter(is_active=True).order_by("-id").first()
    assert mv is not None
    try:
        _assert_threshold_coherent(mv)
    finally:
        if mv.file_path and os.path.exists(mv.file_path):
            os.unlink(mv.file_path)


@pytest.mark.django_db
def test_reported_metrics_declare_their_operating_threshold(small_csv):
    """#4: the confusion matrix / precision / recall / F1 must be computed at
    the operating threshold the system deploys, not the model's 0.5 cutoff. The
    trainer tags the reported metrics with ``classification_threshold`` so the
    dashboard can label them honestly; it must equal the operating threshold."""
    from apps.ml_engine.services.training.trainer import ModelTrainer

    _model, metrics = ModelTrainer().train(small_csv, algorithm="rf", use_reject_inference=False)
    assert "classification_threshold" in metrics, (
        "reported classification metrics must declare the threshold they were computed at"
    )
    assert metrics["classification_threshold"] == metrics["optimal_threshold"], (
        "confusion matrix / P / R / F1 must be reported at the operating threshold, not 0.5"
    )
