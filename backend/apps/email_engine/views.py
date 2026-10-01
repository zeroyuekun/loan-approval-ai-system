from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrOfficer
from apps.accounts.policy import is_staff_role
from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.decision_email import (
    DecisionMismatch,
    bias_hold_reason,
    deliver_decision_email,
    email_type_for,
    require_decision_on_record,
)
from apps.email_engine.services.html_renderer import render_html
from apps.email_engine.tasks import generate_email_task
from apps.loans.permissions import check_loan_access


class EmailGenerationThrottle(UserRateThrottle):
    rate = "10/hour"


def _is_staff(user):
    return is_staff_role(user)


def _visible_emails(user, queryset):
    """Customers see only emails that were actually issued to them.

    A row with ``sent_at`` unset is a draft: withheld by the guardrails, held by
    the bias check, or not yet delivered. Its body may carry exactly the content
    the withhold exists to stop (a hallucinated rate, prohibited wording).
    """
    if _is_staff(user):
        return queryset
    return queryset.filter(application__applicant=user, sent_at__isnull=False)


def _serialize_email(email, *, include_body, staff=True):
    """Shared response shape for the email list and detail endpoints.

    ``body``/``html_body`` are KB-scale per record, so the list endpoint omits
    them; clients fetch them from the single-email endpoint (/emails/<loan_id>/).
    Per-check guardrail details are internal compliance artefacts: customers get
    an empty ``guardrail_checks`` list (same key, so the response shape holds).
    """
    applicant = email.application.applicant
    data = {
        "id": str(email.id),
        "application_id": str(email.application_id),
        "applicant_id": applicant.id,
        "applicant_name": f"{applicant.first_name} {applicant.last_name}".strip() or applicant.username,
        "decision": email.decision,
        "subject": email.subject,
    }
    if include_body:
        data["body"] = email.body
        data["html_body"] = render_html(email.body, email_type=email_type_for(email.decision))
    data.update(
        {
            "model_used": email.model_used,
            "generation_time_ms": email.generation_time_ms,
            "attempt_number": email.attempt_number,
            "passed_guardrails": email.passed_guardrails,
            "guardrail_checks": [
                {
                    "check_name": log.check_name,
                    "passed": log.passed,
                    "details": log.details,
                    "category": log.category,
                    # quality_score is a batch-computed value (not stored per-log).
                    # Exposed as null here; callers should use the email-level score.
                    "quality_score": None,
                }
                for log in email.guardrail_checks.all()
            ]
            if staff
            else [],
            "created_at": email.created_at.isoformat(),
        }
    )
    return data


class EmailListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return a paginated list of all generated emails the user can access."""
        user = request.user
        queryset = (
            GeneratedEmail.objects.select_related("application", "application__applicant")
            .prefetch_related("guardrail_checks")
            .order_by("-created_at")
        )

        queryset = _visible_emails(user, queryset)

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
        emails = queryset[offset : offset + page_size]

        staff = _is_staff(user)
        results = [_serialize_email(email, include_body=False, staff=staff) for email in emails]

        base_url = request.build_absolute_uri(request.path)
        next_url = f"{base_url}?page={page + 1}&page_size={page_size}" if offset + page_size < total else None
        prev_url = f"{base_url}?page={page - 1}&page_size={page_size}" if page > 1 else None

        return Response(
            {
                "count": total,
                "next": next_url,
                "previous": prev_url,
                "results": results,
            }
        )


class GenerateEmailView(APIView):
    # Staff only: a decision email is a credit representation from the lender,
    # so the applicant must never be able to trigger one.
    permission_classes = [IsAdminOrOfficer]
    throttle_classes = [EmailGenerationThrottle]

    def post(self, request, loan_id):
        """Trigger generation of the decision email for the decision on record.

        ``decision`` in the body is optional; when present it must match the
        application's LoanDecision (409 otherwise), so a stale screen cannot
        issue the wrong letter.
        """
        check_loan_access(request, loan_id)

        requested = request.data.get("decision") if isinstance(request.data, dict) else None
        if requested is not None and requested not in ("approved", "denied"):
            return Response(
                {"error": "decision must be 'approved' or 'denied'"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            decision = require_decision_on_record(loan_id, requested)
        except DecisionMismatch as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)

        # Refuse rather than regenerate: a regenerated email here would skip
        # the bias check, so it would release a decision the reviewer has not
        # cleared. The latest draft for this decision is what the task would
        # otherwise re-deliver.
        latest = (
            GeneratedEmail.objects.filter(application_id=loan_id, decision=decision).order_by("-created_at").first()
        )
        hold = bias_hold_reason(loan_id, latest)
        if hold:
            return Response({"error": hold}, status=status.HTTP_409_CONFLICT)

        task = generate_email_task.delay(str(loan_id), decision)
        return Response(
            {"task_id": task.id, "status": "email_generation_queued"},
            status=status.HTTP_202_ACCEPTED,
        )


class SendLatestEmailView(APIView):
    permission_classes = [IsAdminOrOfficer]
    throttle_classes = [EmailGenerationThrottle]

    def post(self, request, loan_id):
        """Send the latest generated email for an application to the customer."""
        check_loan_access(request, loan_id)

        email = (
            GeneratedEmail.objects.filter(application_id=loan_id)
            .select_related("application__applicant")
            .order_by("-created_at")
            .first()
        )

        if not email:
            return Response(
                {"error": "No email found for this application"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not email.passed_guardrails:
            return Response(
                {"error": "Cannot send email that failed guardrails"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            require_decision_on_record(loan_id, email.decision)
        except DecisionMismatch as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)

        hold = bias_hold_reason(loan_id, email)
        if hold:
            return Response({"error": hold}, status=status.HTTP_409_CONFLICT)

        outcome = deliver_decision_email(email)
        if outcome["already_sent"]:
            return Response({"detail": "Email already sent."}, status=status.HTTP_200_OK)
        if outcome["sent"]:
            return Response({"sent": True, "recipient": outcome["recipient"], "email_id": str(email.id)})
        if outcome["recipient"] is None:
            return Response({"error": outcome["error"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"sent": False, "error": outcome["error"] or "Send failed"},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class EmailDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, loan_id):
        """Return the latest generated email for an application."""
        check_loan_access(request, loan_id)

        email = (
            _visible_emails(request.user, GeneratedEmail.objects.filter(application_id=loan_id))
            .select_related("application__applicant")
            .prefetch_related("guardrail_checks")
            .order_by("-created_at")
            .first()
        )

        if not email:
            return Response(
                {"error": "No email found for this application"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(_serialize_email(email, include_body=True, staff=_is_staff(request.user)))
