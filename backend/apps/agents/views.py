import logging

from django.db import transaction
from django.db.models import OuterRef, Prefetch, Subquery
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrOfficer
from apps.accounts.policy import is_staff_role
from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
from apps.agents.serializers import agent_run_serializer_class
from apps.agents.tasks import orchestrate_pipeline_task, resume_pipeline_task
from apps.loans.models import AuditLog, LoanApplication, LoanDecision
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
            AgentRun.objects.select_related("application__applicant")
            .prefetch_related(
                Prefetch("bias_reports", queryset=BiasReport.objects.order_by("-created_at")),
                Prefetch("next_best_offers", queryset=NextBestOffer.objects.order_by("-created_at")),
                Prefetch("marketing_emails", queryset=MarketingEmail.objects.order_by("-created_at")),
            )
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
            # Only the latest run counts, as in the task: an older completed
            # run says nothing once a later run has failed.
            existing = AgentRun.objects.filter(application_id=loan_id).order_by("-created_at").first()
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
            ip_address=request.META.get("REMOTE_ADDR"),
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
            latest_run_status = Subquery(
                AgentRun.objects.filter(application_id=OuterRef("pk")).order_by("-created_at").values("status")[:1]
            )
            reviewable_qs = (
                LoanApplication.objects.filter(status=LoanApplication.Status.REVIEW)
                .annotate(latest_run_status=latest_run_status)
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
                    run = (
                        AgentRun.objects.select_for_update()
                        .filter(application_id=app_id)
                        .order_by("-created_at")
                        .first()
                    )
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
            ip_address=request.META.get("REMOTE_ADDR"),
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

        # Always the latest run: its status, steps and artefacts describe the
        # application's current state. (An older run with marketing emails
        # used to be swapped in, showing a superseded run as current.)
        agent_run = (
            AgentRun.objects.filter(application_id=loan_id)
            .select_related("application__applicant")
            .prefetch_related(
                # Newest first, as in the run list: a run can hold several
                # reports (a replacement, an Agent 2 rewrite, a later reissue).
                Prefetch("bias_reports", queryset=BiasReport.objects.order_by("-created_at")),
                "next_best_offers",
                "marketing_emails",
            )
            .order_by("-created_at")
            .first()
        )

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

    Concurrency and consistency guarantees:
    - select_for_update() to prevent race conditions between concurrent reviewers
    - Audit log inside transaction to prevent ghost entries on DB failure
    - LoanDecision updated on human deny to maintain consistency
    - Task dispatched via on_commit() to ensure DB state is committed first
    - update_fields on save() to prevent lost-update on concurrent writes
    - Throttle to prevent task queue flooding
    """

    permission_classes = [IsAdminOrOfficer]
    throttle_classes = [OrchestrationThrottle]

    def post(self, request, run_id):
        action = request.data.get("action")
        if action not in ("approve", "deny", "regenerate"):
            return Response(
                {"error": "action must be one of: approve, deny, regenerate"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reviewer_note = request.data.get("note", "")

        # Acquire row lock to prevent two reviewers acting on the same run
        with transaction.atomic():
            try:
                agent_run = AgentRun.objects.select_for_update().get(pk=run_id)
            except AgentRun.DoesNotExist:
                return Response(
                    {"error": "Agent run not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if agent_run.status != AgentRun.Status.ESCALATED:
                return Response(
                    {"error": f"Agent run is not escalated (current status: {agent_run.status})"},
                    status=status.HTTP_409_CONFLICT,
                )

            # Staff can also be borrowers; nobody reviews their own application.
            if agent_run.application.applicant_id == request.user.pk:
                return Response(
                    {"error": "You cannot review a run for your own application."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # A run left escalated by an older pipeline must not act on an
            # application a later run has already decided.
            application_status = (
                LoanApplication.objects.select_for_update()
                .values_list("status", flat=True)
                .get(pk=agent_run.application_id)
            )
            if application_status != LoanApplication.Status.REVIEW:
                return Response(
                    {"error": f"Application is no longer in review (current status: {application_status})"},
                    status=status.HTTP_409_CONFLICT,
                )

            review_step = {
                "step_name": "human_review_decision",
                "status": "completed",
                "result_summary": {
                    "action": action,
                    "reviewer": request.user.username,
                    "note": reviewer_note,
                },
            }

            if action == "approve":
                # Claim the run under the lock: it leaves the queue, and a second
                # action on it gets the 409 above instead of racing this one.
                agent_run.steps = agent_run.steps + [review_step]
                agent_run.status = AgentRun.Status.RUNNING
                agent_run.save(update_fields=["steps", "status", "updated_at"])

                # Audit log inside the transaction
                AuditLog.objects.create(
                    user=request.user,
                    action="human_review_approve",
                    resource_type="AgentRun",
                    resource_id=str(run_id),
                    details={"note": reviewer_note},
                    ip_address=request.META.get("REMOTE_ADDR"),
                )

                # Dispatch task after commit so it sees the updated state
                task_holder = {}

                def _dispatch_resume():
                    task_holder["task"] = resume_pipeline_task.delay(
                        str(run_id),
                        reviewer=request.user.username,
                        note=reviewer_note,
                    )

                transaction.on_commit(_dispatch_resume)

            elif action == "deny":
                application = agent_run.application
                decision = LoanDecision.objects.select_for_update().filter(application=application).first()
                if decision is None:
                    # Nothing on record to announce: deny directly (no notice
                    # can be generated without a LoanDecision).
                    logger.info(
                        "human_review_deny_no_decision_record",
                        extra={
                            "agent_run_id": str(run_id),
                            "application_id": str(application.id),
                            "reviewer": request.user.username,
                        },
                    )
                    application.transition_to("denied", user=request.user, details={"reason": "human_review_deny"})
                    agent_run.steps = agent_run.steps + [review_step]
                    agent_run.status = AgentRun.Status.COMPLETED
                    agent_run.total_time_ms = agent_run.total_time_ms or 0
                    agent_run.save(update_fields=["steps", "status", "total_time_ms", "updated_at"])
                    AuditLog.objects.create(
                        user=request.user,
                        action="human_review_deny",
                        resource_type="AgentRun",
                        resource_id=str(run_id),
                        details={"note": reviewer_note, "application_id": str(application.id)},
                        ip_address=request.META.get("REMOTE_ADDR"),
                    )
                    return Response({"status": "application_denied_by_reviewer", "action": "deny"})

                # Record the reviewer's denial on the decision, then resume the
                # run exactly as an approval does: the resume generates the
                # denial email, runs the bias pre-screen/check on it, delivers
                # it once, and only then moves the application to denied. A
                # flagged denial email is withheld and the run re-escalates.
                original_decision = decision.decision
                decision.decision = "denied"
                decision.reasoning = f"Human review override by {request.user.username}: {reviewer_note}"
                update_fields = ["decision", "reasoning"]
                if original_decision != "denied":
                    decision.human_involvement = LoanDecision.HumanInvolvement.OVERRIDDEN
                    update_fields.append("human_involvement")
                decision.save(update_fields=update_fields)

                agent_run.steps = agent_run.steps + [review_step]
                agent_run.status = AgentRun.Status.RUNNING  # claimed, as for approve
                agent_run.save(update_fields=["steps", "status", "updated_at"])

                AuditLog.objects.create(
                    user=request.user,
                    action="human_review_deny",
                    resource_type="AgentRun",
                    resource_id=str(run_id),
                    details={
                        "note": reviewer_note,
                        "application_id": str(application.id),
                        "original_decision": original_decision,
                    },
                    ip_address=request.META.get("REMOTE_ADDR"),
                )

                task_holder = {}

                def _dispatch_deny():
                    task_holder["task"] = resume_pipeline_task.delay(
                        str(run_id),
                        reviewer=request.user.username,
                        note=reviewer_note,
                        action="deny",
                    )

                transaction.on_commit(_dispatch_deny)

            else:  # regenerate
                # Close the old run as superseded, NOT completed: a COMPLETED run
                # "owns" the application, so the orchestrate task's idempotency
                # guard would replay the stored decision instead of running, and
                # stuck-processing cleanup would skip the app if the new run died.
                agent_run.steps = agent_run.steps + [review_step]
                agent_run.status = AgentRun.Status.FAILED
                agent_run.error = f"Superseded by human-review regenerate ({request.user.username})"
                agent_run.total_time_ms = agent_run.total_time_ms or 0
                agent_run.save(update_fields=["steps", "status", "error", "total_time_ms", "updated_at"])

                # Reset application to pending so the new pipeline can process it
                application = agent_run.application
                application.transition_to("pending", user=request.user, details={"reason": "human_review_regenerate"})

                AuditLog.objects.create(
                    user=request.user,
                    action="human_review_regenerate",
                    resource_type="AgentRun",
                    resource_id=str(run_id),
                    details={"note": reviewer_note, "application_id": str(agent_run.application_id)},
                    ip_address=request.META.get("REMOTE_ADDR"),
                )

                # Dispatch new pipeline AFTER commit
                task_holder = {}

                def _dispatch_regenerate():
                    # force=True: an earlier COMPLETED run for this application
                    # must not short-circuit the reviewer's regenerate request.
                    task_holder["task"] = orchestrate_pipeline_task.delay(str(agent_run.application_id), force=True)

                transaction.on_commit(_dispatch_regenerate)

        # For approve/regenerate, return task info after transaction commits
        task = task_holder.get("task")
        status_by_action = {
            "approve": "review_approved_pipeline_resuming",
            "deny": "review_denied_pipeline_resuming",
            "regenerate": "regeneration_queued",
        }
        return Response(
            {
                "task_id": getattr(task, "id", None),
                "status": status_by_action[action],
                "action": action,
            }
        )
