"""Tests for loan application state machine transitions.

Tests the transition_to() method that validates state transitions,
prevents illegal transitions, and creates audit log entries.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog, LoanApplication


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
        assert self.app.status == "pending"

    def test_pending_to_processing(self):
        self.app.transition_to("processing")
        self.app.refresh_from_db()
        assert self.app.status == "processing"

    def test_processing_to_approved(self):
        self.app.transition_to("processing")
        self.app.transition_to("approved")
        self.app.refresh_from_db()
        assert self.app.status == "approved"

    def test_processing_to_denied(self):
        self.app.transition_to("processing")
        self.app.transition_to("denied")
        self.app.refresh_from_db()
        assert self.app.status == "denied"

    def test_processing_to_review(self):
        self.app.transition_to("processing")
        self.app.transition_to("review")
        self.app.refresh_from_db()
        assert self.app.status == "review"

    def test_review_to_approved(self):
        self.app.transition_to("processing")
        self.app.transition_to("review")
        self.app.transition_to("approved")
        self.app.refresh_from_db()
        assert self.app.status == "approved"

    def test_review_to_denied(self):
        self.app.transition_to("processing")
        self.app.transition_to("review")
        self.app.transition_to("denied")
        self.app.refresh_from_db()
        assert self.app.status == "denied"

    def test_review_to_pending_regenerate(self):
        """Regenerate resets review back to pending."""
        self.app.transition_to("processing")
        self.app.transition_to("review")
        self.app.transition_to("pending")
        self.app.refresh_from_db()
        assert self.app.status == "pending"

    def test_processing_to_pending_rollback(self):
        """Failed prediction rolls back processing to pending."""
        self.app.transition_to("processing")
        self.app.transition_to("pending", details={"reason": "prediction_failed"})
        self.app.refresh_from_db()
        assert self.app.status == "pending"

    # --- Invalid transitions ---

    def test_pending_to_approved_invalid(self):
        """Cannot skip processing and go straight to approved."""
        with self.assertRaises(LoanApplication.InvalidStateTransition):
            self.app.transition_to("approved")

    def test_pending_to_review_invalid(self):
        """Cannot skip processing and go straight to review."""
        with self.assertRaises(LoanApplication.InvalidStateTransition):
            self.app.transition_to("review")

    def test_approved_allows_reprocessing(self):
        """Can transition from approved back to processing for pipeline re-run."""
        self.app.transition_to("processing")
        self.app.transition_to("approved")
        self.app.transition_to("processing")
        self.assertEqual(self.app.status, "processing")

    def test_approved_blocks_other_transitions(self):
        """Cannot transition from approved to anything except processing."""
        self.app.transition_to("processing")
        self.app.transition_to("approved")
        with self.assertRaises(LoanApplication.InvalidStateTransition):
            self.app.transition_to("pending")

    def test_denied_allows_reprocessing(self):
        """Can transition from denied back to processing for pipeline re-run."""
        self.app.transition_to("processing")
        self.app.transition_to("denied")
        self.app.transition_to("processing")
        self.assertEqual(self.app.status, "processing")

    def test_denied_blocks_other_transitions(self):
        """Cannot transition from denied to anything except processing."""
        self.app.transition_to("processing")
        self.app.transition_to("denied")
        with self.assertRaises(LoanApplication.InvalidStateTransition):
            self.app.transition_to("pending")

    def test_invalid_status_value(self):
        """Cannot transition to a non-existent status."""
        with self.assertRaises(LoanApplication.InvalidStateTransition):
            self.app.transition_to("nonexistent")

    # --- Audit logging ---

    def test_transition_creates_audit_log(self):
        """Each transition should create an AuditLog entry."""
        initial_count = AuditLog.objects.count()
        self.app.transition_to("processing", user=self.user)
        assert AuditLog.objects.count() == initial_count + 1

        log = AuditLog.objects.order_by("-timestamp").first()
        assert log.action == "status_transition"
        assert log.resource_type == "LoanApplication"
        assert log.resource_id == str(self.app.id)
        assert log.details["from_status"] == "pending"
        assert log.details["to_status"] == "processing"
        assert log.user == self.user

    def test_transition_audit_includes_details(self):
        """Custom details should be included in audit log."""
        self.app.transition_to("processing", details={"source": "orchestrator"})
        log = AuditLog.objects.order_by("-timestamp").first()
        assert log.details["source"] == "orchestrator"

    def test_invalid_transition_does_not_create_audit_log(self):
        """Failed transitions should not create audit entries."""
        initial_count = AuditLog.objects.count()
        with self.assertRaises(LoanApplication.InvalidStateTransition):
            self.app.transition_to("approved")
        assert AuditLog.objects.count() == initial_count

    def test_valid_status_choices(self):
        """All status values should be from the defined choices."""
        valid_statuses = {choice[0] for choice in LoanApplication.Status.choices}
        expected = {"pending", "processing", "approved", "denied", "review"}
        assert valid_statuses == expected
