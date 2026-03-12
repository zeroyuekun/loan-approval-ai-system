from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.trainer import ModelTrainer


class Command(BaseCommand):
    help = 'Train a loan approval ML model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--algorithm', type=str, default='xgb', choices=['rf', 'xgb'],
            help='Algorithm to use: rf (Random Forest) or xgb (XGBoost). Default: xgb',
        )
        parser.add_argument(
            '--data-path', type=str, default='.tmp/synthetic_loans.csv',
            help='Path to training data CSV (default: .tmp/synthetic_loans.csv)',
        )

    def handle(self, *args, **options):
        algorithm = options['algorithm']
        data_path = options['data_path']

        self.stdout.write(f'Training {algorithm.upper()} model with data from {data_path}...')

        trainer = ModelTrainer()
        model, metrics = trainer.train(data_path, algorithm=algorithm)

        # Save model file
        version_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        model_filename = f'{algorithm}_{version_str}.joblib'
        model_path = str(settings.ML_MODELS_DIR / model_filename)
        trainer.save_model(model, model_path)

        # Create ModelVersion record
        mv = ModelVersion.objects.create(
            algorithm=algorithm,
            version=version_str,
            file_path=model_path,
            is_active=True,
            accuracy=metrics['accuracy'],
            precision=metrics['precision'],
            recall=metrics['recall'],
            f1_score=metrics['f1_score'],
            auc_roc=metrics['auc_roc'],
            confusion_matrix=metrics['confusion_matrix'],
            feature_importances=metrics['feature_importances'],
            roc_curve_data=metrics['roc_curve'],
            training_params=metrics['training_params'],
        )

        self.stdout.write(self.style.SUCCESS(
            f'Model trained successfully: {mv}\n'
            f'  Accuracy:  {metrics["accuracy"]:.4f}\n'
            f'  Precision: {metrics["precision"]:.4f}\n'
            f'  Recall:    {metrics["recall"]:.4f}\n'
            f'  F1 Score:  {metrics["f1_score"]:.4f}\n'
            f'  AUC-ROC:   {metrics["auc_roc"]:.4f}\n'
            f'  Saved to:  {model_path}'
        ))
