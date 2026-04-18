import logging

from django.core.cache import cache as django_cache
from django.db import models, transaction
from rest_framework import permissions, viewsets
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import CustomerProfile
from apps.accounts.permissions import IsAdmin, IsAdminOrOfficer

from .filters import AuditLogFilter, LoanApplicationFilter
from .models import AuditLog, Complaint, LoanApplication
from .serializers import (
    AuditLogSerializer,
    ComplaintSerializer,
    CustomerLoanApplicationSerializer,
    LoanApplicationCreateSerializer,
    LoanApplicationCustomerUpdateSerializer,
    LoanApplicationSerializer,
)

logger = logging.getLogger(__name__)


class IsOwnerOrStaff(permissions.BasePermission):
    """Object-level permission: only the applicant, admins, or officers can modify."""

    def has_object_permission(self, request, view, obj):
        if request.user.role in ("admin", "officer"):
            return True
        return obj.applicant_id == request.user.id


class LoanApplicationViewSet(viewsets.ModelViewSet):
    filterset_class = LoanApplicationFilter
    ordering_fields = ["created_at", "loan_amount", "credit_score", "status"]
    search_fields = [
        "applicant__first_name",
        "applicant__last_name",
        "applicant__email",
        "applicant__username",
        "notes",
        "purpose",
    ]

    def get_serializer_class(self):
        if self.action == "create":
            return LoanApplicationCreateSerializer
        if self.action in ("update", "partial_update") and self.request.user.role == "customer":
            return LoanApplicationCustomerUpdateSerializer
        if self.action in ("retrieve", "list") and self.request.user.role == "customer":
            return CustomerLoanApplicationSerializer
        return LoanApplicationSerializer

    def get_queryset(self):
        user = self.request.user
        qs = LoanApplication.objects.select_related("applicant", "decision").prefetch_related("fraud_checks")
        if user.role in ("admin", "officer"):
            return qs.all()
        return qs.filter(applicant=user)

    def get_permissions(self):
        if self.action == "destroy":
            return [permissions.IsAuthenticated(), IsAdmin()]
        if self.action in ("update", "partial_update"):
            return [permissions.IsAuthenticated(), IsOwnerOrStaff()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        user = self.request.user
        with transaction.atomic():
            instance = serializer.save(applicant=user)
            # Ensure customer has a profile and seed it from the application
            if user.role == "customer":
                profile, created = CustomerProfile.objects.get_or_create(user=user)
                if created or profile.num_products <= 1:
                    # Seed profile banking fields from the loan application data
                    profile.has_mortgage = instance.home_ownership == "mortgage"
                    profile.has_credit_card = (instance.existing_credit_card_limit or 0) > 0
                    profile.num_products = max(
                        profile.num_products,
                        1 + int(profile.has_credit_card) + int(profile.has_mortgage),
                    )
                    profile.save(
                        update_fields=[
                            "has_mortgage",
                            "has_credit_card",
                            "num_products",
                        ]
                    )
            AuditLog.objects.create(
                user=user,
                action="loan_created",
                resource_type="LoanApplication",
                resource_id=str(instance.id),
                details={"loan_amount": str(instance.loan_amount), "purpose": instance.purpose},
                ip_address=self.request.META.get("REMOTE_ADDR"),
            )

            # Durable dispatch: on_commit so the row is visible to the worker,
            # and an outbox fallback so a broker outage never swallows a submission.
            from apps.agents.tasks import orchestrate_pipeline_task
            from apps.loans.models import PipelineDispatchOutbox

            def _dispatch():
                try:
                    orchestrate_pipeline_task.delay(str(instance.pk))
                    logger.info("Auto-triggered pipeline for application %s", instance.pk)
                except Exception as exc:
                    logger.error(
                        "Failed to auto-trigger pipeline for %s: %s — queued to outbox",
                        instance.pk,
                        exc,
                    )
                    PipelineDispatchOutbox.objects.get_or_create(
                        application=instance,
                        defaults={"last_error": str(exc)[:1000]},
                    )
                    LoanApplication.objects.filter(pk=instance.pk).update(status=LoanApplication.Status.QUEUE_FAILED)

            transaction.on_commit(_dispatch)

    def perform_update(self, serializer):
        instance = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action="loan_updated",
            resource_type="LoanApplication",
            resource_id=str(instance.id),
            details={"status": instance.status},
            ip_address=self.request.META.get("REMOTE_ADDR"),
        )

    def perform_destroy(self, instance):
        resource_id = str(instance.id)
        AuditLog.objects.create(
            user=self.request.user,
            action="loan_deleted",
            resource_type="LoanApplication",
            resource_id=resource_id,
            details={},
            ip_address=self.request.META.get("REMOTE_ADDR"),
        )
        super().perform_destroy(instance)


class AuditLogViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filterset_class = AuditLogFilter
    search_fields = ["resource_id", "user__username", "action"]
    ordering_fields = ["timestamp", "action"]
    ordering = ["-timestamp"]

    def get_queryset(self):
        return AuditLog.objects.all().select_related("user")


class DashboardStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrOfficer]

    def get(self, request):
        data = django_cache.get("dashboard_stats")
        if data is None:
            data = self._compute_stats()
            django_cache.set("dashboard_stats", data, 30)
        return Response(data)

    def _compute_stats(self):
        from datetime import timedelta

        from django.db.models import Avg, Count, Q
        from django.db.models.functions import TruncDate
        from django.utils import timezone

        from apps.agents.models import AgentRun
        from apps.ml_engine.models import ModelVersion

        now = timezone.now()

        # Total applications
        total = LoanApplication.objects.count()

        # Approval rate
        decided = LoanApplication.objects.filter(status__in=["approved", "denied"])
        decided_count = decided.count()
        approved = decided.filter(status="approved").count()
        approval_rate = round(approved / decided_count * 100, 1) if decided_count > 0 else 0

        # Average processing time from AgentRun
        avg_time = AgentRun.objects.filter(status="completed", total_time_ms__isnull=False).aggregate(
            avg=Avg("total_time_ms")
        )["avg"]
        avg_processing_seconds = round(avg_time / 1000, 1) if avg_time else None

        # Active model
        active_model = ModelVersion.objects.filter(is_active=True).first()

        # Daily application volume (last 30 days)
        thirty_days_ago = now - timedelta(days=30)
        daily_volume = list(
            LoanApplication.objects.filter(created_at__gte=thirty_days_ago)
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(count=Count("id"))
            .order_by("date")
        )

        # Daily approval rate (last 30 days)
        daily_approvals = list(
            LoanApplication.objects.filter(created_at__gte=thirty_days_ago, status__in=["approved", "denied"])
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total=Count("id"), approved=Count("id", filter=models.Q(status="approved")))
            .order_by("date")
        )
        approval_trend = [
            {"date": str(d["date"]), "rate": round(d["approved"] / d["total"] * 100, 1) if d["total"] > 0 else 0}
            for d in daily_approvals
        ]

        # Pipeline stats (single query instead of 4)
        pipeline_stats = AgentRun.objects.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            failed=Count("id", filter=Q(status="failed")),
            escalated=Count("id", filter=Q(status="escalated")),
        )
        pipeline_total = pipeline_stats["total"]
        pipeline_completed = pipeline_stats["completed"]
        pipeline_failed = pipeline_stats["failed"]
        pipeline_escalated = pipeline_stats["escalated"]

        return {
            "total_applications": total,
            "approval_rate": approval_rate,
            "avg_processing_seconds": avg_processing_seconds,
            "active_model": {
                "name": f"{active_model.algorithm} v{active_model.version}" if active_model else None,
                "auc": float(active_model.auc_roc) if active_model and active_model.auc_roc else None,
            }
            if active_model
            else None,
            "daily_volume": [{"date": str(d["date"]), "count": d["count"]} for d in daily_volume],
            "approval_trend": approval_trend,
            "pipeline": {
                "total": pipeline_total,
                "completed": pipeline_completed,
                "failed": pipeline_failed,
                "escalated": pipeline_escalated,
                "success_rate": round(pipeline_completed / pipeline_total * 100, 1) if pipeline_total > 0 else 0,
            },
        }


class ComplaintFilingThrottle(UserRateThrottle):
    """Tight cap on complaint filing — sensitive + spam vector."""

    scope = "complaint_filing"
    rate = "10/hour"


class ComplaintViewSet(viewsets.ModelViewSet):
    """Complaint management: customers create/view own, staff view/update all."""

    serializer_class = ComplaintSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ("admin", "officer"):
            return Complaint.objects.all().select_related("complainant", "loan_application")
        return Complaint.objects.filter(complainant=user).select_related("loan_application")

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsAdminOrOfficer()]
        return [permissions.IsAuthenticated()]

    def get_throttles(self):
        if self.action == "create":
            return [ComplaintFilingThrottle()]
        return super().get_throttles()


class ReferralListView(APIView):
    """Admin-only list of LoanApplications in a non-NONE referral state.

    Orthogonal to the bias review queue (which remains
    `bias_reports__flagged=True`). Filterable by policy code via
    `?code=P09` (ORs across comma-separated values). Designed as a
    read-only audit surface for future ops tooling — Arm A intentionally
    ships no customer-facing UI against this endpoint.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = (
            LoanApplication.objects.exclude(
                referral_status=LoanApplication.ReferralStatus.NONE,
            )
            .select_related("applicant")
            .order_by("-updated_at")
        )

        code_filter = request.query_params.get("code")
        if code_filter:
            codes = [c.strip() for c in code_filter.split(",") if c.strip()]
            # JSONField contains-any match — postgres supports @> with a list
            # operand. Fall back to a Python filter if the DB dialect can't
            # translate (sqlite in tests).
            try:
                code_q = models.Q()
                for code in codes:
                    code_q |= models.Q(referral_codes__contains=[code])
                qs = qs.filter(code_q)
            except Exception:
                applications = [a for a in qs if any(c in (a.referral_codes or []) for c in codes)]
                qs = applications  # fallback: Python-level filter

        status_filter = request.query_params.get("status")
        if status_filter and hasattr(qs, "filter"):
            qs = qs.filter(referral_status=status_filter)

        limit = min(int(request.query_params.get("limit", 100)), 500)
        results = []
        for app in list(qs)[:limit]:
            results.append(
                {
                    "application_id": str(app.id),
                    "applicant_id": str(app.applicant_id),
                    "purpose": app.purpose,
                    "loan_amount": float(app.loan_amount) if app.loan_amount is not None else None,
                    "referral_status": app.referral_status,
                    "referral_codes": app.referral_codes or [],
                    "referral_rationale": app.referral_rationale or {},
                    "status": app.status,
                    "updated_at": app.updated_at.isoformat() if app.updated_at else None,
                }
            )
        return Response({"count": len(results), "results": results})
