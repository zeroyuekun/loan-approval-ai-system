"""Tests for the submission outbox — Codex finding #4 (durable dispatch)."""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile, CustomUser
from apps.loans.models import LoanApplication, PipelineDispatchOutbox
from apps.loans.tasks import retry_failed_dispatches


def _complete_profile(user):
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.date_of_birth = "1990-01-15"
    profile.phone = "0412345678"
    profile.address_line_1 = "123 Test St"
    profile.suburb = "Sydney"
    profile.state = "NSW"
    profile.postcode = "2000"
    profile.residency_status = "citizen"
    profile.primary_id_type = "drivers_licence"
    profile.primary_id_number = "DL12345678"
    profile.employment_status = "payg_permanent"
    profile.gross_annual_income = 85000
    profile.housing_situation = "renting"
    profile.number_of_dependants = 0
    profile.save()
    return profile


LOAN_PAYLOAD = {
    "annual_income": "85000.00",
    "credit_score": 780,
    "loan_amount": "25000.00",
    "loan_term_months": 36,
    "debt_to_income": "1.50",
    "employment_length": 5,
    "purpose": "personal",
    "home_ownership": "rent",
    "employment_type": "payg_permanent",
    "applicant_type": "single",
    "state": "NSW",
}


class TestSubmissionOutbox(TestCase):
    """Durable dispatch: broker outages route to the outbox, not the floor.

    Uses Django's TestCase because we need captureOnCommitCallbacks to test
    the transaction.on_commit dispatch path inside perform_create.
    """

    def setUp(self):
        self.customer = CustomUser.objects.create_user(
            username="outbox_customer",
            email="outbox@test.com",
            password="TestPass123!",
            role="customer",
            first_name="Outbox",
            last_name="Tester",
        )
        _complete_profile(self.customer)
        profile = self.customer.profile
        profile.refresh_from_db()
        assert profile.is_profile_complete, f"Profile missing: {profile.missing_profile_fields}"
        self.client = APIClient()
        self.client.force_authenticate(user=self.customer)

    def test_broker_failure_creates_outbox_row(self):
        """When Celery .delay() raises, the loan gets an outbox row and
        QUEUE_FAILED status."""
        with patch(
            "apps.agents.tasks.orchestrate_pipeline_task.delay",
            side_effect=ConnectionError("broker unreachable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post("/api/v1/loans/", LOAN_PAYLOAD, format="json")

        assert response.status_code == 201, response.content
        loan_id = response.json()["id"]

        application = LoanApplication.objects.get(pk=loan_id)
        assert application.status == LoanApplication.Status.QUEUE_FAILED
        assert PipelineDispatchOutbox.objects.filter(application=application).exists()
        entry = PipelineDispatchOutbox.objects.get(application=application)
        assert "broker unreachable" in entry.last_error

    def test_successful_dispatch_leaves_no_outbox_row(self):
        """Happy path — no outbox row is created when dispatch succeeds."""
        with patch("apps.agents.tasks.orchestrate_pipeline_task.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post("/api/v1/loans/", LOAN_PAYLOAD, format="json")

        assert response.status_code == 201
        assert mock_delay.called
        loan_id = response.json()["id"]
        assert not PipelineDispatchOutbox.objects.filter(application_id=loan_id).exists()

    def _make_application(self):
        from decimal import Decimal

        return LoanApplication.objects.create(
            applicant=self.customer,
            annual_income=Decimal("75000.00"),
            credit_score=720,
            loan_amount=Decimal("25000.00"),
            loan_term_months=36,
            debt_to_income=Decimal("1.50"),
            employment_length=5,
            purpose="personal",
            home_ownership="rent",
            has_cosigner=False,
            monthly_expenses=Decimal("2200.00"),
            existing_credit_card_limit=Decimal("8000.00"),
            number_of_dependants=0,
            employment_type="payg_permanent",
            applicant_type="single",
            has_hecs=False,
            has_bankruptcy=False,
            state="NSW",
            status=LoanApplication.Status.QUEUE_FAILED,
        )

    def test_retry_task_recovers_pending_row(self):
        """retry_failed_dispatches drains rows, re-queues, and flips status back."""
        application = self._make_application()
        PipelineDispatchOutbox.objects.create(
            application=application,
            last_error="broker unreachable",
        )

        with patch("apps.agents.tasks.orchestrate_pipeline_task.delay") as mock_delay:
            result = retry_failed_dispatches()

        assert mock_delay.called
        assert result["recovered"] == 1
        assert result["failed"] == 0
        assert not PipelineDispatchOutbox.objects.filter(application=application).exists()
        application.refresh_from_db()
        assert application.status == LoanApplication.Status.PENDING

    def test_retry_increments_attempts_on_repeated_failure(self):
        """When the broker is still down, attempts increment and last_error is
        recorded."""
        application = self._make_application()
        entry = PipelineDispatchOutbox.objects.create(
            application=application,
            last_error="initial failure",
        )

        with patch(
            "apps.agents.tasks.orchestrate_pipeline_task.delay",
            side_effect=ConnectionError("still down"),
        ):
            result = retry_failed_dispatches()

        assert result["recovered"] == 0
        assert result["failed"] == 1
        entry.refresh_from_db()
        assert entry.attempts == 1
        assert "still down" in entry.last_error
        assert entry.last_attempt_at is not None

    def test_retry_skips_exhausted_entries(self):
        """Rows at MAX_DISPATCH_ATTEMPTS are surfaced as exhausted but not
        retried automatically."""
        application = self._make_application()
        PipelineDispatchOutbox.objects.create(
            application=application,
            attempts=PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS,
            last_error="final failure",
        )

        with patch("apps.agents.tasks.orchestrate_pipeline_task.delay") as mock_delay:
            result = retry_failed_dispatches()

        assert not mock_delay.called
        assert result["recovered"] == 0
        assert result["exhausted"] == 1
