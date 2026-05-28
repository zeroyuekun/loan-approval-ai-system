import pytest

from apps.loans.models import DecisionReview, LoanApplication

pytestmark = pytest.mark.django_db


def _app(django_user_model):
    u = django_user_model.objects.create_user(username="c", password="x", role="customer")
    return LoanApplication.objects.create(
        applicant=u,
        annual_income=50000,
        credit_score=500,
        loan_amount=30000,
        debt_to_income=5,
        employment_length=1,
        purpose="personal",
        home_ownership="rent",
        status="denied",
    )


def test_decision_review_defaults_to_requested(django_user_model):
    app = _app(django_user_model)
    review = DecisionReview.objects.create(application=app, requested_by=app.applicant, reason="I disagree")
    assert review.status == DecisionReview.Status.REQUESTED
    assert review.resolved_at is None
