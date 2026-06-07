"""Local fixtures for email_engine reliability tests.

The shared fixtures in backend/tests/conftest.py are only visible to tests
under tests/. Re-expose the application factory here so apps/email_engine/tests
can build a realistic LoanApplication without duplicating the field list.
"""

from decimal import Decimal

import pytest

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication


@pytest.fixture
def email_customer_user(db):
    return CustomUser.objects.create_user(
        username="email_customer_test",
        email="email_customer@test.com",
        password="testpass123",
        role="customer",
        first_name="Email",
        last_name="Customer",
    )


@pytest.fixture
def sample_application(db, email_customer_user):
    """A sample loan application for email reliability tests."""
    return LoanApplication.objects.create(
        applicant=email_customer_user,
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
