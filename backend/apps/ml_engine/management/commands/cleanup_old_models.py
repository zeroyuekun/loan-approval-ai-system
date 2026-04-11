"""Prune historical ModelVersion rows and their on-disk joblib bundles.

By default, keeps the most recent ``--keep-last`` (default 10) inactive
ModelVersions and always preserves any model with ``is_active=True`` and any
model referenced by a ModelValidationReport. Runs in dry-run mode unless
``--apply`` is passed, so the operator can review what would be deleted.

Usage:
    # Show what would be deleted
    python manage.py cleanup_old_models

    # Keep the most recent 5 inactive models, actually delete the rest
    python manage.py cleanup_old_models --keep-last 5 --apply
"""

import uuid
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.ml_engine.models import ModelVersion


class Command(BaseCommand):
    help = "Delete old inactive ModelVersion rows and their on-disk joblib files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-last",
            type=int,
            default=10,
            help="Number of most recent inactive models to keep (default 10).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this flag the command runs as a dry-run.",
        )

    def handle(self, *args, **options):
        keep_last = options["keep_last"]
        apply_changes = options["apply"]

        if keep_last < 0:
            self.stderr.write(self.style.ERROR("--keep-last must be >= 0"))
            return

        # Identify protected versions: any active model and any version
        # referenced by a ModelValidationReport (champion or challenger).
        protected_ids: set = set(ModelVersion.objects.filter(is_active=True).values_list("id", flat=True))

        try:
            from apps.ml_engine.models import ModelValidationReport

            reports = ModelValidationReport.objects.all()
            protected_ids.update(reports.values_list("model_version_id", flat=True))

            # Also protect challenger models referenced inside the JSON blob.
            # validate_model.py stores `model_version: str(challenger.id)` per
            # entry, which the FK lookup above misses.
            for cc in reports.values_list("challenger_comparison", flat=True):
                if not isinstance(cc, dict):
                    continue
                for entry in cc.values():
                    if not isinstance(entry, dict):
                        continue
                    mv = entry.get("model_version")
                    if not mv:
                        continue
                    try:
                        protected_ids.add(uuid.UUID(str(mv)))
                    except (TypeError, ValueError):
                        continue
        except (ImportError, AttributeError):
            # ModelValidationReport may not exist in older deployments
            pass

        # Candidates: every non-protected model, ordered newest first.
        candidates = list(ModelVersion.objects.exclude(id__in=protected_ids).order_by("-created_at"))

        keep = candidates[:keep_last]
        delete = candidates[keep_last:]

        self.stdout.write(f"Total ModelVersions:        {ModelVersion.objects.count()}")
        self.stdout.write(f"Protected (active + cited): {len(protected_ids)}")
        self.stdout.write(f"Eligible candidates:        {len(candidates)}")
        self.stdout.write(f"Keeping (recent):           {len(keep)}")
        self.stdout.write(f"Marked for deletion:        {len(delete)}")

        if not delete:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        files_to_remove = []
        for mv in delete:
            self.stdout.write(
                f"  - {mv.version} ({mv.algorithm}) created {mv.created_at.isoformat()} -> {mv.file_path or '(no file)'}"
            )
            if mv.file_path:
                files_to_remove.append(Path(mv.file_path))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("\nDry-run only. Pass --apply to delete."))
            return

        deleted_rows = 0
        deleted_files = 0
        for mv in delete:
            try:
                if mv.file_path and Path(mv.file_path).exists():
                    Path(mv.file_path).unlink()
                    deleted_files += 1
            except OSError as e:
                self.stderr.write(self.style.WARNING(f"  could not delete file {mv.file_path}: {e}"))
            mv.delete()
            deleted_rows += 1

        self.stdout.write(
            self.style.SUCCESS(f"Done. Deleted {deleted_rows} ModelVersion rows and {deleted_files} joblib files.")
        )
