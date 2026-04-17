from django.contrib import admin

from .models import Complaint, LoanApplication, LoanDecision, PipelineDispatchOutbox


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "applicant",
        "loan_amount",
        "purpose",
        "status",
        "credit_score",
        "employment_type",
        "created_at",
    )
    list_filter = ("status", "purpose", "home_ownership", "employment_type", "applicant_type", "has_cosigner")
    search_fields = ("applicant__username", "applicant__email", "notes")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(LoanDecision)
class LoanDecisionAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "decision", "confidence", "model_version", "created_at")
    list_filter = ("decision",)
    search_fields = ("application__applicant__username",)
    readonly_fields = ("id", "created_at")


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("id", "complainant", "category", "status", "sla_deadline", "created_at")
    list_filter = ("status", "category")
    search_fields = ("complainant__username", "subject", "description")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(PipelineDispatchOutbox)
class PipelineDispatchOutboxAdmin(admin.ModelAdmin):
    list_display = ("application", "attempts", "last_attempt_at", "created_at")
    list_filter = ("attempts",)
    search_fields = ("application__id",)
    readonly_fields = ("id", "application", "attempts", "last_error", "last_attempt_at", "created_at")
    ordering = ("-created_at",)
