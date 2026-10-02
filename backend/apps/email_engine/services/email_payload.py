"""Response shape for a GeneratedEmail, shared by every endpoint that returns one."""

from apps.email_engine.services.decision_email import email_type_for
from apps.email_engine.services.html_renderer import render_html


def serialize_email(email, *, include_body, staff=True):
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
