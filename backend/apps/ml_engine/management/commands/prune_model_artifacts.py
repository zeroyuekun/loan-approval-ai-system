"""Prune stale `.joblib` artifacts from `backend/ml_models/`.

Keeps: files referenced by any `is_active=True` ModelVersion, the N most
recent inactive versions per segment (default N=1), `contract_test_model.joblib`,
and any non-`.joblib` file (e.g. `golden_metrics.json`).

Deletes: every other `.joblib` file in `ML_MODELS_DIR`, including orphan
files with no ModelVersion row.

Complements `cleanup_old_models` (which prunes DB rows first and cascades to
files); this command prunes files first and leaves the DB alone, so it can
reclaim disk from the large tail of orphan `.joblib` files left by past
training experiments.

Usage:
    python manage.py prune_model_artifacts             # prune
    python manage.py prune_model_artifacts --dry-run   # preview
    python manage.py prune_model_artifacts --keep 2    # retain last 2 inactive per segment
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion

ALWAYS_KEEP = frozenset({"contract_test_model.joblib"})


class Command(BaseCommand):
    help = "Prune stale .joblib artifacts from ML_MODELS_DIR."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview deletions without touching disk.",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=1,
            help="Number of most-recent inactive ModelVersions per segment to retain (default: 1).",
        )

    def handle(self, *args, **opts):
        models_dir = Path(settings.ML_MODELS_DIR)
        if not models_dir.is_dir():
            raise CommandError(f"ML_MODELS_DIR not found: {models_dir}")

        dry_run: bool = opts["dry_run"]
        keep_n: int = max(0, int(opts["keep"]))

        keep_basenames = self._compute_whitelist(keep_n)
        self.stdout.write(f"Whitelist ({len(keep_basenames)} file(s)):")
        for name in sorted(keep_basenames):
            self.stdout.write(f"  KEEP  {name}")

        reclaimed = 0
        deleted = 0
        for joblib in sorted(models_dir.glob("*.joblib")):
            if joblib.name in keep_basenames:
                continue
            size = joblib.stat().st_size
            reclaimed += size
            deleted += 1
            verb = "would delete" if dry_run else "deleting"
            self.stdout.write(f"  {verb}  {joblib.name} ({size} bytes)")
            if not dry_run:
                joblib.unlink()

        mode = "(dry-run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Done {mode}: {deleted} file(s); {reclaimed} bytes reclaimed."
            )
        )

    def _compute_whitelist(self, keep_n: int) -> set[str]:
        keep: set[str] = set(ALWAYS_KEEP)

        for mv in ModelVersion.objects.filter(is_active=True):
            if mv.file_path:
                keep.add(Path(mv.file_path).name)

        per_segment: dict[str, list[ModelVersion]] = defaultdict(list)
        inactives: Iterable[ModelVersion] = (
            ModelVersion.objects.filter(is_active=False)
            .exclude(file_path="")
            .order_by("-created_at")
        )
        for mv in inactives:
            per_segment[getattr(mv, "segment", "unified")].append(mv)

        for _segment, versions in per_segment.items():
            for mv in versions[:keep_n]:
                keep.add(Path(mv.file_path).name)

        return keep
