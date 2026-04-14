"""Integration test: orchestrator short-circuits on age-at-maturity denial.

Confirms that when EligibilityChecker denies an application, the orchestrator
writes a denied LoanDecision, transitions the application to 'denied', and
does NOT invoke the ML predictor.
"""

import datetime
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import CustomerProfile
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import LoanApplication, LoanDecision


@pytest.mark.django_db
def test_orchestrator_denies_on_age_maturity_and_skips_ml():
    User = get_user_model()
    user = User.objects.create_user(username="too-old", password="test-pass", role="customer")
    # Applicant is 65 today; with a 60-month term, maturity age is 70 → >67.
    # min(today.day, 28) avoids ValueError on Feb 29 -> non-leap year.
    today = datetime.date.today()
    dob = datetime.date(today.year - 65, today.month, min(today.day, 28))
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.date_of_birth = dob.isoformat()
    profile.save()

    app = LoanApplication.objects.create(
        applicant=user,
        loan_amount=25000,
        loan_term_months=60,
        purpose="personal",
        annual_income=80000,
        credit_score=720,
        debt_to_income=0.25,
        monthly_expenses=3000,
        employment_type="payg_permanent",
        employment_length=5,
        home_ownership="rent",
        state="NSW",
        applicant_type="single",
    )

    # If ML scoring is called, fail the test — the gate should short-circuit.
    with patch(
        "apps.ml_engine.services.predictor.ModelPredictor.predict",
        side_effect=AssertionError("ML predictor should not be called when policy gate fails"),
    ):
        orch = PipelineOrchestrator()
        orch.orchestrate(str(app.id))

    app.refresh_from_db()
    assert app.status == "denied"
    decision = LoanDecision.objects.get(application=app)
    assert decision.decision == "denied"
    assert "R71" in (decision.reasoning or "")
