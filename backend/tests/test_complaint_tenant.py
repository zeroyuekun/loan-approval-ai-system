"""Tests for Finding 3 — ComplaintSerializer cross-tenant validation.

Closes the Codex adversarial review finding that any authenticated user
could file a Complaint tied to another user's loan_application because
ComplaintSerializer.create() overwrote `complainant` with request.user
but never validated ownership of the referenced loan.
"""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog, Complaint, LoanApplication

COMPLAINTS_URL = "/api/v1/loans/complaints/"


def _make_customer(username, email):
    return CustomUser.objects.create_user(
        username=username,
        email=email,
        password="testpass123",
        role="customer",
        first_name=username.title(),
        last_name="Tester",
    )


def _make_application(applicant):
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


@pytest.fixture
def customer_a(db):
    return _make_customer("customer_a", "a@test.com")


@pytest.fixture
def customer_b(db):
    return _make_customer("customer_b", "b@test.com")


@pytest.fixture
def loan_a(customer_a):
    return _make_application(customer_a)


@pytest.fixture
def loan_b(customer_b):
    return _make_application(customer_b)


def _payload(loan_application_id):
    return {
        "loan_application": str(loan_application_id) if loan_application_id else None,
        "category": "decision",
        "subject": "Concerned about outcome",
        "description": "Please re-review my file.",
    }


@pytest.mark.django_db
class TestComplaintTenantValidation:
    def test_customer_cannot_file_on_other_customers_loan(
        self, customer_a, loan_b
    ):
        client = APIClient()
        client.force_authenticate(user=customer_a)

        response = client.post(COMPLAINTS_URL, _payload(loan_b.id), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert "loan_application" in body
        assert "You can only file complaints on your own applications." in str(
            body["loan_application"]
        )
        assert Complaint.objects.count() == 0
        assert not AuditLog.objects.filter(action="complaint_filed").exists()

    def test_customer_can_file_on_own_loan(self, customer_a, loan_a):
        client = APIClient()
        client.force_authenticate(user=customer_a)

        response = client.post(COMPLAINTS_URL, _payload(loan_a.id), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert Complaint.objects.count() == 1
        audit = AuditLog.objects.get(action="complaint_filed")
        assert audit.user == customer_a
        assert audit.details["on_behalf_of_id"] is None
        assert audit.details["loan_application_id"] == str(loan_a.id)
        assert audit.details["category"] == "decision"

    def test_officer_can_file_on_any_customer_loan(
        self, officer_user, customer_b, loan_b
    ):
        client = APIClient()
        client.force_authenticate(user=officer_user)

        response = client.post(COMPLAINTS_URL, _payload(loan_b.id), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert Complaint.objects.count() == 1
        audit = AuditLog.objects.get(action="complaint_filed")
        assert audit.user == officer_user
        assert audit.details["on_behalf_of_id"] == customer_b.id

    def test_admin_can_file_on_any_customer_loan(
        self, admin_user, customer_b, loan_b
    ):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        response = client.post(COMPLAINTS_URL, _payload(loan_b.id), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        audit = AuditLog.objects.get(action="complaint_filed")
        assert audit.details["on_behalf_of_id"] == customer_b.id

    def test_complaint_without_loan_application_still_allowed(
        self, customer_a
    ):
        client = APIClient()
        client.force_authenticate(user=customer_a)

        response = client.post(COMPLAINTS_URL, _payload(None), format="json")

        assert response.status_code == status.HTTP_201_CREATED
        audit = AuditLog.objects.get(action="complaint_filed")
        assert audit.details["loan_application_id"] is None
        assert audit.details["on_behalf_of_id"] is None

    def test_nonexistent_loan_id_rejected(self, customer_a):
        import uuid

        client = APIClient()
        client.force_authenticate(user=customer_a)

        response = client.post(
            COMPLAINTS_URL, _payload(uuid.uuid4()), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
