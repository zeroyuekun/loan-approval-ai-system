from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
import uuid


class ModelVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    algorithm = models.CharField(
        max_length=20, choices=[('rf', 'Random Forest'), ('xgb', 'XGBoost')]
    )
    version = models.CharField(max_length=50)
    file_path = models.CharField(max_length=500)
    file_hash = models.CharField(max_length=64, blank=True, help_text="SHA-256 hash for integrity verification")
    is_active = models.BooleanField(default=False)
    traffic_percentage = models.IntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Percentage of predictions routed to this model (for A/B testing)',
    )

    # Metrics
    accuracy = models.FloatField(null=True)
    precision = models.FloatField(null=True)
    recall = models.FloatField(null=True)
    f1_score = models.FloatField(null=True)
    auc_roc = models.FloatField(null=True)
    brier_score = models.FloatField(null=True)
    gini_coefficient = models.FloatField(null=True)
    ks_statistic = models.FloatField(null=True)
    log_loss_value = models.FloatField(null=True)
    ece = models.FloatField(null=True)
    optimal_threshold = models.FloatField(null=True)
    confusion_matrix = models.JSONField(default=dict)
    feature_importances = models.JSONField(default=dict)
    roc_curve_data = models.JSONField(default=dict)
    training_params = models.JSONField(default=dict)
    calibration_data = models.JSONField(default=dict)
    threshold_analysis = models.JSONField(default=dict)
    decile_analysis = models.JSONField(default=dict)
    fairness_metrics = models.JSONField(default=dict)
    training_metadata = models.JSONField(default=dict)

    # Model governance (SR 11-7 / APRA CPG 235 alignment)
    decision_threshold_approve = models.FloatField(
        null=True, blank=True,
        help_text='Confidence >= this threshold → approve',
    )
    decision_threshold_deny = models.FloatField(
        null=True, blank=True,
        help_text='Confidence <= this threshold → deny',
    )
    decision_threshold_review = models.FloatField(
        null=True, blank=True,
        help_text='Between deny and approve → human review',
    )
    next_review_date = models.DateField(
        null=True, blank=True,
        help_text='Scheduled performance review / revalidation date',
    )
    explainability_method = models.CharField(
        max_length=50, default='shap_tree',
        help_text='Explainability framework used (e.g. shap_tree, lime)',
    )
    retired_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When this model version was retired from production',
    )
    retraining_policy = models.JSONField(
        default=dict, blank=True,
        help_text='Retraining cadence, validation criteria, and data requirements (SR 11-7)',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_algorithm_display()} v{self.version} (active={self.is_active})"

    def clean(self):
        super().clean()
        if self.file_path:
            models_dir = Path(settings.ML_MODELS_DIR).resolve()
            resolved = Path(self.file_path).resolve()
            if not resolved.is_relative_to(models_dir):
                raise ValidationError(
                    {'file_path': f'Model file must be within {models_dir}'}
                )
            if resolved.suffix != '.joblib':
                raise ValidationError(
                    {'file_path': 'Model file must have .joblib extension'}
                )
        if self.is_active:
            other_traffic = (
                ModelVersion.objects.filter(is_active=True)
                .exclude(pk=self.pk)
                .aggregate(total=models.Sum('traffic_percentage'))['total']
            ) or 0
            if other_traffic + (self.traffic_percentage or 0) > 100:
                raise ValidationError(
                    f'Total traffic would be {other_traffic + (self.traffic_percentage or 0)}% '
                    f'(max 100%). Reduce other models\' traffic first.'
                )

    def save(self, *args, **kwargs):
        self.clean()
        with transaction.atomic():
            super().save(*args, **kwargs)


class PredictionLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_version = models.ForeignKey(ModelVersion, on_delete=models.SET_NULL, null=True)
    application = models.ForeignKey(
        'loans.LoanApplication', on_delete=models.CASCADE, related_name='predictions'
    )
    prediction = models.CharField(max_length=20)
    probability = models.FloatField()
    feature_importances = models.JSONField(default=dict)
    processing_time_ms = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prediction for {self.application_id}: {self.prediction}"


class DriftReport(models.Model):
    """Weekly model drift monitoring report."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE, related_name='drift_reports')
    report_date = models.DateField(db_index=True)
    period_start = models.DateField()
    period_end = models.DateField()
    num_predictions = models.IntegerField(default=0)

    # Population Stability Index
    psi_score = models.FloatField(null=True, help_text='PSI: <0.1 stable, 0.1-0.25 moderate, >0.25 significant drift')
    psi_per_feature = models.JSONField(default=dict, help_text='PSI score per feature')

    # Prediction distribution stats
    mean_probability = models.FloatField(null=True)
    std_probability = models.FloatField(null=True)
    approval_rate = models.FloatField(null=True)

    # Alert status
    drift_detected = models.BooleanField(default=False)
    alert_level = models.CharField(
        max_length=20,
        choices=[('none', 'None'), ('moderate', 'Moderate'), ('significant', 'Significant')],
        default='none',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-report_date']
        unique_together = [('model_version', 'report_date')]

    def __str__(self):
        return f"DriftReport {self.report_date}: PSI={self.psi_score}, alert={self.alert_level}"
