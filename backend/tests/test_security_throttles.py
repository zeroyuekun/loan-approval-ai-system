"""Throttle coverage tests for v1.9.6 security sweep.

Verifies the new scoped throttles on sensitive endpoints:
- ComplaintFilingThrottle = 10/hour on ComplaintViewSet.create
- DataExportThrottle     = 10/hour on CustomerDataExportView

Both are user-scoped UserRateThrottle subclasses. The tests clear the
throttle cache first so prior tests don't poison the counter.
"""

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication

COMPLAINTS_URL = "/api/v1/loans/complaints/"
DATA_EXPORT_URL = "/api/v1/auth/me/data-export/"


def _make_customer(username="throttle_user"):
    return CustomUser.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="testpass123",
        role="customer",
        first_name=username.title(),
        last_name="User",
    )


def _make_loan(applicant):
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
    )


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestComplaintFilingThrottle:
    def test_tenth_succeeds_eleventh_rate_limited(self, settings):
        user = _make_customer("complaint_spammer")
        loan = _make_loan(user)
        client = APIClient()
        client.force_authenticate(user=user)

        payload = {
            "loan_application": str(loan.id),
            "category": "decision",
            "subject": "Concern",
            "description": "Please re-review.",
        }

        for i in range(10):
            resp = client.post(COMPLAINTS_URL, payload, format="json")
            assert resp.status_code == 201, f"call {i+1} unexpectedly failed: {resp.status_code} {resp.content!r}"

        throttled = client.post(COMPLAINTS_URL, payload, format="json")
        assert throttled.status_code == 429
        assert "retry" in throttled.content.decode().lower() or "throttled" in throttled.content.decode().lower()

    def test_list_is_not_throttled_by_filing_scope(self):
        """GET /complaints/ uses default user scope (60/min), not the 10/hour filing cap."""
        user = _make_customer("complaint_reader")
        loan = _make_loan(user)
        client = APIClient()
        client.force_authenticate(user=user)

        for _ in range(10):
            client.post(COMPLAINTS_URL, {
                "loan_application": str(loan.id),
                "category": "decision",
                "subject": "x",
                "description": "y",
            }, format="json")

        resp = client.get(COMPLAINTS_URL)
        assert resp.status_code == 200, "list should remain accessible after filing cap is hit"


@pytest.mark.django_db
class TestDataExportThrottle:
    def test_tenth_succeeds_eleventh_rate_limited(self):
        user = _make_customer("export_spammer")
        client = APIClient()
        client.force_authenticate(user=user)

        for i in range(10):
            resp = client.get(DATA_EXPORT_URL)
            assert resp.status_code == 200, f"call {i+1} unexpectedly failed: {resp.status_code} {resp.content!r}"

        throttled = client.get(DATA_EXPORT_URL)
        assert throttled.status_code == 429
