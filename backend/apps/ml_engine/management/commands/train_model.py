from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.services.scoring.segmentation import SEGMENT_UNIFIED


class Command(BaseCommand):
    help = (
        "Train a loan approval ML model. Same path as the 'Train Model' button: holds the training "
        "lock, registers the model in its segment, and activates it only if the governance gates allow."
    )

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
        parser.add_argument(
            "--segment",
            type=str,
            default=SEGMENT_UNIFIED,
            help=f"Product segment to train and activate in (default: {SEGMENT_UNIFIED})",
        )

    def handle(self, *args, **options):
        from apps.ml_engine.models import ModelVersion
        from apps.ml_engine.tasks import _do_train, acquire_train_lock, release_train_lock

        algorithm = options["algorithm"]
        data_path = options["data_path"]

        lock = acquire_train_lock()
        if lock is None:
            raise CommandError("A training run is already in progress; wait for it to finish.")

        self.stdout.write(f"Training {algorithm.upper()} model with data from {data_path}...")
        try:
            result = _do_train(None, algorithm, data_path, lock, segment=options["segment"])
        except Exception:
            release_train_lock(lock)
            raise

        mv = ModelVersion.objects.get(pk=result["model_version_id"])
        metrics = result["metrics"]
        if result["activated"]:
            status = self.style.SUCCESS(f"Model trained and activated in segment '{mv.segment}': {mv}")
        else:
            blocked = ", ".join(mv.training_metadata.get("activation_blocked", []))
            status = self.style.WARNING(
                f"Model trained but NOT activated (blocked by: {blocked}); the current champion keeps serving: {mv}"
            )
        self.stdout.write(
            f"{status}\n"
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
            f"  Saved to:  {mv.file_path}"
        )
