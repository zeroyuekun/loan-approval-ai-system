import hashlib
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.predictor import clear_model_cache
from apps.ml_engine.services.trainer import ModelTrainer


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

        trainer = ModelTrainer()
        model, metrics = trainer.train(data_path, algorithm=algorithm)

        # Save model file
        version_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_filename = f"{algorithm}_{version_str}.joblib"
        model_path = str(settings.ML_MODELS_DIR / model_filename)
        trainer.save_model(model, model_path)

        # Compute SHA-256 hash of saved model file for integrity verification
        sha256 = hashlib.sha256()
        with open(model_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        file_hash = sha256.hexdigest()

        # Deactivate existing active models before creating the new one
        ModelVersion.objects.filter(is_active=True).update(is_active=False)
        mv = ModelVersion.objects.create(
            algorithm=algorithm,
            version=version_str,
            file_path=model_path,
            file_hash=file_hash,
            is_active=True,
            accuracy=metrics["accuracy"],
            precision=metrics["precision"],
            recall=metrics["recall"],
            f1_score=metrics["f1_score"],
            auc_roc=metrics["auc_roc"],
            brier_score=metrics.get("brier_score"),
            gini_coefficient=metrics.get("gini_coefficient"),
            ks_statistic=metrics.get("ks_statistic"),
            log_loss_value=metrics.get("log_loss"),
            ece=metrics.get("calibration_data", {}).get("ece"),
            optimal_threshold=metrics.get("threshold_analysis", {}).get("youden_j_threshold"),
            confusion_matrix=metrics["confusion_matrix"],
            feature_importances=metrics["feature_importances"],
            roc_curve_data=metrics["roc_curve"],
            training_params=metrics["training_params"],
            calibration_data=metrics.get("calibration_data", {}),
            threshold_analysis=metrics.get("threshold_analysis", {}),
            decile_analysis=metrics.get("decile_analysis", {}),
            fairness_metrics=metrics.get("fairness", {}),
            training_metadata=metrics.get("training_metadata", {}),
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
                f"  Threshold: {metrics.get('threshold_analysis', {}).get('youden_j_threshold', 'N/A')}\n"
                f"  Saved to:  {model_path}"
            )
        )
