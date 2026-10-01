"""Issuing decision emails (approval / denial) to the applicant.

The decision an email announces always comes from the application's
``LoanDecision`` record, never from a caller-supplied value: an approval letter
carries a rate, repayments and a sign-by date, so sending one for a pending or
denied application is a false credit representation.
"""

from apps.loans.models import LoanDecision


class DecisionMismatch(ValueError):
    """The requested decision email disagrees with the decision on record."""


def decision_on_record(application_id):
    """Return ``"approved"``/``"denied"`` from LoanDecision, or None if undecided."""
    return LoanDecision.objects.filter(application_id=application_id).values_list("decision", flat=True).first()


def require_decision_on_record(application_id, requested=None):
    """Return the recorded decision, refusing when there is none or it disagrees.

    ``requested=None`` means "whatever is on record".
    """
    recorded = decision_on_record(application_id)
    if recorded is None:
        raise DecisionMismatch(f"Application {application_id} has no decision on record")
    if requested is not None and requested != recorded:
        raise DecisionMismatch(
            f"Requested a {requested!r} email but the decision on record for application {application_id} "
            f"is {recorded!r}"
        )
    return recorded
