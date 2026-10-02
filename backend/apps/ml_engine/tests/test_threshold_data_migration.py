"""Existing models serve at the threshold training chose on the validation split.

Models trained before the threshold-coherence fix persisted Youden's J on the
TEST split as ModelVersion.optimal_threshold (the live champion: 0.5), while
the validation-chosen cost-optimal threshold (0.87) went to
training_metadata.optimal_threshold and anchored the per-group thresholds that
actually served. With per-group thresholds ignored, scoring would fall back to
the test-split 0.5 and loosen approval for most applicants. Migration 0010
persists the validation-chosen threshold and keeps the old value for rollback.
"""

import importlib

import pytest
from django.apps import apps as global_apps

from apps.ml_engine.models import ModelVersion

migration = importlib.import_module("apps.ml_engine.migrations.0010_persist_validation_threshold")

pytestmark = pytest.mark.django_db


def _mv(settings, tmp_path, version, optimal, meta):
    settings.ML_MODELS_DIR = tmp_path
    settings.MRM_DOSSIER_AUTO_GENERATE = False
    return ModelVersion.objects.create(
        algorithm="xgb",
        version=version,
        file_path=str(tmp_path / f"{version}.joblib"),
        optimal_threshold=optimal,
        training_metadata=meta,
    )


def test_a_legacy_row_serves_at_its_validation_chosen_threshold(settings, tmp_path):
    mv = _mv(settings, tmp_path, "legacy", 0.5, {"optimal_threshold": 0.87, "group_thresholds": {}})

    migration.persist_validation_threshold(global_apps, None)

    mv.refresh_from_db()
    assert mv.optimal_threshold == 0.87
    assert mv.training_metadata["superseded_optimal_threshold"] == 0.5
    assert mv.training_metadata["decision_threshold"] == {
        "value": 0.87,
        "applies_to": "all_applicants",
        "selected_on": "validation",
        "method": "cost_optimal",
    }

    migration.restore_superseded_threshold(global_apps, None)
    mv.refresh_from_db()
    assert mv.optimal_threshold == 0.5
    assert "superseded_optimal_threshold" not in mv.training_metadata


def test_coherent_rows_and_rows_without_a_recorded_threshold_are_untouched(settings, tmp_path):
    coherent = _mv(settings, tmp_path, "coherent", 0.6, {"optimal_threshold": 0.6})
    bare = _mv(settings, tmp_path, "bare", 0.55, {})

    migration.persist_validation_threshold(global_apps, None)

    coherent.refresh_from_db()
    bare.refresh_from_db()
    assert (coherent.optimal_threshold, coherent.training_metadata) == (0.6, {"optimal_threshold": 0.6})
    assert (bare.optimal_threshold, bare.training_metadata) == (0.55, {})


def test_the_migration_records_the_threshold_the_stored_metrics_were_computed_at(settings, tmp_path):
    """The confusion matrix, precision/recall and fairness ratios on a legacy row
    were computed at the old threshold; only the serving threshold moved."""
    mv = _mv(settings, tmp_path, "legacy_metrics", 0.5, {"optimal_threshold": 0.87})

    migration.persist_validation_threshold(global_apps, None)
    mv.refresh_from_db()
    assert mv.training_metadata["metrics_threshold"] == 0.5
    assert mv.stale_metrics_threshold() == 0.5

    migration.restore_superseded_threshold(global_apps, None)
    mv.refresh_from_db()
    assert "metrics_threshold" not in mv.training_metadata
    assert mv.stale_metrics_threshold() is None
