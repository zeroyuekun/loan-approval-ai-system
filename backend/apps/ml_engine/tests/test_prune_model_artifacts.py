"""Unit tests for the prune_model_artifacts management command.

Covers safety whitelist (active ModelVersion, contract_test, non-joblib
files), dry-run mode, and orphan-file handling.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.ml_engine.models import ModelVersion

pytestmark = pytest.mark.django_db


@pytest.fixture
def models_dir(tmp_path, settings):
    """Sandbox ML_MODELS_DIR so the command operates on fresh fixtures."""
    settings.ML_MODELS_DIR = str(tmp_path)
    return tmp_path


def _make_file(path: Path, size: int = 1024) -> Path:
    path.write_bytes(b"\0" * size)
    return path


def _make_version(
    *,
    file_path: Path,
    version: str,
    is_active: bool = False,
    segment: str = ModelVersion.SEGMENT_UNIFIED,
    traffic_percentage: int = 100,
) -> ModelVersion:
    # Active per-segment traffic must cap at 100; tests stay within a single
    # segment so the segment-active partial index is respected.
    return ModelVersion.objects.create(
        algorithm="xgb",
        version=version,
        file_path=str(file_path),
        file_hash="a" * 64,
        is_active=is_active,
        segment=segment,
        traffic_percentage=traffic_percentage if is_active else 0,
    )


def test_prune_keeps_active_and_recent_versions(models_dir: Path):
    """Active ModelVersion file + N most-recent inactive per segment are kept."""
    active = _make_file(models_dir / "xgb_active.joblib", 2048)
    keep_1 = _make_file(models_dir / "xgb_keep.joblib", 2048)
    stale_1 = _make_file(models_dir / "xgb_stale_1.joblib", 2048)
    stale_2 = _make_file(models_dir / "xgb_stale_2.joblib", 2048)
    _make_file(models_dir / "contract_test_model.joblib", 5)

    _make_version(file_path=active, version="1.0.0-active", is_active=True)
    _make_version(file_path=keep_1, version="1.0.0-keep")
    _make_version(file_path=stale_1, version="1.0.0-stale1")
    _make_version(file_path=stale_2, version="1.0.0-stale2")

    out = StringIO()
    call_command("prune_model_artifacts", "--keep", "1", stdout=out)

    assert active.exists(), "active ModelVersion must never be deleted"
    assert keep_1.exists(), "most recent inactive kept for rollback"
    assert not stale_1.exists(), "older inactive pruned"
    assert not stale_2.exists(), "older inactive pruned"
    assert (models_dir / "contract_test_model.joblib").exists(), (
        "contract_test_model.joblib is always whitelisted"
    )


def test_prune_dry_run_deletes_nothing(models_dir: Path):
    """--dry-run reports what would be deleted but touches no files."""
    stale = _make_file(models_dir / "xgb_stale.joblib", 2048)
    _make_version(file_path=stale, version="1.0.0-stale")

    out = StringIO()
    call_command("prune_model_artifacts", "--dry-run", stdout=out)

    assert stale.exists(), "dry-run must not delete anything"
    assert "would delete" in out.getvalue().lower()


def test_prune_handles_orphan_files_with_no_modelversion_row(models_dir: Path):
    """A joblib with no ModelVersion row is safe to delete."""
    orphan = _make_file(models_dir / "xgb_orphan.joblib", 2048)

    call_command("prune_model_artifacts")

    assert not orphan.exists(), "orphan files (no DB row) are deleted"


def test_prune_protects_non_joblib_files(models_dir: Path):
    """golden_metrics.json etc. are non-.joblib files — must not be touched."""
    (models_dir / "golden_metrics.json").write_text('{"auc": 0.87}')
    _make_file(models_dir / "xgb_stale.joblib", 2048)

    call_command("prune_model_artifacts")

    assert (models_dir / "golden_metrics.json").exists()


def test_prune_reports_bytes_reclaimed(models_dir: Path):
    """Command prints total bytes reclaimed for operator feedback."""
    _make_file(models_dir / "xgb_orphan.joblib", 10_000)

    out = StringIO()
    call_command("prune_model_artifacts", stdout=out)

    output = out.getvalue().lower()
    assert "bytes reclaimed" in output or "bytes freed" in output
