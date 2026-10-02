import logging

from django.db import transaction
from django.db.models import OuterRef, Subquery
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrOfficer
from apps.accounts.policy import is_staff_role
from apps.agents.models import AgentRun
from apps.agents.serializers import agent_run_serializer_class
from apps.agents.services.human_review_actions import (
    HUMAN_REVIEW_ACTIONS,
    HumanReviewRejected,
    apply_human_review_action,
)
from apps.agents.tasks import orchestrate_pipeline_task
from apps.common.http import client_ip
from apps.loans.models import AuditLog, LoanApplication
from apps.loans.permissions import check_loan_access

logger = logging.getLogger(__name__)


class OrchestrationThrottle(UserRateThrottle):
    rate = "60/hour"


class AgentRunListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return a paginated list of all agent runs the user can access."""
        user = request.user
        queryset = (
            AgentRun.objects.for_serializer()
            .filter(application__deleted_at__isnull=True)  # hidden with a soft-deleted application
            .order_by("-created_at")
        )

        # Non-staff users can only see runs for their own applications
        if not is_staff_role(user):
            queryset = queryset.filter(application__applicant=user)

        # Optional status filter
        status_filter = request.query_params.get("status")
        if status_filter and status_filter in dict(AgentRun.Status.choices):
            queryset = queryset.filter(status=status_filter)

            # For escalated runs, only show ones with actual bias flags
            # and deduplicate by application_id — keep only the most recent
            # run per application so reviewers see one row each.
            if status_filter == "escalated":
                queryset = queryset.filter(
                    bias_reports__flagged=True,
                )
                latest_per_app = (
                    AgentRun.objects.filter(
                        status=AgentRun.Status.ESCALATED,
                        bias_reports__flagged=True,
                        application_id=OuterRef("application_id"),
                    )
                    .order_by("-created_at")
                    .values("id")[:1]
                )
                queryset = queryset.filter(id=Subquery(latest_per_app)).distinct()

        # Simple pagination (clamped to max 100)
        try:
            page = int(request.query_params.get("page", 1))
        except (ValueError, TypeError):
            page = 1
        try:
            page_size = min(int(request.query_params.get("page_size", 20)), 100)
        except (ValueError, TypeError):
            page_size = 20
        total = queryset.count()
        offset = (page - 1) * page_size
        runs = queryset[offset : offset + page_size]

        # List endpoint drops marketing html_body to avoid re-rendering the
        # large regex HTML renderer per row in this paginated hot path.
        serializer_class = agent_run_serializer_class(user)
        results = serializer_class(runs, many=True, context={"include_html": False}).data

        # Build next/previous URLs preserving all filter params
        base_url = request.build_absolute_uri(request.path)
        extra_params = "".join(f"&{k}={v}" for k, v in request.query_params.items() if k not in ("page", "page_size"))
        next_url = (
            f"{base_url}?page={page + 1}&page_size={page_size}{extra_params}" if offset + page_size < total else None
        )
        prev_url = f"{base_url}?page={page - 1}&page_size={page_size}{extra_params}" if page > 1 else None

        return Response(
            {
                "count": total,
                "next": next_url,
                "previous": prev_url,
                "results": results,
            }
        )


_CUSTOMER_DISPATCHABLE = (LoanApplication.Status.PENDING, LoanApplication.Status.QUEUE_FAILED)


class OrchestrateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OrchestrationThrottle]

    def post(self, request, loan_id):
        """Trigger pipeline orchestration for a loan application.

        Non-force path (default): idempotent. If the latest AgentRun completed,
        return it without dispatching. Otherwise dispatch a new run.

        Force path: staff-only, requires `reason` query/body param, writes an
        AuditLog entry before dispatching.
        """
        application = check_loan_access(request, loan_id)

        force = request.query_params.get("force", "").lower() == "true"
        reason = (
            request.query_params.get("reason")
            or (request.data.get("reason") if isinstance(request.data, dict) else None)
            or ""
        ).strip()

        if force:
            if not is_staff_role(request.user):
                return Response(
                    {"detail": "force rerun requires staff role"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not reason:
                return Response(
                    {"detail": "reason is required for force rerun"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            existing = AgentRun.objects.latest_for(loan_id)
            if existing is not None and existing.status == AgentRun.Status.COMPLETED:
                return Response(
                    {
                        "status": "already_completed",
                        "existing_run_id": str(existing.id),
                    },
                    status=status.HTTP_200_OK,
                )
            # A customer may only start the pipeline for an application that
            # is waiting for it. Anything else (under review, being processed,
            # decided after a failed run) would replace a decision or fail an
            # escalated review run: that is a staff action.
            if not is_staff_role(request.user) and application.status not in _CUSTOMER_DISPATCHABLE:
                return Response(
                    {"detail": f"The application cannot be processed in its current status ({application.status})"},
                    status=status.HTTP_409_CONFLICT,
                )

        task = orchestrate_pipeline_task.delay(str(loan_id), force=force)

        audit_action = "pipeline_force_rerun" if force else "pipeline_triggered"
        audit_details = {"task_id": task.id}
        if force:
            audit_details["reason"] = reason

        AuditLog.objects.create(
            user=request.user,
            action=audit_action,
            resource_type="LoanApplication",
            resource_id=str(loan_id),
            details=audit_details,
            ip_address=client_ip(request),
        )

        return Response(
            {"task_id": task.id, "status": "pipeline_queued"},
            status=status.HTTP_202_ACCEPTED,
        )


BATCH_ORCHESTRATE_MAX = 100  # Safety cap for POST /agents/orchestrate-all/


class BatchOrchestrateView(APIView):
    """Trigger the AI pipeline for all pending applications in one go."""

    permission_classes = [IsAdminOrOfficer]
    throttle_classes = [OrchestrationThrottle]

    def post(self, request):
        recheck = request.query_params.get("recheck", "").lower() == "true"

        if recheck:
            # Re-run applications waiting in the review queue: REVIEW with an
            # ESCALATED latest run. A REVIEW application whose run a reviewer has
            # claimed (RUNNING) is being resumed and is left alone.
            # Stuck-PROCESSING recovery is out of scope here; that belongs in a
            # dedicated dead-letter / recovery task.
            reviewable_qs = (
                LoanApplication.objects.filter(status=LoanApplication.Status.REVIEW)
                .annotate(latest_run_status=AgentRun.objects.latest_status_subquery())
                .filter(latest_run_status=AgentRun.Status.ESCALATED)
                .order_by("created_at")
            )
            total_eligible = reviewable_qs.count()
            pending_ids = []
            for app_id in reviewable_qs.values_list("id", flat=True)[:BATCH_ORCHESTRATE_MAX]:
                # Same lock order as the review action (run, then application),
                # and re-checked under the locks: a reviewer may have claimed
                # the run since the query above.
                with transaction.atomic():
                    run = AgentRun.objects.select_for_update().latest_for(app_id)
                    app = (
                        LoanApplication.objects.select_for_update()
                        .filter(pk=app_id, status=LoanApplication.Status.REVIEW)
                        .first()
                    )
                    if run is None or run.status != AgentRun.Status.ESCALATED or app is None:
                        continue
                    try:
                        app.transition_to(
                            "pending",
                            user=request.user,
                            details={"reason": "batch_recheck"},
                        )
                    except LoanApplication.InvalidStateTransition:
                        continue
                pending_ids.append(app_id)
        else:
            pending_qs = LoanApplication.objects.filter(status=LoanApplication.Status.PENDING).order_by("created_at")
            total_eligible = pending_qs.count()
            pending_ids = list(pending_qs.values_list("id", flat=True)[:BATCH_ORCHESTRATE_MAX])

        if not pending_ids:
            return Response(
                {"detail": "No pending applications to process.", "queued": 0},
                status=status.HTTP_200_OK,
            )

        skipped = max(0, total_eligible - len(pending_ids))

        tasks = []
        for app_id in pending_ids:
            task = orchestrate_pipeline_task.delay(str(app_id), force=recheck)
            tasks.append({"application_id": str(app_id), "task_id": task.id})

        AuditLog.objects.create(
            user=request.user,
            action="batch_pipeline_triggered",
            resource_type="LoanApplication",
            resource_id="batch",
            details={
                "count": len(tasks),
                "skipped_count": skipped,
                "application_ids": [t["application_id"] for t in tasks],
            },
            ip_address=client_ip(request),
        )

        body = {"queued": len(tasks), "tasks": tasks}
        if skipped:
            body["skipped"] = skipped
            body["detail"] = f"{skipped} more pending; call again to continue"

        return Response(body, status=status.HTTP_202_ACCEPTED)


class AgentRunView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, loan_id):
        """Return the latest AgentRun with all related data for a loan application."""
        check_loan_access(request, loan_id)

        agent_run = AgentRun.objects.for_serializer().latest_for(loan_id)

        if not agent_run:
            return Response(
                {"error": "No agent run found for this application"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Detail endpoint includes the rendered marketing html_body.
        serializer_class = agent_run_serializer_class(request.user)
        return Response(serializer_class(agent_run, context={"include_html": True}).data)


class HumanReviewView(APIView):
    """Lets loan officers approve, deny, or regenerate escalated pipeline runs.

    The state machine lives in apps.agents.services.human_review_actions; the
    throttle prevents task queue flooding.
    """

    permission_classes = [IsAdminOrOfficer]
    throttle_classes = [OrchestrationThrottle]

    def post(self, request, run_id):
        action = request.data.get("action")
        if action not in HUMAN_REVIEW_ACTIONS:
            return Response(
                {"error": "action must be one of: approve, deny, regenerate"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payload = apply_human_review_action(
                run_id,
                action=action,
                user=request.user,
                note=request.data.get("note", ""),
                ip_address=client_ip(request),
            )
        except HumanReviewRejected as exc:
            return Response({"error": str(exc)}, status=exc.status_code)
        return Response(payload)
