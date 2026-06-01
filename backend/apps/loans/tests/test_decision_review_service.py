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


def test_overturn_approves_and_audits(django_user_model, monkeypatch):
    import apps.loans.services.decision_review as svc

    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
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
