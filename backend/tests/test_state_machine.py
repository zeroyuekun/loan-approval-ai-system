"""Tests for loan application state machine transitions.

Basic tests for status transitions on LoanApplication. The state machine may
not have explicit transition validation yet, so these tests verify the current
model behavior and document expected constraints.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication


class TestLoanStatusTransitions(TestCase):
    """Test loan application status transitions."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="statemachine_test",
            password="testpass123",
            email="sm@test.com",
            role="customer",
        )
        self.app = LoanApplication.objects.create(
            applicant=self.user,
            annual_income=Decimal("75000.00"),
            credit_score=720,
            loan_amount=Decimal("25000.00"),
            loan_term_months=36,
            debt_to_income=Decimal("1.50"),
            employment_length=5,
            purpose="personal",
            home_ownership="rent",
            employment_type="payg_permanent",
            applicant_type="single",
        )

    def test_initial_status_is_pending(self):
        """New applications should start in pending status."""
        assert self.app.status == "pending", f"Initial status should be pending, got {self.app.status}"

    def test_pending_to_processing(self):
        """Application can move from pending to processing."""
        self.app.status = "processing"
        self.app.save()
        self.app.refresh_from_db()
        assert self.app.status == "processing"

    def test_processing_to_approved(self):
        """Application can move from processing to approved."""
        self.app.status = "processing"
        self.app.save()
        self.app.status = "approved"
        self.app.save()
        self.app.refresh_from_db()
        assert self.app.status == "approved"

    def test_processing_to_denied(self):
        """Application can move from processing to denied."""
        self.app.status = "processing"
        self.app.save()
        self.app.status = "denied"
        self.app.save()
        self.app.refresh_from_db()
        assert self.app.status == "denied"

    def test_processing_to_review(self):
        """Application can move from processing to review."""
        self.app.status = "processing"
        self.app.save()
        self.app.status = "review"
        self.app.save()
        self.app.refresh_from_db()
        assert self.app.status == "review"

    def test_valid_status_choices(self):
        """All status values should be from the defined choices."""
        valid_statuses = {choice[0] for choice in LoanApplication.Status.choices}
        expected = {"pending", "processing", "approved", "denied", "review"}
        assert valid_statuses == expected, f"Status choices mismatch: got {valid_statuses}, expected {expected}"

    def test_status_persists_after_save(self):
        """Status change should persist after save and refresh."""
        for target_status in ["processing", "approved", "denied", "review"]:
            self.app.status = target_status
            self.app.save()
            self.app.refresh_from_db()
            assert self.app.status == target_status, f"Status {target_status} did not persist after save"
            # Reset for next iteration
            self.app.status = "pending"
            self.app.save()
