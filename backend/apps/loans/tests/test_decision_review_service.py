import pytest

from apps.loans.models import AuditLog, DecisionReview, LoanApplication, LoanDecision
from apps.loans.services.decision_review import apply_review_outcome

pytestmark = pytest.mark.django_db


def _denied_with_review(django_user_model):
    cust = django_user_model.objects.create_user(username="c", password="x", role="customer", email="c@x.com")
    officer = django_user_model.objects.create_user(username="o", password="x", role="officer")
    app = LoanApplication.objects.create(
        applicant=cust,
        annual_income=50000,
        credit_score=500,
        loan_amount=30000,
        debt_to_income=5,
        employment_length=1,
        purpose="personal",
        home_ownership="rent",
        status="denied",
    )
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    review = DecisionReview.objects.create(
        application=app, requested_by=cust, reason="disagree", status=DecisionReview.Status.UNDER_REVIEW
    )
    return app, officer, review


def test_uphold_marks_review_and_keeps_denied(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="upheld", note="confirmed")
    review.refresh_from_db()
    app.refresh_from_db()
    assert review.status == DecisionReview.Status.UPHELD
    assert app.status == "denied"
    assert AuditLog.objects.filter(action="decision_review_resolved", resource_id=str(review.id)).exists()


def test_uphold_stamps_human_involvement_assisted(django_user_model):
    """An upheld review is a human-reviewed event: the decision must be stamped
    ASSISTED so the ADM disclosure stops reporting 'solely automated' (the
    disclosure derives its mode from this persisted fact)."""
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="upheld", note="confirmed")
    decision = LoanDecision.objects.get(application=app)
    assert decision.human_involvement == LoanDecision.HumanInvolvement.ASSISTED


def test_overturn_approves_and_audits(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="overturned", note="manual approve")
    review.refresh_from_db()
    app.refresh_from_db()
    assert review.status == DecisionReview.Status.OVERTURNED
    assert app.status == "approved"
    assert app.decision.decision == "approved"


def test_double_resolve_raises(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="upheld", note="x")
    with pytest.raises(ValueError):
        apply_review_outcome(review, officer=officer, outcome="overturned", note="y")


def test_overturn_on_non_denied_app_raises_valueerror(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    # Simulate a concurrent force re-run that moved the app off 'denied'.
    app.transition_to("processing", details={"source": "test_force_rerun"})
    app.refresh_from_db()
    assert app.status == "processing"
    with pytest.raises(ValueError):
        apply_review_outcome(review, officer=officer, outcome="overturned", note="late")


def test_overturn_missing_decision_raises_valueerror(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    app.decision.delete()  # LoanDecision gone -> RelatedObjectDoesNotExist path
    with pytest.raises(ValueError):
        apply_review_outcome(review, officer=officer, outcome="overturned", note="x")


def test_withdraw_marks_review_and_keeps_app_status(django_user_model):
    from apps.loans.services.decision_review import withdraw_review

    app, officer, review = _denied_with_review(django_user_model)  # status UNDER_REVIEW
    withdraw_review(review, user=review.requested_by)
    review.refresh_from_db()
    app.refresh_from_db()
    assert review.status == DecisionReview.Status.WITHDRAWN
    assert app.status == "denied"  # withdraw does not change the loan decision
    assert AuditLog.objects.filter(action="decision_review_withdrawn", resource_id=str(review.id)).exists()


def test_withdraw_already_resolved_raises(django_user_model):
    from apps.loans.services.decision_review import apply_review_outcome, withdraw_review

    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="upheld", note="stands")
    with pytest.raises(ValueError):
        withdraw_review(review, user=review.requested_by)


def _make_officer_a_party(party, app, officer, review):
    if party == "applicant":  # staff can also be borrowers
        app.applicant = officer
        app.save(update_fields=["applicant"])
    elif party == "filer":  # filed the review on someone's behalf
        review.requested_by = officer
        review.save(update_fields=["requested_by"])
    elif party == "decider":  # denied it by hand, recorded on the transition
        AuditLog.objects.create(
            user=officer,
            action="status_transition",
            resource_type="LoanApplication",
            resource_id=str(app.id),
            details={"from_status": "review", "to_status": "denied"},
        )
    else:  # a human-review deny from before the transition recorded the reviewer
        AuditLog.objects.create(
            user=officer,
            action="human_review_deny",
            resource_type="AgentRun",
            resource_id="00000000-0000-0000-0000-000000000001",
            details={"note": "n", "application_id": str(app.id), "original_decision": "approved"},
        )
        AuditLog.objects.create(
            user=None,
            action="status_transition",
            resource_type="LoanApplication",
            resource_id=str(app.id),
            details={"from_status": "review", "to_status": "denied"},
        )


@pytest.mark.parametrize("outcome", ["upheld", "overturned"])
@pytest.mark.parametrize("party", ["applicant", "filer", "decider", "historical_human_review_decider"])
def test_an_officer_who_is_a_party_cannot_resolve_the_review(django_user_model, party, outcome):
    from django.core.exceptions import PermissionDenied

    app, officer, review = _denied_with_review(django_user_model)
    _make_officer_a_party(party, app, officer, review)

    with pytest.raises(PermissionDenied):
        apply_review_outcome(review, officer=officer, outcome=outcome, note="x")
    review.refresh_from_db()
    app.refresh_from_db()
    assert review.status == DecisionReview.Status.UNDER_REVIEW
    assert app.status == "denied"
    assert app.decision.decision == "denied"
