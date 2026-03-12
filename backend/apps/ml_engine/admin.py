from django.contrib import admin

from .models import ModelVersion, PredictionLog


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ('id', 'algorithm', 'version', 'is_active', 'accuracy', 'f1_score', 'auc_roc', 'created_at')
    list_filter = ('algorithm', 'is_active')
    search_fields = ('version',)
    readonly_fields = ('id', 'created_at')


@admin.register(PredictionLog)
class PredictionLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'application', 'model_version', 'prediction', 'probability', 'processing_time_ms', 'created_at')
    list_filter = ('prediction',)
    readonly_fields = ('id', 'created_at')
