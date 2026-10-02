from django.contrib import admin

from apps.common.admin import ViewOnlyModelAdmin

from .models import ModelVersion, PredictionLog


@admin.register(ModelVersion)
class ModelVersionAdmin(ViewOnlyModelAdmin):
    """View-only: which model serves, its traffic share, threshold and artefact
    change only through the activation service (gates, segment lock, audit)."""

    list_display = ("id", "algorithm", "version", "is_active", "accuracy", "f1_score", "auc_roc", "created_at")
    list_filter = ("algorithm", "is_active")
    search_fields = ("version",)
    readonly_fields = ("id", "created_at")


@admin.register(PredictionLog)
class PredictionLogAdmin(ViewOnlyModelAdmin):
    """View-only: the record of what the model returned for an application."""

    list_display = (
        "id",
        "application",
        "model_version",
        "prediction",
        "probability",
        "processing_time_ms",
        "created_at",
    )
    list_filter = ("prediction",)
    readonly_fields = ("id", "created_at")
