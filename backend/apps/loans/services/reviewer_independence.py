"""Who may review a decision on a loan application.

Staff can also be borrowers, and a role says nothing about independence: the
applicant may not review their own application, the customer who filed a
decision review may not resolve it, and the officer who made the decision
under review may not resolve it either (four-eyes).
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from apps.loans.models import AuditLog


class ReviewerNotIndependent(PermissionDenied):
    """The user is a party to what they are asked to review."""


def assert_independent_reviewer(user, application, *, review=None) -> None:
    """Raise ReviewerNotIndependent unless ``user`` may review ``application``.

    Without ``review`` (the human-review queue) only the applicant is
    excluded. With a DecisionReview, its filer and the officer who made the
    decision under review are excluded too.
    """
    if user.pk == application.applicant_id:
        raise ReviewerNotIndependent("You cannot review a decision on your own application.")
    if review is None:
        return
    if user.pk == review.requested_by_id:
        raise ReviewerNotIndependent("You cannot resolve a review you filed.")
    if _made_the_decision(user, application):
        raise ReviewerNotIndependent(
            "An officer cannot resolve their own decision — four-eyes policy requires a second approver."
        )


def _made_the_decision(user, application) -> bool:
    """True if ``user`` made the denial under review.

    That is whoever last moved the application to ``denied`` by hand (an
    automated ML decision has no user and exempts nobody). A human-review
    denial records the reviewer on that transition; older ones recorded
    it only on the ``human_review_deny`` row, which is checked as well.
    """
    last_denier_id = (
        AuditLog.objects.filter(
            resource_type="LoanApplication",
            resource_id=str(application.pk),
            action="status_transition",
            details__to_status="denied",
            user__isnull=False,
        )
        .order_by("-timestamp")
        .values_list("user_id", flat=True)
        .first()
    )
    if last_denier_id == user.pk:
        return True
    return AuditLog.objects.filter(
        action="human_review_deny", details__application_id=str(application.pk), user_id=user.pk
    ).exists()
