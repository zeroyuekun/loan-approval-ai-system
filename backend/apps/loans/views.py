import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache as django_cache
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import CustomerProfile
from apps.accounts.permissions import IsAdmin, IsAdminOrOfficer
from apps.accounts.policy import is_staff_role
from apps.agents.models import AgentRun
from apps.agents.services.api_budget import ApiBudgetGuard
from apps.ml_engine.models import ModelVersion

from .filters import AuditLogFilter, LoanApplicationFilter
from .models import AuditLog, Complaint, DecisionReview, LoanApplication, LoanDecision
from .serializers import (
    AuditLogSerializer,
    ComplaintSerializer,
    CustomerLoanApplicationSerializer,
    DecisionReviewSerializer,
    LoanApplicationCreateSerializer,
    LoanApplicationCustomerUpdateSerializer,
    LoanApplicationSerializer,
)
from .services.decision_review import apply_review_outcome, withdraw_review
from .services.overturn_policy import evaluate_overturn_gate, normalize_overturn_mode
from .tasks import dispatch_pipeline_or_queue_failed

logger = logging.getLogger(__name__)


class IsOwnerOrStaff(permissions.BasePermission):
    """Object-level permission: only the applicant, admins, or officers can modify."""

    def has_object_permission(self, request, view, obj):
        if is_staff_role(request.user):
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
        if is_staff_role(user):
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
            transaction.on_commit(lambda: dispatch_pipeline_or_queue_failed(instance, source="api"))

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
        """Soft delete: the application and its decision evidence (decision,
        bias reports, emails, agent runs) stay for the retention period;
        enforce_retention purges them later. The audit row snapshots what
        the deleted record was."""
        resource_id = str(instance.id)
        decision = LoanDecision.objects.filter(application_id=instance.pk).first()
        with transaction.atomic():
            self._audit_and_delete(instance, resource_id, decision)

    def _audit_and_delete(self, instance, resource_id, decision):
        AuditLog.objects.create(
            user=self.request.user,
            action="loan_deleted",
            resource_type="LoanApplication",
            resource_id=resource_id,
            details={
                "soft_delete": True,
                "status": instance.status,
                "decision_id": str(decision.pk) if decision else None,
                "decision": decision.decision if decision else None,
            },
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

    _CACHE_KEY = "dashboard_stats"
    _CACHE_TTL = 60

    def get(self, request):
        data = django_cache.get(self._CACHE_KEY)
        if data is None:
            if django_cache.add(f"{self._CACHE_KEY}:lock", True, timeout=5):
                data = self._compute_stats()
                django_cache.set(self._CACHE_KEY, data, self._CACHE_TTL)
            else:
                # Another request is computing — return stale or compute inline
                data = django_cache.get(self._CACHE_KEY) or self._compute_stats()
        return Response(data)

    def _compute_stats(self):
        import numpy as np

        now = timezone.now()
        last_24h = now - timedelta(hours=24)

        # Total applications
        total = LoanApplication.objects.count()

        # Approval rate (lifetime) — and raw counts for the donut chart
        decided = LoanApplication.objects.filter(status__in=["approved", "denied"])
        decided_count = decided.count()
        approved_count = decided.filter(status="approved").count()
        denied_count = decided_count - approved_count
        approval_rate = round(approved_count / decided_count * 100, 1) if decided_count > 0 else 0

        # Lifetime average processing time (kept for back-compat with any
        # current callers — new tiles use the 24h window below).
        avg_time = AgentRun.objects.filter(status="completed", total_time_ms__isnull=False).aggregate(
            avg=Avg("total_time_ms")
        )["avg"]
        avg_processing_seconds = round(avg_time / 1000, 1) if avg_time else None

        # 24h rolling decision latency window
        latencies_ms_24h = list(
            AgentRun.objects.filter(
                status="completed",
                total_time_ms__isnull=False,
                created_at__gte=last_24h,
            ).values_list("total_time_ms", flat=True)
        )
        decisions_24h_count = len(latencies_ms_24h)
        if latencies_ms_24h:
            p50_ms_24h, p95_ms_24h = (int(x) for x in np.percentile(latencies_ms_24h, [50, 95]))
        else:
            p50_ms_24h = None
            p95_ms_24h = None

        # LLM spend — safe-defaults if the budget guard cannot reach Redis
        # at all (get_daily_stats already returns zeros on a Redis error, but
        # defend against the rare case where ApiBudgetGuard itself raises
        # during construction).
        try:
            budget_stats = ApiBudgetGuard().get_daily_stats()
            llm_spend_today_usd = float(budget_stats.get("cost_usd", 0.0))
            llm_spend_cap_usd = float(budget_stats.get("budget_limit_usd", 5.0))
        except Exception:
            llm_spend_today_usd = 0.0
            llm_spend_cap_usd = 5.0

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
            .annotate(total=Count("id"), approved=Count("id", filter=Q(status="approved")))
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

        return {
            "total_applications": total,
            "approval_rate": approval_rate,
            "approved_count": approved_count,
            "denied_count": denied_count,
            "avg_processing_seconds": avg_processing_seconds,
            "decision_latency_p50_ms_24h": p50_ms_24h,
            "decision_latency_p95_ms_24h": p95_ms_24h,
            "decisions_24h_count": decisions_24h_count,
            "llm_spend_today_usd": llm_spend_today_usd,
            "llm_spend_cap_usd": llm_spend_cap_usd,
            "active_model": {
                "name": f"{active_model.algorithm} v{active_model.version}",
                "auc": float(active_model.auc_roc) if active_model.auc_roc else None,
            }
            if active_model
            else None,
            "daily_volume": [{"date": str(d["date"]), "count": d["count"]} for d in daily_volume],
            "approval_trend": approval_trend,
            "pipeline": {
                "total": pipeline_total,
                "completed": pipeline_stats["completed"],
                "failed": pipeline_stats["failed"],
                "escalated": pipeline_stats["escalated"],
                "success_rate": round(pipeline_stats["completed"] / pipeline_total * 100, 1)
                if pipeline_total > 0
                else 0,
            },
        }


def _audit_value(value):
    """JSON-safe rendering of a model value for AuditLog details."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class ComplaintFilingThrottle(UserRateThrottle):
    """Tight cap on complaint filing — sensitive + spam vector."""

    scope = "complaint_filing"
    rate = "10/hour"


class ComplaintViewSet(viewsets.ModelViewSet):
    """Complaint management: customers create/view own, staff view/update all."""

    serializer_class = ComplaintSerializer
    permission_classes = [permissions.IsAuthenticated]
    # No DELETE: a complaint is an IDR record (ASIC RG 271) that must be kept.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    # Fields whose before/after values go into the audit row. Free text
    # (subject, description, resolution) is recorded by name only.
    _AUDITED_VALUES = ("status", "category", "loan_application_id", "resolved_at")

    def get_queryset(self):
        user = self.request.user
        if is_staff_role(user):
            return Complaint.objects.all().select_related("complainant", "loan_application")
        return Complaint.objects.filter(complainant=user).select_related("loan_application")

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            return [permissions.IsAuthenticated(), IsAdminOrOfficer()]
        return [permissions.IsAuthenticated()]

    def get_throttles(self):
        if self.action == "create":
            return [ComplaintFilingThrottle()]
        return super().get_throttles()

    def perform_update(self, serializer):
        """Staff edits are audited with every changed field."""
        instance = serializer.instance
        before = {f.attname: getattr(instance, f.attname) for f in instance._meta.concrete_fields}
        with transaction.atomic():
            updated = serializer.save()
            changed = [name for name, old in before.items() if name != "updated_at" and getattr(updated, name) != old]
            details = {"changed_fields": sorted(n.removesuffix("_id") for n in changed)}
            for name in self._AUDITED_VALUES:
                if name in changed:
                    details[name.removesuffix("_id")] = {
                        "from": _audit_value(before[name]),
                        "to": _audit_value(getattr(updated, name)),
                    }
            AuditLog.objects.create(
                user=self.request.user,
                action="complaint_updated",
                resource_type="Complaint",
                resource_id=str(updated.pk),
                details=details,
                ip_address=self.request.META.get("REMOTE_ADDR"),
            )


class DecisionReviewFilingThrottle(UserRateThrottle):
    scope = "decision_review_filing"
    rate = "10/hour"


class DecisionReviewViewSet(viewsets.ModelViewSet):
    """Customers file/view their own decision reviews; staff view all + resolve."""

    serializer_class = DecisionReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        # Reviews of a soft-deleted application go with it.
        qs = DecisionReview.objects.select_related("application", "requested_by").filter(
            application__deleted_at__isnull=True
        )
        if not is_staff_role(user):
            qs = qs.filter(requested_by=user)
        application_id = self.request.query_params.get("application")
        if application_id:
            qs = qs.filter(application_id=application_id)
        return qs

    def get_throttles(self):
        if self.action == "create":
            return [DecisionReviewFilingThrottle()]
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        # Feature flag: filing can be disabled instantly without removing the surface.
        if not getattr(settings, "DECISION_REVIEW_ENABLED", True):
            return Response({"detail": "Decision review requests are not currently available."}, status=503)
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, IsAdminOrOfficer])
    def resolve(self, request, pk=None):
        review = self.get_object()
        outcome = request.data.get("outcome")
        note = request.data.get("note", "")
        if len(note) > 4000:
            return Response({"detail": "note must be 4000 characters or fewer"}, status=400)
        if outcome not in ("upheld", "overturned"):
            return Response({"detail": "outcome must be 'upheld' or 'overturned'"}, status=400)

        # Optional maker/checker gate on high-value overturns. Default mode is
        # "off" — no behaviour change until an operator opts in.
        if outcome == "overturned":
            mode = normalize_overturn_mode(getattr(settings, "DECISION_OVERTURN_GATE_MODE", "off"))
            gate = evaluate_overturn_gate(
                amount=float(review.application.loan_amount or 0),
                threshold=getattr(settings, "DECISION_OVERTURN_THRESHOLD", 100000.0),
                mode=mode,
                officer_has_2fa=request.user.has_confirmed_totp(),
            )
            if not gate["allowed"]:
                return Response({"detail": gate["reason"]}, status=403)

        try:
            updated = apply_review_outcome(review, officer=request.user, outcome=outcome, note=note)
        except (ValueError, LoanApplication.InvalidStateTransition) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(DecisionReviewSerializer(updated, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def withdraw(self, request, pk=None):
        review = self.get_object()
        try:
            updated = withdraw_review(review, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(DecisionReviewSerializer(updated, context={"request": request}).data)


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
            # JSONField contains-any match (postgres @> with a list operand).
            code_q = Q()
            for code in codes:
                code_q |= Q(referral_codes__contains=[code])
            qs = qs.filter(code_q)

        status_filter = request.query_params.get("status")
        if status_filter:
            valid_statuses = LoanApplication.ReferralStatus.values
            if status_filter not in valid_statuses:
                return Response(
                    {"error": f"Invalid status '{status_filter}'. Valid values: {valid_statuses}"},
                    status=400,
                )
            qs = qs.filter(referral_status=status_filter)

        try:
            limit = int(request.query_params.get("limit", 100))
        except (ValueError, TypeError):
            limit = 100
        limit = max(1, min(limit, 500))
        results = []
        for app in qs[:limit]:
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
