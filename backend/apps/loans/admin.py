from django.contrib import admin, messages
from django.db import transaction

from .models import Complaint, DecisionReview, LoanApplication, LoanDecision, PipelineDispatchOutbox
from .services.decision_review import apply_review_outcome
from .tasks import dispatch_pipeline_or_queue_failed


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

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is None and "applicant" in form.base_fields:
            form.base_fields["applicant"].required = False
            form.base_fields["applicant"].help_text = (
                "Leave blank to use your own admin account as the applicant — "
                "the decision email will be sent to your address."
            )
        return form

    def save_model(self, request, obj, form, change):
        """Default applicant to the logged-in admin and trigger the orchestrator on create.

        Mirrors the API's ``perform_create`` so applications created via the Django
        admin get the same auto-pipeline + decision-email flow.
        """
        if obj.applicant_id is None:
            obj.applicant = request.user

        super().save_model(request, obj, form, change)

        if change:
            return

        # messages.warning is NOT reliable inside the on_commit callback — it fires
        # after MessageMiddleware has serialized request._messages, so failure
        # visibility comes from the QUEUE_FAILED status flip instead.
        transaction.on_commit(lambda: dispatch_pipeline_or_queue_failed(obj, source="admin"))

        recipient = getattr(obj.applicant, "email", "") if obj.applicant_id else ""
        if recipient:
            messages.success(
                request,
                f"Application queued — the decision email will be sent to {recipient} once processing completes.",
            )
        else:
            messages.warning(
                request,
                "Application queued, but applicant has no email on file — no decision email will be sent.",
            )


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


@admin.register(DecisionReview)
class DecisionReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "requested_by", "status", "assigned_officer", "requested_at")
    list_filter = ("status",)
    search_fields = ("application__id", "requested_by__username", "reason")
    readonly_fields = ("id", "application", "requested_by", "reason", "requested_at", "resolved_at")
    actions = ["mark_upheld", "mark_overturned"]

    @admin.action(description="Uphold selected decisions (no change to loan)")
    def mark_upheld(self, request, queryset):
        done = 0
        for review in queryset:
            try:
                apply_review_outcome(review, officer=request.user, outcome="upheld", note="Resolved via Django admin")
                done += 1
            except ValueError as exc:
                self.message_user(request, f"{review.id}: {exc}", level=messages.WARNING)
        self.message_user(request, f"{done} review(s) upheld.", level=messages.SUCCESS)

    @admin.action(description="Overturn selected decisions (officer override -> approve)")
    def mark_overturned(self, request, queryset):
        done = 0
        for review in queryset:
            try:
                apply_review_outcome(
                    review, officer=request.user, outcome="overturned", note="Overturned via Django admin"
                )
                done += 1
            except ValueError as exc:
                self.message_user(request, f"{review.id}: {exc}", level=messages.WARNING)
        self.message_user(request, f"{done} decision(s) overturned + approval email queued.", level=messages.SUCCESS)
