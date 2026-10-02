"""Resolve a DecisionReview — uphold (no-op to the loan) or overturn (officer
override -> approve + send approval email). Uses the same locking discipline as
`agents.human_review_handler.resume_after_review` to avoid double-resolution and
respect the FOR-UPDATE-on-nullable-join caveat.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.loans.models import AuditLog, DecisionReview, LoanApplication, LoanDecision

from .overturn_policy import evaluate_overturn_gate, normalize_overturn_mode
from .reviewer_independence import assert_independent_reviewer

logger = logging.getLogger(__name__)


class OverturnGateBlocked(PermissionDenied):
    """DECISION_OVERTURN_GATE_MODE refused this overturn (the message says why)."""


def _enforce_overturn_gate(application, officer) -> None:
    """Optional maker/checker gate on high-value overturns (default mode off).

    Lives in the service so every caller (API resolve, Django admin action,
    any batch job) goes through it.
    """
    gate = evaluate_overturn_gate(
        amount=float(application.loan_amount or 0),
        threshold=getattr(settings, "DECISION_OVERTURN_THRESHOLD", 100000.0),
        mode=normalize_overturn_mode(getattr(settings, "DECISION_OVERTURN_GATE_MODE", "off")),
    )
    if not gate["allowed"]:
        raise OverturnGateBlocked(gate["reason"])


_TERMINAL = {DecisionReview.Status.UPHELD, DecisionReview.Status.OVERTURNED, DecisionReview.Status.WITHDRAWN}


def _send_approval_email(application) -> None:
    """Queue the approval email for after the overturn commits. Best-effort:
    a dispatch failure must not roll back the approved decision.

    The email task generates, bias-checks and sends it (template fallback on
    provider trouble, a row-locked send that stamps sent_at). Running that
    here would hold the HTTP request or the admin action open for an LLM call
    and an SMTP round trip.
    """
    application_id = str(application.pk)

    def _dispatch():
        try:
            from apps.email_engine.tasks import generate_email_task

            generate_email_task.delay(application_id, "approved", regenerate=True)
        except Exception:  # noqa: BLE001 — email is best-effort post-override
            logger.exception("Approval email after overturn could not be queued for application %s", application_id)

    transaction.on_commit(_dispatch)


def apply_review_outcome(review: DecisionReview, *, officer, outcome: str, note: str) -> DecisionReview:
    if outcome not in ("upheld", "overturned"):
        raise ValueError(f"Invalid outcome {outcome!r}")

    with transaction.atomic():
        locked = DecisionReview.objects.select_for_update().get(pk=review.pk)
        if locked.status in _TERMINAL:
            raise ValueError(f"DecisionReview already resolved ({locked.status})")

        assert_independent_reviewer(officer, locked.application, review=locked)

        locked.assigned_officer = officer
        locked.resolution_note = note
        locked.resolved_at = timezone.now()

        if outcome == "upheld":
            locked.status = DecisionReview.Status.UPHELD
            locked.save(update_fields=["assigned_officer", "resolution_note", "resolved_at", "status"])
            application = locked.application
            # A human officer reviewed and CONFIRMED the decision: record the human
            # touch so the ADM disclosure stops reporting 'solely automated' (the
            # symmetric counterpart to the OVERRIDDEN stamp on the overturn path).
            # Promote NONE -> ASSISTED only; never downgrade an existing stamp.
            try:
                decision = LoanDecision.objects.select_for_update().get(application_id=locked.application_id)
            except LoanDecision.DoesNotExist:
                decision = None
            if decision is not None and decision.mark_human(LoanDecision.HumanInvolvement.ASSISTED):
                decision.save(update_fields=["human_involvement"])
        else:
            try:
                application = LoanApplication.objects.select_for_update().get(pk=locked.application_id)
            except LoanApplication.DoesNotExist as exc:
                # App soft-deleted (retention/erasure) between filing and
                # resolution: SoftDeleteManager hides it -> raise the ValueError
                # the view/admin already map to a clean 409, not an uncaught 500.
                raise ValueError("Application no longer exists") from exc
            # Re-assert overturn-eligibility under the lock: a force re-run or a
            # concurrent overturn may have moved the app off 'denied' between
            # filing and resolution. transition_to would otherwise raise
            # InvalidStateTransition (NOT a ValueError) -> uncaught 500.
            if application.status != "denied":
                raise ValueError("Application is no longer in a declined state")
            _enforce_overturn_gate(application, officer)

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
            # Lock the LoanDecision row directly by FK — not via the nullable
            # OneToOne join, which Postgres refuses to FOR UPDATE — so any
            # concurrent writer to human_involvement serialises behind us.
            try:
                decision = LoanDecision.objects.select_for_update().get(application_id=locked.application_id)
            except LoanDecision.DoesNotExist as exc:
                raise ValueError("No decision record exists for this application") from exc
            decision.decision = "approved"
            decision.reasoning = f"Officer override via decision review {locked.id}: {note}".strip()
            decision.mark_human(LoanDecision.HumanInvolvement.OVERRIDDEN)
            decision.save(update_fields=["decision", "reasoning", "human_involvement"])
            try:
                # denied -> processing -> approved (validated transitions, each audited)
                application.transition_to("processing", user=officer, details={"source": "decision_review_overturn"})
                application.transition_to("approved", user=officer, details={"source": "decision_review_overturn"})
            except LoanApplication.InvalidStateTransition as exc:
                raise ValueError(str(exc)) from exc

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


def withdraw_review(review: DecisionReview, *, user) -> DecisionReview:
    """Customer-initiated withdrawal of a review they filed in error.

    Only the original requester can withdraw, and only from a non-terminal
    state. Audited; does NOT change the loan decision (the original denial
    stands). Mirrors the locking discipline of apply_review_outcome.
    """
    with transaction.atomic():
        locked = DecisionReview.objects.select_for_update().get(pk=review.pk)
        if locked.requested_by_id != user.id:
            raise ValueError("Only the requester can withdraw this review")
        if locked.status in _TERMINAL:
            raise ValueError(f"DecisionReview already resolved ({locked.status})")
        locked.status = DecisionReview.Status.WITHDRAWN
        locked.resolved_at = timezone.now()
        locked.save(update_fields=["status", "resolved_at"])
        AuditLog.objects.create(
            user=user,
            action="decision_review_withdrawn",
            resource_type="DecisionReview",
            resource_id=str(locked.id),
            details={"application_id": str(locked.application_id)},
        )
    return locked
