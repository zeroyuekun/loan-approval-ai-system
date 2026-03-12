from django.db import models
import uuid


class ModelVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    algorithm = models.CharField(
        max_length=20, choices=[('rf', 'Random Forest'), ('xgb', 'XGBoost')]
    )
    version = models.CharField(max_length=50)
    file_path = models.CharField(max_length=500)
    is_active = models.BooleanField(default=False)

    # Metrics
    accuracy = models.FloatField(null=True)
    precision = models.FloatField(null=True)
    recall = models.FloatField(null=True)
    f1_score = models.FloatField(null=True)
    auc_roc = models.FloatField(null=True)
    confusion_matrix = models.JSONField(default=dict)
    feature_importances = models.JSONField(default=dict)
    roc_curve_data = models.JSONField(default=dict)
    training_params = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_algorithm_display()} v{self.version} (active={self.is_active})"

    def save(self, *args, **kwargs):
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
