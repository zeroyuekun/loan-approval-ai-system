"""Backfill training_metadata.psi_by_feature on existing model versions.

Models trained before the trainer's psi_by_feature mirror landed have
empty `mv.training_metadata.psi_by_feature`, so the dossier prints
"No PSI data recorded" even when reference distributions exist in the
bundle. This command computes per-feature PSI between the bundle's
stored feature_distributions (training reference) and a fresh
DataGenerator batch (the proxy for "current" data), and writes the
result into mv.training_metadata.psi_by_feature.

Idempotent — refuses to overwrite without --force.
"""

import joblib
import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.metrics import psi_by_feature
from apps.ml_engine.services.prediction_cache import _validate_model_path


class Command(BaseCommand):
    help = "Backfill ModelVersion.training_metadata.psi_by_feature for models that pre-date the trainer mirror."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--model-id", type=str, help="UUID of a specific ModelVersion to backfill.")
        target.add_argument("--all-active", action="store_true", help="Backfill every is_active=True ModelVersion.")
        parser.add_argument(
            "--sample", type=int, default=5000,
            help="DataGenerator sample size used as the 'current' frame for PSI (default 5000).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite existing training_metadata.psi_by_feature. Default refuses.",
        )

    def handle(self, *args, **options):
        if options["all_active"]:
            targets = list(ModelVersion.objects.filter(is_active=True))
        else:
            try:
                targets = [ModelVersion.objects.get(id=options["model_id"])]
            except ModelVersion.DoesNotExist:
                raise CommandError(f"ModelVersion {options['model_id']} not found")

        if not targets:
            self.stdout.write("No matching models found.")
            return

        for mv in targets:
            self._backfill_one(mv, options["sample"], options["force"])

    def _backfill_one(self, mv: ModelVersion, sample_size: int, force: bool) -> None:
        from apps.ml_engine.services.data_generator import DataGenerator
        from apps.ml_engine.services.predictor import ModelPredictor

        meta = dict(mv.training_metadata or {})
        if meta.get("psi_by_feature") and not force:
            self.stdout.write(
                f"[skip] {mv.algorithm} v{mv.version}: psi_by_feature already populated; "
                f"pass --force to overwrite."
            )
            return

        try:
            bundle_path = _validate_model_path(mv.file_path)
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(f"Bundle path invalid for {mv.id}: {exc}")

        bundle = joblib.load(bundle_path)
        ref_dist = bundle.get("reference_distribution") or {}
        feature_distributions = ref_dist.get("feature_distributions") or {}
        if not feature_distributions:
            raise CommandError(
                f"Bundle for {mv.id} has no feature_distributions in reference_distribution; "
                f"run backfill_reference_distribution first."
            )

        train_df = pd.DataFrame({col: vals for col, vals in feature_distributions.items()})

        gen_df = DataGenerator().generate(num_records=sample_size, random_seed=42, label_noise_rate=0.05)
        for target_col in ("default_flag", "approved", "is_default"):
            if target_col in gen_df.columns:
                gen_df = gen_df.drop(columns=[target_col])

        try:
            predictor = ModelPredictor(model_version=mv)
        except Exception as exc:
            raise CommandError(f"Could not load predictor for {mv.id}: {exc}")

        try:
            current_df = predictor._transform(gen_df.copy())
        except Exception as exc:
            raise CommandError(f"Feature transformation failed for {mv.id}: {exc}")

        feature_cols = [c for c in feature_distributions.keys() if c in current_df.columns]
        if not feature_cols:
            raise CommandError(
                f"No overlap between bundle feature_distributions and predictor output for {mv.id}; "
                f"cannot compute PSI."
            )

        try:
            psi_map = psi_by_feature(train_df, current_df, feature_cols)
        except Exception as exc:
            raise CommandError(f"psi_by_feature computation failed for {mv.id}: {exc}")

        meta["psi_by_feature"] = psi_map
        mv.training_metadata = meta
        mv.save(update_fields=["training_metadata"])

        self.stdout.write(self.style.SUCCESS(
            f"[ok] {mv.algorithm} v{mv.version}: wrote psi_by_feature with {len(psi_map)} feature columns"
        ))
