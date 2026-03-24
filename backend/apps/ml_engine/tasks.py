import hashlib
import logging
from datetime import datetime, timedelta

import numpy as np
from celery import shared_task
from django.conf import settings
from django.db.models import Avg, StdDev, Q
from django.utils import timezone

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog

logger = logging.getLogger(__name__)


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

    # Deactivate all existing active models before activating the new one
    ModelVersion.objects.filter(is_active=True).update(is_active=False, traffic_percentage=0)

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
            'shap_values': result.get('shap_values', {}),
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


def _compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Compute Population Stability Index between reference and current distributions."""
    eps = 1e-4
    breakpoints = np.linspace(0, 1, bins + 1)

    ref_counts = np.histogram(reference, bins=breakpoints)[0]
    cur_counts = np.histogram(current, bins=breakpoints)[0]

    ref_pct = ref_counts / ref_counts.sum() + eps
    cur_pct = cur_counts / cur_counts.sum() + eps

    psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
    return float(psi)


@shared_task(bind=True, name='apps.ml_engine.tasks.compute_weekly_drift_report', time_limit=600)
def compute_weekly_drift_report(self):
    """Compute weekly drift report comparing recent predictions to training distribution."""
    active_version = ModelVersion.objects.filter(is_active=True).first()
    if not active_version:
        logger.warning('No active model version found; skipping drift report.')
        return {'status': 'skipped', 'reason': 'no_active_model'}

    now = timezone.now().date()
    period_end = now
    period_start = now - timedelta(days=7)

    predictions = PredictionLog.objects.filter(
        model_version=active_version,
        created_at__date__gte=period_start,
        created_at__date__lte=period_end,
    )

    num_predictions = predictions.count()
    if num_predictions == 0:
        logger.info('No predictions in the last 7 days; skipping drift report.')
        return {'status': 'skipped', 'reason': 'no_predictions'}

    probabilities = np.array(
        list(predictions.values_list('probability', flat=True)), dtype=float
    )

    # Compute prediction distribution stats
    mean_prob = float(np.mean(probabilities))
    std_prob = float(np.std(probabilities))
    approval_rate = float(np.mean(probabilities >= 0.5))

    # Compute PSI against training reference distribution
    training_meta = active_version.training_metadata or {}
    reference_probs = training_meta.get('reference_probabilities')

    psi_score = None
    psi_per_feature = {}

    if reference_probs:
        ref_array = np.array(reference_probs, dtype=float)
        psi_score = _compute_psi(ref_array, probabilities)

        # Per-feature PSI if feature distributions are available
        ref_feature_dists = training_meta.get('feature_distributions', {})
        if ref_feature_dists:
            # Get feature values from recent predictions
            recent_features = list(predictions.values_list('feature_importances', flat=True))
            for feature_name, ref_dist in ref_feature_dists.items():
                cur_values = [
                    f.get(feature_name) for f in recent_features
                    if isinstance(f, dict) and f.get(feature_name) is not None
                ]
                if cur_values and ref_dist:
                    try:
                        psi_per_feature[feature_name] = _compute_psi(
                            np.array(ref_dist, dtype=float),
                            np.array(cur_values, dtype=float),
                        )
                    except (ValueError, TypeError):
                        pass

    # Determine alert level
    if psi_score is not None and psi_score >= 0.25:
        drift_detected = True
        alert_level = 'significant'
    elif psi_score is not None and psi_score >= 0.1:
        drift_detected = True
        alert_level = 'moderate'
    else:
        drift_detected = False
        alert_level = 'none'

    report = DriftReport.objects.update_or_create(
        model_version=active_version,
        report_date=now,
        defaults={
            'period_start': period_start,
            'period_end': period_end,
            'num_predictions': num_predictions,
            'psi_score': psi_score,
            'psi_per_feature': psi_per_feature,
            'mean_probability': mean_prob,
            'std_probability': std_prob,
            'approval_rate': approval_rate,
            'drift_detected': drift_detected,
            'alert_level': alert_level,
        },
    )[0]

    if psi_score is not None and psi_score >= 0.25:
        logger.warning(
            'Significant model drift detected: PSI=%.4f for model %s (report %s)',
            psi_score, active_version.id, report.id,
        )

    return {
        'status': 'completed',
        'report_id': str(report.id),
        'psi_score': psi_score,
        'alert_level': alert_level,
        'num_predictions': num_predictions,
    }
