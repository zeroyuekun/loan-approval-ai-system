"""Tests for the staff-only, reason-audited force rerun on /agents/orchestrate/."""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog


@pytest.fixture
def customer(db):
    return CustomUser.objects.create_user(
        username="cust_force",
        email="cust@test.com",
        password="testpass123",
        role="customer",
        first_name="Cust",
        last_name="F",
    )


@pytest.fixture
def officer(db):
    return CustomUser.objects.create_user(
        username="officer_force",
        email="officer@test.com",
        password="testpass123",
        role="officer",
        first_name="Off",
        last_name="F",
    )


@pytest.fixture
def loan_app(db, customer):
    from apps.loans.models import LoanApplication
    return LoanApplication.objects.create(
        applicant=customer,
        loan_amount=20000,
        annual_income=80000,
        credit_score=700,
        loan_term_months=24,
        debt_to_income=0.3,
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
    )


@pytest.fixture
def completed_run(db, loan_app):
    from apps.agents.models import AgentRun
    return AgentRun.objects.create(
        application_id=loan_app.id,
        status=AgentRun.Status.COMPLETED,
    )


@pytest.mark.django_db
class TestOrchestrationForceGuard:
    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_customer_with_force_true_denied(self, mock_delay, customer, loan_app):
        client = APIClient()
        client.force_authenticate(user=customer)
        resp = client.post(f"/api/v1/agents/orchestrate/{loan_app.id}/?force=true")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "staff" in (resp.json().get("detail") or "").lower()
        assert mock_delay.call_count == 0

    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_staff_force_without_reason_denied(self, mock_delay, officer, loan_app):
        client = APIClient()
        client.force_authenticate(user=officer)
        resp = client.post(f"/api/v1/agents/orchestrate/{loan_app.id}/?force=true")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "reason" in (resp.json().get("detail") or "").lower()
        assert mock_delay.call_count == 0

    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_staff_force_with_reason_dispatches_and_audits(
        self, mock_delay, officer, loan_app
    ):
        mock_delay.return_value.id = "task-abc"
        client = APIClient()
        client.force_authenticate(user=officer)
        resp = client.post(
            f"/api/v1/agents/orchestrate/{loan_app.id}/?force=true&reason=bias_fix"
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        mock_delay.assert_called_once_with(str(loan_app.id), force=True)

        audit_entries = AuditLog.objects.filter(
            action="pipeline_force_rerun",
            resource_id=str(loan_app.id),
        )
        assert audit_entries.exists()
        assert audit_entries.first().details.get("reason") == "bias_fix"

    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_customer_non_force_on_completed_returns_existing(
        self, mock_delay, customer, loan_app, completed_run
    ):
        """Non-force path on a completed loan returns existing run without dispatching."""
        mock_delay.return_value.id = "should-not-dispatch"
        client = APIClient()
        client.force_authenticate(user=customer)
        resp = client.post(f"/api/v1/agents/orchestrate/{loan_app.id}/")
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body.get("status") == "already_completed"
        assert body.get("existing_run_id") == str(completed_run.id)
        assert mock_delay.call_count == 0
