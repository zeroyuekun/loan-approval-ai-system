"""Tests for Finding 2 — BatchOrchestrateView hard cap.

Closes the Codex adversarial review finding that `max_batch=100` was only
applied in the recheck branch, leaving the default path able to dispatch
an unbounded backlog to Celery.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.loans.models import AuditLog, LoanApplication

BATCH_URL = "/api/v1/agents/orchestrate-all/"


def _no_throttle(self, request, view):
    """Bypass DRF throttles for test scenarios."""
    return True


def _make_application(applicant, status_value=LoanApplication.Status.PENDING):
    """Minimal LoanApplication matching the `sample_application` fixture shape."""
    return LoanApplication.objects.create(
        applicant=applicant,
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
        status=status_value,
    )


class _FakeTask:
    def __init__(self, task_id="task-fake"):
        self.id = task_id


@pytest.fixture(autouse=True)
def disable_throttles(monkeypatch):
    from rest_framework.throttling import UserRateThrottle

    monkeypatch.setattr(UserRateThrottle, "allow_request", _no_throttle)


@pytest.mark.django_db
class TestBatchOrchestrateCap:
    def _post(self, admin_user, query=""):
        from apps.agents import views

        client = APIClient()
        client.force_authenticate(user=admin_user)
        url = BATCH_URL + (f"?{query}" if query else "")

        with patch(
            "apps.agents.views.orchestrate_pipeline_task.delay",
            return_value=_FakeTask(),
        ) as mock_delay:
            response = client.post(url)
        return response, mock_delay, views.BATCH_ORCHESTRATE_MAX

    def test_default_path_caps_at_max_and_reports_skipped(self, admin_user, customer_user):
        from apps.agents.views import BATCH_ORCHESTRATE_MAX

        for _ in range(BATCH_ORCHESTRATE_MAX + 50):
            _make_application(customer_user)

        response, mock_delay, cap = self._post(admin_user)

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["queued"] == cap
        assert body["skipped"] == 50
        assert "50 more pending" in body["detail"]
        assert mock_delay.call_count == cap

    def test_default_path_no_overflow_keeps_response_shape_unchanged(self, admin_user, customer_user):
        for _ in range(30):
            _make_application(customer_user)

        response, mock_delay, _ = self._post(admin_user)

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["queued"] == 30
        assert "skipped" not in body
        assert "detail" not in body
        assert mock_delay.call_count == 30

    def test_recheck_path_caps_at_max(self, admin_user, customer_user):
        from apps.agents.views import BATCH_ORCHESTRATE_MAX

        for _ in range(BATCH_ORCHESTRATE_MAX + 50):
            _make_application(customer_user, status_value=LoanApplication.Status.REVIEW)

        response, mock_delay, cap = self._post(admin_user, query="recheck=true")

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["queued"] == cap
        assert body["skipped"] == 50
        assert mock_delay.call_count == cap

    def test_oldest_first_ordering_on_default_path(self, admin_user, customer_user):
        from datetime import timedelta

        from django.utils import timezone

        first = _make_application(customer_user)
        LoanApplication.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=5))
        second = _make_application(customer_user)
        LoanApplication.objects.filter(pk=second.pk).update(created_at=timezone.now() - timedelta(days=3))
        third = _make_application(customer_user)

        response, mock_delay, _ = self._post(admin_user)

        assert response.status_code == status.HTTP_202_ACCEPTED
        dispatched_ids = [str(call.args[0]) for call in mock_delay.call_args_list]
        expected = [str(first.pk), str(second.pk), str(third.pk)]
        assert dispatched_ids == expected

    def test_audit_log_records_skipped_count(self, admin_user, customer_user):
        from apps.agents.views import BATCH_ORCHESTRATE_MAX

        for _ in range(BATCH_ORCHESTRATE_MAX + 7):
            _make_application(customer_user)

        response, _, _ = self._post(admin_user)

        assert response.status_code == status.HTTP_202_ACCEPTED
        audit = AuditLog.objects.filter(action="batch_pipeline_triggered", user=admin_user).latest("timestamp")
        assert audit.details["skipped_count"] == 7

    def test_audit_log_records_zero_skipped_on_happy_path(self, admin_user, customer_user):
        for _ in range(5):
            _make_application(customer_user)

        response, _, _ = self._post(admin_user)

        assert response.status_code == status.HTTP_202_ACCEPTED
        audit = AuditLog.objects.filter(action="batch_pipeline_triggered", user=admin_user).latest("timestamp")
        assert audit.details["skipped_count"] == 0

    def test_empty_queue_returns_unchanged_response(self, admin_user):
        response, mock_delay, _ = self._post(admin_user)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {
            "detail": "No pending applications to process.",
            "queued": 0,
        }
        assert mock_delay.call_count == 0
