import hashlib
from datetime import datetime

from celery import shared_task
from django.conf import settings

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import ModelVersion, PredictionLog


@shared_task(bind=True, name='apps.ml_engine.tasks.train_model_task', time_limit=1800)
def train_model_task(self, algorithm='xgb', data_path=None):
    """Train a model asynchronously via Celery."""
    from apps.ml_engine.services.trainer import ModelTrainer
    from apps.ml_engine.services.predictor import clear_model_cache

    if data_path is None:
        data_path = '.tmp/synthetic_loans.csv'

    trainer = ModelTrainer()
    model, metrics = trainer.train(data_path, algorithm=algorithm)

    version_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_filename = f'{algorithm}_{version_str}.joblib'
    model_path = str(settings.ML_MODELS_DIR / model_filename)
    trainer.save_model(model, model_path)

    # Compute SHA-256 hash of saved model file for integrity verification
    sha256 = hashlib.sha256()
    with open(model_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    # ModelVersion.save() atomically deactivates other versions when is_active=True
    mv = ModelVersion.objects.create(
        algorithm=algorithm,
        version=version_str,
        file_path=model_path,
        file_hash=file_hash,
        is_active=True,
        accuracy=metrics['accuracy'],
        precision=metrics['precision'],
        recall=metrics['recall'],
        f1_score=metrics['f1_score'],
        auc_roc=metrics['auc_roc'],
        brier_score=metrics.get('brier_score'),
        gini_coefficient=metrics.get('gini_coefficient'),
        ks_statistic=metrics.get('ks_statistic'),
        log_loss_value=metrics.get('log_loss'),
        ece=metrics.get('calibration_data', {}).get('ece'),
        optimal_threshold=metrics.get('threshold_analysis', {}).get('youden_j_threshold'),
        confusion_matrix=metrics['confusion_matrix'],
        feature_importances=metrics['feature_importances'],
        roc_curve_data=metrics['roc_curve'],
        training_params=metrics['training_params'],
        calibration_data=metrics.get('calibration_data', {}),
        threshold_analysis=metrics.get('threshold_analysis', {}),
        decile_analysis=metrics.get('decile_analysis', {}),
        fairness_metrics=metrics.get('fairness', {}),
        training_metadata=metrics.get('training_metadata', {}),
    )

    # Invalidate cached models so workers pick up the new version
    clear_model_cache()

    return {'model_version_id': str(mv.id), 'metrics': metrics}


@shared_task(
    bind=True,
    name='apps.ml_engine.tasks.run_prediction_task',
    time_limit=120,
    soft_time_limit=100,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=2,
)
def run_prediction_task(self, application_id):
    """Run ML prediction on a loan application."""
    from apps.ml_engine.services.predictor import ModelPredictor

    application = LoanApplication.objects.get(pk=application_id)
    application.status = 'processing'
    application.save(update_fields=['status'])

    try:
        predictor = ModelPredictor()
        result = predictor.predict(application)
    except Exception:
        # Revert status so the application isn't stuck in 'processing'
        application.status = 'pending'
        application.save(update_fields=['status'])
        raise

    # Save prediction log
    PredictionLog.objects.create(
        model_version_id=result['model_version'],
        application=application,
        prediction=result['prediction'],
        probability=result['probability'],
        feature_importances=result['feature_importances'],
        processing_time_ms=result['processing_time_ms'],
    )

    # Save loan decision
    LoanDecision.objects.update_or_create(
        application=application,
        defaults={
            'decision': result['prediction'],
            'confidence': result['probability'],
            'feature_importances': result['feature_importances'],
            'model_version': result['model_version'],
        },
    )

    # Update application status — flag borderline cases for human review
    if result.get('requires_human_review'):
        application.status = 'review'
    else:
        application.status = result['prediction']
    application.save(update_fields=['status'])

    return {
        'application_id': str(application_id),
        'prediction': result['prediction'],
        'probability': result['probability'],
    }
