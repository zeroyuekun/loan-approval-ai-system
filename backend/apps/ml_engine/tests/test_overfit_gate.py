"""Tests for the validation-split overfitting gate.

Task 1: the trainer records `val_auc` and `overfitting_gap_val` (train AUC
minus validation AUC) in `training_metadata`, so overfitting can be judged
before the test set is ever read.

Task 2: `model_selector.promote_if_eligible` gate 5 rejects a challenger
whose train-vs-validation gap exceeds `ML_OVERFIT_MAX_GAP` (default 0.05),
treats a missing gap as not-assessable (passes), and is overridable via
the `ML_OVERFIT_MAX_GAP` setting. It runs before the no-champion
short-circuit, so it applies with or without an incumbent.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# Task 2 — promote_if_eligible gate 5 (overfitting)
# ---------------------------------------------------------------------------


def _make_mv(*, id_="cand-1", overfitting_gap_val=0.03, psi_by_feature_map=None, ece=0.02):
    """Build a stub ModelVersion that passes PSI + ECE, varying only the
    overfitting gap under test (mirrors _make_mv in
    test_metrics_production_grade.py)."""
    mv = MagicMock()
    mv.id = id_
    mv.pk = id_
    mv.segment = "unified"
    mv.auc_roc = 0.88
    mv.ks_statistic = 0.45
    mv.ece = ece
    psi_feat = {"f1": 0.05, "f2": 0.08} if psi_by_feature_map is None else psi_by_feature_map
    meta = {"psi_by_feature": psi_feat}
    if overfitting_gap_val is not None:
        meta["overfitting_gap_val"] = overfitting_gap_val
    mv.training_metadata = meta
    return mv


@pytest.fixture
def no_champion(monkeypatch):
    """No incumbent champion — gate 5 must still run before the short-circuit."""
    from apps.ml_engine.services import model_selector as ms

    fake_qs = MagicMock()
    fake_qs.exclude.return_value = fake_qs
    fake_qs.order_by.return_value = fake_qs
    fake_qs.first.return_value = None
    fake_manager = MagicMock()
    fake_manager.filter.return_value = fake_qs
    monkeypatch.setattr(ms.ModelVersion, "objects", fake_manager, raising=False)


def test_overfit_gap_beyond_limit_rejects(no_champion):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(overfitting_gap_val=0.08)
    result = ms.promote_if_eligible(candidate)
    assert not result.promoted
    assert any("Overfitting gate failed" in r for r in result.reasons)
    assert result.gates["overfitting"]["passed"] is False


def test_overfit_gap_within_limit_passes(no_champion):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(overfitting_gap_val=0.03)
    result = ms.promote_if_eligible(candidate)
    assert result.promoted, result.reasons
    assert result.gates["overfitting"]["passed"] is True


def test_overfit_gap_missing_is_not_assessable_and_passes(no_champion):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(overfitting_gap_val=None)
    result = ms.promote_if_eligible(candidate)
    assert result.promoted, result.reasons
    assert result.gates["overfitting"]["not_assessable"] is True
    assert result.gates["overfitting"]["passed"] is True


def test_overfit_gap_setting_override_relaxes_limit(no_champion, settings):
    from apps.ml_engine.services import model_selector as ms

    settings.ML_OVERFIT_MAX_GAP = 0.10
    candidate = _make_mv(overfitting_gap_val=0.08)
    result = ms.promote_if_eligible(candidate)
    assert result.promoted, result.reasons
    assert result.gates["overfitting"]["passed"] is True


@pytest.mark.parametrize(("raw", "expected"), [("", 0.05), ("not-a-number", 0.05), ("0.08", 0.08)])
def test_overfit_max_gap_setting_tolerates_empty_or_malformed_env(monkeypatch, raw, expected):
    """An empty or malformed ML_OVERFIT_MAX_GAP falls back to 0.05 instead of
    crashing settings import (the same tolerance as the other _env_float knobs)."""
    import runpy
    import warnings
    from pathlib import Path

    from django.conf import settings as dj_settings

    monkeypatch.setenv("ML_OVERFIT_MAX_GAP", raw)
    base = Path(dj_settings.BASE_DIR) / "config" / "settings" / "base.py"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        namespace = runpy.run_path(str(base))
    assert namespace["ML_OVERFIT_MAX_GAP"] == pytest.approx(expected)
