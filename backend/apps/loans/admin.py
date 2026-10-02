"""Django admin for loans.

The admin is a staff write path beside the API, so it must not bypass what
the API enforces: status changes go through the state machine (status is
read-only here), decision records are view-only, decision inputs freeze
once an application is assessed, review outcomes go through
apply_review_outcome (four-eyes and the overturn gate), and every change
writes an AuditLog row into the hash chain, not only a Django LogEntry.
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import AuditLog, Complaint, DecisionReview, LoanApplication, LoanDecision, PipelineDispatchOutbox
from .services.audit_diff import field_change_details, snapshot
from .services.decision_review import apply_review_outcome
from .tasks import dispatch_pipeline_or_queue_failed


def _audit_admin_change(request, action, instance, before, **kwargs):
    details = field_change_details(before, instance, **kwargs)
    details["source"] = "django_admin"
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=type(instance).__name__,
        resource_id=str(instance.pk),
        details=details,
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _audit_admin_delete(request, instance):
    AuditLog.objects.create(
        user=request.user,
        action="loan_deleted",
        resource_type=type(instance).__name__,
        resource_id=str(instance.pk),
        details={"source": "django_admin", "status": instance.status},
        ip_address=request.META.get("REMOTE_ADDR"),
    )


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
    readonly_fields = ("id", "created_at", "updated_at", "status")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.decision_inputs_frozen():
            fields += list(LoanApplication.DECISION_INPUT_FIELDS)
        return fields

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

        if change:
            before = snapshot(LoanApplication.all_objects.all_with_deleted().get(pk=obj.pk))
            with transaction.atomic():
                super().save_model(request, obj, form, change)
                _audit_admin_change(request, "loan_updated", obj, before, names_only=("notes", "conditions"))
            return

        super().save_model(request, obj, form, change)

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

    def delete_model(self, request, obj):
        # delete() soft-deletes; record it in the hash chain like every other
        # admin write, not only in Django's LogEntry.
        with transaction.atomic():
            super().delete_model(request, obj)
            _audit_admin_delete(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            deleted = list(queryset)
            super().delete_queryset(request, queryset)
            for obj in deleted:
                _audit_admin_delete(request, obj)


@admin.register(LoanDecision)
class LoanDecisionAdmin(admin.ModelAdmin):
    """View-only: a decision changes only through the pipeline, human review
    or a decision review, each of which audits it."""

    list_display = ("id", "application", "decision", "confidence", "model_version", "created_at")
    list_filter = ("decision",)
    search_fields = ("application__applicant__username",)
    readonly_fields = ("id", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("id", "complainant", "category", "status", "sla_deadline", "created_at")
    list_filter = ("status", "category")
    search_fields = ("complainant__username", "subject", "description")
    readonly_fields = ("id", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False  # an IDR record (RG 271); the API has no delete either

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        before = snapshot(Complaint.objects.get(pk=obj.pk))
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            _audit_admin_change(
                request,
                "complaint_updated",
                obj,
                before,
                values_for=("status", "category", "loan_application_id", "resolved_at"),
            )


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
    # Outcome fields change only through the actions below, which go through
    # apply_review_outcome (four-eyes, overturn gate, decision + audit).
    readonly_fields = (
        "id",
        "application",
        "requested_by",
        "reason",
        "requested_at",
        "resolved_at",
        "status",
        "outcome_decision",
        "assigned_officer",
        "resolution_note",
    )
    actions = ["mark_upheld", "mark_overturned"]

    def has_delete_permission(self, request, obj=None):
        return False  # a contestability record; resolved through the actions below, never deleted

    @admin.action(description="Uphold selected decisions (no change to loan)")
    def mark_upheld(self, request, queryset):
        done = 0
        for review in queryset:
            try:
                apply_review_outcome(review, officer=request.user, outcome="upheld", note="Resolved via Django admin")
                done += 1
            except (ValueError, PermissionDenied) as exc:
                # PermissionDenied: four-eyes or the overturn gate refused this
                # one; report it and carry on with the rest of the batch.
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
            except (ValueError, PermissionDenied) as exc:
                # PermissionDenied: four-eyes or the overturn gate refused this
                # one; report it and carry on with the rest of the batch.
                self.message_user(request, f"{review.id}: {exc}", level=messages.WARNING)
        self.message_user(request, f"{done} decision(s) overturned + approval email queued.", level=messages.SUCCESS)
