from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.scoring.prediction_cache import file_sha256
from apps.ml_engine.services.scoring.predictor import clear_model_cache
from apps.ml_engine.services.training.trainer import ModelTrainer


class Command(BaseCommand):
    help = "Train a loan approval ML model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--algorithm",
            type=str,
            default="xgb",
            choices=["rf", "xgb"],
            help="Algorithm: rf (Random Forest), xgb (XGBoost). Default: xgb",
        )
        parser.add_argument(
            "--data-path",
            type=str,
            default=".tmp/synthetic_loans.csv",
            help="Path to training data CSV (default: .tmp/synthetic_loans.csv)",
        )

    def handle(self, *args, **options):
        algorithm = options["algorithm"]
        data_path = options["data_path"]

        self.stdout.write(f"Training {algorithm.upper()} model with data from {data_path}...")

        # Self-heal: parity with the Celery "Train Model" path so a fresh clone
        # (no .tmp/synthetic_loans.csv) doesn't die with a cryptic FileNotFoundError.
        from apps.ml_engine.tasks import _ensure_training_data, model_version_metric_fields

        if _ensure_training_data(data_path):
            self.stdout.write(self.style.WARNING(f"No training data at {data_path} — generated a synthetic dataset."))

        trainer = ModelTrainer()
        model, metrics = trainer.train(data_path, algorithm=algorithm)

        # Save model file
        version_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_filename = f"{algorithm}_{version_str}.joblib"
        model_path = str(settings.ML_MODELS_DIR / model_filename)
        trainer.save_model(model, model_path)

        file_hash = file_sha256(model_path)  # integrity check at load time

        # Deactivate existing active models before creating the new one
        ModelVersion.objects.filter(is_active=True).update(is_active=False)
        mv = ModelVersion.objects.create(
            algorithm=algorithm,
            version=version_str,
            file_path=model_path,
            file_hash=file_hash,
            is_active=True,
            **model_version_metric_fields(metrics),
        )

        # Invalidate cached models so workers pick up the new version
        clear_model_cache()

        self.stdout.write(
            self.style.SUCCESS(
                f"Model trained successfully: {mv}\n"
                f"  Accuracy:  {metrics['accuracy']:.4f}\n"
                f"  Precision: {metrics['precision']:.4f}\n"
                f"  Recall:    {metrics['recall']:.4f}\n"
                f"  F1 Score:  {metrics['f1_score']:.4f}\n"
                f"  AUC-ROC:   {metrics['auc_roc']:.4f}\n"
                f"  Gini:      {metrics.get('gini_coefficient', 'N/A')}\n"
                f"  KS Stat:   {metrics.get('ks_statistic', 'N/A')}\n"
                f"  Brier:     {metrics.get('brier_score', 'N/A')}\n"
                f"  ECE:       {metrics.get('calibration_data', {}).get('ece', 'N/A')}\n"
                f"  Threshold: {metrics.get('optimal_threshold', 'N/A')}\n"
                f"  Saved to:  {model_path}"
            )
        )
