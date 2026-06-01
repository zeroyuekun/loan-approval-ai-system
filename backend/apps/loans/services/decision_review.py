"""Resolve a DecisionReview — uphold (no-op to the loan) or overturn (officer
override -> approve + send approval email). Uses the same locking discipline as
`agents.human_review_handler.resume_after_review` to avoid double-resolution and
respect the FOR-UPDATE-on-nullable-join caveat.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.loans.models import AuditLog, DecisionReview, LoanApplication, LoanDecision

logger = logging.getLogger(__name__)

_TERMINAL = {DecisionReview.Status.UPHELD, DecisionReview.Status.OVERTURNED, DecisionReview.Status.WITHDRAWN}


def _send_approval_email(application) -> None:
    """Re-generate + send the approval email after an overturn. Best-effort:
    a delivery failure must not roll back the approved decision."""
    try:
        from apps.email_engine.services.email_generator import EmailGenerator
        from apps.email_engine.services.persistence import EmailPersistenceService
        from apps.email_engine.services.sender import send_decision_email

        result = EmailGenerator().generate(application, "approved", confidence=application.decision.confidence)
        generated = EmailPersistenceService.save_generated_email(application, "approved", result)
        EmailPersistenceService.save_guardrail_logs(generated, result.get("guardrail_results", []))
        recipient = application.applicant.email
        if recipient and result.get("passed_guardrails"):
            send_decision_email(recipient, result["subject"], result["body"], email_type="approval")
    except Exception:  # noqa: BLE001 — email is best-effort post-override
        logger.exception("Approval email after overturn failed for application %s", application.id)


def apply_review_outcome(review: DecisionReview, *, officer, outcome: str, note: str) -> DecisionReview:
    if outcome not in ("upheld", "overturned"):
        raise ValueError(f"Invalid outcome {outcome!r}")

    with transaction.atomic():
        locked = DecisionReview.objects.select_for_update().get(pk=review.pk)
        if locked.status in _TERMINAL:
            raise ValueError(f"DecisionReview already resolved ({locked.status})")

        locked.assigned_officer = officer
        locked.resolution_note = note
        locked.resolved_at = timezone.now()

        if outcome == "upheld":
            locked.status = DecisionReview.Status.UPHELD
            locked.save(update_fields=["assigned_officer", "resolution_note", "resolved_at", "status"])
            application = locked.application
        else:
            locked.status = DecisionReview.Status.OVERTURNED
            locked.outcome_decision = "approved"
            locked.save(
                update_fields=[
                    "assigned_officer",
                    "resolution_note",
                    "resolved_at",
                    "status",
                    "outcome_decision",
                ]
            )
            application = LoanApplication.objects.select_for_update().get(pk=locked.application_id)
            # Lock the LoanDecision row directly by FK — not via the nullable
            # OneToOne join, which Postgres refuses to FOR UPDATE — so any
            # concurrent writer to human_involvement serialises behind us.
            decision = LoanDecision.objects.select_for_update().get(application_id=locked.application_id)
            decision.decision = "approved"
            decision.reasoning = f"Officer override via decision review {locked.id}: {note}".strip()
            decision.human_involvement = LoanDecision.HumanInvolvement.OVERRIDDEN
            decision.save(update_fields=["decision", "reasoning", "human_involvement"])
            # denied -> processing -> approved (validated transitions, each audited)
            application.transition_to("processing", user=officer, details={"source": "decision_review_overturn"})
            application.transition_to("approved", user=officer, details={"source": "decision_review_overturn"})

        AuditLog.objects.create(
            user=officer,
            action="decision_review_resolved",
            resource_type="DecisionReview",
            resource_id=str(locked.id),
            details={"outcome": outcome, "application_id": str(locked.application_id)},
        )

    if outcome == "overturned":
        _send_approval_email(application)

    return locked
