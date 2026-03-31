from django.contrib import admin

from .models import AgentRun, BiasReport, NextBestOffer


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
