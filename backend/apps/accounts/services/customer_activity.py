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
    # A soft-deleted application's emails and runs stay hidden, as its
    # related manager hides the application itself.
    of_customer = {"application__applicant": customer, "application__deleted_at__isnull": True}
    emails = (
        GeneratedEmail.objects.filter(**of_customer)
        .select_related("application__applicant")
        .prefetch_related("guardrail_checks")
        .order_by("-created_at")[:ACTIVITY_LIMIT]
    )
    runs = AgentRun.objects.for_serializer().filter(**of_customer).order_by("-created_at")[:ACTIVITY_LIMIT]

    return {
        "customer_id": customer.id,
        "customer_name": f"{customer.first_name} {customer.last_name}".strip() or customer.username,
        "emails": [serialize_email(email, include_body=True) for email in emails],
        "agent_runs": AgentRunSerializer(runs, many=True, context={"include_html": True}).data,
    }
