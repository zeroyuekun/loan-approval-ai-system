"""APP 12 (Australian Privacy Act 1988) customer data export.

The export is the customer's own view of their data, so it follows the same
visibility rules as the customer API: only emails that were actually sent to
them, the customer-facing summary of each pipeline run, and no internal bias
analysis. Drafts that the guardrails withheld or the bias check held back are
excluded, because their bodies may carry exactly the content those checks
exist to stop.
"""

from django.db.models import Prefetch

from apps.agents.models import AgentRun, MarketingEmail
from apps.agents.serializers import customer_steps
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import AuditLog, LoanApplication, LoanDecision

from ..models import CustomerProfile

# Prevent unbounded memory load for high-volume applicants. Real users will
# never exceed these caps; attackers who synthesise many records would OOM
# the worker without them.
MAX_APPLICATIONS = 500
MAX_EMAILS_PER_APP = 50
MAX_AGENT_RUNS_PER_APP = 20
MAX_AUDIT_ENTRIES = 100


def _user_section(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "created_at": user.created_at.isoformat(),
    }


def _profile_section(user):
    try:
        profile = user.profile
    except CustomerProfile.DoesNotExist:
        return None
    return {
        f.name: str(getattr(profile, f.name, ""))
        for f in profile._meta.get_fields()
        if hasattr(f, "column") and f.name not in ("id", "user")
    }


def _decision_section(app):
    try:
        d = app.decision
    except LoanDecision.DoesNotExist:
        return None
    return {
        "decision": d.decision,
        "confidence": d.confidence,
        "risk_grade": d.risk_grade,
        "feature_importances": d.feature_importances,
        "shap_values": d.shap_values,
        "reasoning": d.reasoning,
        "model_version": str(d.model_version) if d.model_version else None,
        "created_at": d.created_at.isoformat(),
    }


def _application_section(app):
    return {
        "id": str(app.id),
        "loan_amount": str(app.loan_amount),
        "purpose": app.purpose,
        "status": app.status,
        "created_at": app.created_at.isoformat(),
        "decision": _decision_section(app),
        "emails": [
            {
                "subject": e.subject,
                "body": e.body,
                "decision": e.decision,
                "sent_at": e.sent_at.isoformat(),
                "created_at": e.created_at.isoformat(),
            }
            for e in app._sent_emails
        ],
        "marketing_emails": [
            {
                "subject": me.subject,
                "body": me.body,
                "sent_at": me.sent_at.isoformat() if me.sent_at else None,
                "created_at": me.created_at.isoformat(),
            }
            for me in app._sent_marketing_emails
        ],
        "agent_runs": [
            {
                "status": run.status,
                "steps": customer_steps(run),
                "created_at": run.created_at.isoformat(),
            }
            for run in app._agent_runs_cached
        ],
    }


def build_customer_export(user):
    """Everything the customer may see about themselves, as a JSON-ready dict."""
    applications = (
        LoanApplication.objects.filter(applicant=user)
        .select_related("decision", "decision__model_version")
        .prefetch_related(
            # Bounded Prefetch querysets so the prefetch cache is hit inside the
            # loop (slicing a related manager would bypass it: N+1 queries).
            Prefetch(
                "emails",
                queryset=GeneratedEmail.objects.filter(sent_at__isnull=False).order_by("-created_at")[
                    :MAX_EMAILS_PER_APP
                ],
                to_attr="_sent_emails",
            ),
            Prefetch(
                "agent_runs",
                queryset=AgentRun.objects.order_by("-created_at")[:MAX_AGENT_RUNS_PER_APP],
                to_attr="_agent_runs_cached",
            ),
            Prefetch(
                "marketing_emails",
                queryset=MarketingEmail.objects.filter(sent=True).order_by("-created_at")[:MAX_EMAILS_PER_APP],
                to_attr="_sent_marketing_emails",
            ),
        )
        .order_by("-created_at")[:MAX_APPLICATIONS]
    )

    audit_logs = (
        AuditLog.objects.filter(user=user)
        .order_by("-timestamp")[:MAX_AUDIT_ENTRIES]
        .values("action", "resource_type", "timestamp")
    )

    return {
        "user": _user_section(user),
        "profile": _profile_section(user),
        "loan_applications": [_application_section(app) for app in applications],
        "audit_logs": [{k: str(v) for k, v in log.items()} for log in audit_logs],
    }
