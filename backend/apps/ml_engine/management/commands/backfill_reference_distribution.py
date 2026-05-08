"""Backfill probability_distribution + feature_distributions on existing model bundles.

Models trained before the trainer hook landed (commits leading up to this
file) lack the keys both drift code paths consume. This command is the
one-shot patch: run the model on a fresh DataGenerator batch, populate the
two bundle keys + ModelVersion.training_metadata.reference_probabilities,
and atomically re-save the bundle.

Idempotent -- refuses to overwrite by default; pass --force to overwrite.
"""

import os

import joblib
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.prediction_cache import _validate_model_path


class Command(BaseCommand):
    help = "Backfill bundle reference_distribution + training_metadata.reference_probabilities for existing models."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--model-id", type=str, help="UUID of a specific ModelVersion to backfill.")
        target.add_argument("--all-active", action="store_true", help="Backfill every is_active=True ModelVersion.")
        parser.add_argument(
            "--sample", type=int, default=5000,
            help="DataGenerator sample size used to seed the holdout reference (default 5000, capped at 1000 in bundle).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite probability_distribution if already populated. Default refuses.",
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

        try:
            bundle_path = _validate_model_path(mv.file_path)
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(f"Bundle path invalid for {mv.id}: {exc}")

        bundle = joblib.load(bundle_path)
        ref_dist = dict(bundle.get("reference_distribution") or {})

        already = bool(ref_dist.get("probability_distribution"))
        if already and not force:
            self.stdout.write(
                f"[skip] {mv.algorithm} v{mv.version}: probability_distribution already populated; "
                f"pass --force to overwrite."
            )
            return

        self.stdout.write(f"[backfill] {mv.algorithm} v{mv.version} ({mv.id})")
        gen_df = DataGenerator().generate(num_records=sample_size, random_seed=42, label_noise_rate=0.05)

        # Drop the target column if present (DataGenerator outputs include it).
        for target_col in ("default_flag", "approved", "is_default"):
            if target_col in gen_df.columns:
                gen_df = gen_df.drop(columns=[target_col])

        from apps.ml_engine.services.predictor import ModelPredictor

        try:
            predictor = ModelPredictor(model_version=mv)
        except Exception as exc:
            raise CommandError(f"Could not load predictor for {mv.id}: {exc}")

        try:
            transformed = predictor._transform(gen_df.copy())
        except Exception as exc:
            raise CommandError(
                f"Feature transformation failed for {mv.id}: {exc}. "
                f"DataGenerator output may be missing columns the predictor pipeline expects."
            )

        try:
            probs = predictor.model.predict_proba(transformed[predictor.feature_cols])[:, 1]
        except Exception as exc:
            raise CommandError(f"predict_proba failed for {mv.id}: {exc}")

        # Capture raw (untransformed) numeric feature distributions — not the
        # one-hot encoded transformed columns, which would balloon the bundle
        # without adding statistical signal.
        feature_capture_cols = [c for c in (bundle.get("numeric_cols") or []) if c in gen_df.columns]

        cap = 1000
        if len(probs) > cap:
            import numpy as np
            rng = np.random.default_rng(42)
            idx = rng.choice(len(probs), size=cap, replace=False)
            prob_sample = probs[idx].tolist()
            feat_sample = {col: gen_df[col].iloc[idx].tolist() for col in feature_capture_cols}
        else:
            prob_sample = list(map(float, probs))
            feat_sample = {col: gen_df[col].tolist() for col in feature_capture_cols}

        ref_dist["probability_distribution"] = prob_sample
        ref_dist["feature_distributions"] = feat_sample
        bundle["reference_distribution"] = ref_dist

        # Atomic re-save: write to .tmp then rename.
        tmp_path = f"{bundle_path}.tmp"
        joblib.dump(bundle, tmp_path)
        os.replace(tmp_path, bundle_path)

        meta = dict(mv.training_metadata or {})
        meta["reference_probabilities"] = prob_sample
        mv.training_metadata = meta
        mv.save(update_fields=["training_metadata"])

        self.stdout.write(self.style.SUCCESS(
            f"[ok] {mv.algorithm} v{mv.version}: wrote {len(prob_sample)} probs + "
            f"{len(feat_sample)} feature columns"
        ))
