from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
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

    def save(self, *args, **kwargs):
        self.clean()
        with transaction.atomic():
            if self.is_active:
                ModelVersion.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
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
