"""Staff view of one customer's emails and agent runs.

Built from the same serializers the email and agent-run endpoints use, so a
field added there shows up here too. Text is returned raw: the frontend
escapes it when rendering.
"""

from apps.agents.models import AgentRun
from apps.agents.serializers import AgentRunSerializer
from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.email_payload import serialize_email

ACTIVITY_LIMIT = 50


def customer_activity(customer) -> dict:
    app_ids = list(customer.loan_applications.values_list("id", flat=True))

    # Fetch the most-recent IDs first so prefetch_related operates on a
    # non-sliced queryset (Django drops prefetches on sliced querysets,
    # causing an N+1 on guardrail_checks).
    top_email_ids = list(
        GeneratedEmail.objects.filter(application_id__in=app_ids)
        .order_by("-created_at")
        .values_list("id", flat=True)[:ACTIVITY_LIMIT]
    )
    emails = (
        GeneratedEmail.objects.filter(id__in=top_email_ids)
        .select_related("application__applicant")
        .prefetch_related("guardrail_checks")
        .order_by("-created_at")
    )

    runs = AgentRun.objects.for_serializer().filter(application_id__in=app_ids).order_by("-created_at")[:ACTIVITY_LIMIT]

    return {
        "customer_id": customer.id,
        "customer_name": f"{customer.first_name} {customer.last_name}".strip() or customer.username,
        "emails": [serialize_email(email, include_body=True) for email in emails],
        "agent_runs": AgentRunSerializer(runs, many=True, context={"include_html": True}).data,
    }
