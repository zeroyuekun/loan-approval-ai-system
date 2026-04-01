from django.contrib import admin

from .models import AgentRun, APICallLog, BiasReport, NextBestOffer


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "status", "total_time_ms", "created_at")
    list_filter = ("status",)
    search_fields = ("application__applicant__username",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(BiasReport)
class BiasReportAdmin(admin.ModelAdmin):
    list_display = ("id", "agent_run", "bias_score", "flagged", "requires_human_review", "created_at")
    list_filter = ("flagged", "requires_human_review")
    readonly_fields = ("id", "created_at")


@admin.register(NextBestOffer)
class NextBestOfferAdmin(admin.ModelAdmin):
    list_display = ("id", "agent_run", "application", "created_at")
    readonly_fields = ("id", "created_at")


@admin.register(APICallLog)
class APICallLogAdmin(admin.ModelAdmin):
    list_display = ("id", "service", "provider", "model_used", "loan_application", "timestamp")
    list_filter = ("service", "provider", "destination_country")
    search_fields = ("loan_application__id", "service")
    readonly_fields = ("id", "timestamp", "prompt_hash")
