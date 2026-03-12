from datetime import datetime

from celery import shared_task
from django.conf import settings

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import ModelVersion, PredictionLog


@shared_task(bind=True, name='apps.ml_engine.tasks.train_model_task')
def train_model_task(self, algorithm='xgb', data_path=None):
    """Train a model asynchronously via Celery."""
    from apps.ml_engine.services.trainer import ModelTrainer

    if data_path is None:
        data_path = '.tmp/synthetic_loans.csv'

    trainer = ModelTrainer()
    model, metrics = trainer.train(data_path, algorithm=algorithm)

    version_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_filename = f'{algorithm}_{version_str}.joblib'
    model_path = str(settings.ML_MODELS_DIR / model_filename)
    trainer.save_model(model, model_path)

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

    return {'model_version_id': str(mv.id), 'metrics': metrics}


@shared_task(bind=True, name='apps.ml_engine.tasks.run_prediction_task')
def run_prediction_task(self, application_id):
    """Run ML prediction on a loan application."""
    from apps.ml_engine.services.predictor import ModelPredictor

    application = LoanApplication.objects.get(pk=application_id)
    application.status = 'processing'
    application.save(update_fields=['status'])

    predictor = ModelPredictor()
    result = predictor.predict(application)

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

    # Update application status
    application.status = result['prediction']
    application.save(update_fields=['status'])

    return {
        'application_id': str(application_id),
        'prediction': result['prediction'],
        'probability': result['probability'],
    }
