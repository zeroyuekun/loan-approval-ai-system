import pytest
from decimal import Decimal

from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication


@pytest.fixture
def api_client():
    """Return an unauthenticated API client."""
    return APIClient()


@pytest.fixture
def admin_user(db):
    """Create and return an admin user."""
    user = CustomUser.objects.create_user(
        username='admin_test',
        email='admin@test.com',
        password='testpass123',
        role='admin',
        first_name='Admin',
        last_name='User',
    )
    return user


@pytest.fixture
def officer_user(db):
    """Create and return a loan officer user."""
    user = CustomUser.objects.create_user(
        username='officer_test',
        email='officer@test.com',
        password='testpass123',
        role='officer',
        first_name='Officer',
        last_name='User',
    )
    return user


@pytest.fixture
def customer_user(db):
    """Create and return a customer user."""
    user = CustomUser.objects.create_user(
        username='customer_test',
        email='customer@test.com',
        password='testpass123',
        role='customer',
        first_name='Customer',
        last_name='User',
    )
    return user


@pytest.fixture
def sample_application(db, customer_user):
    """Create and return a sample loan application."""
    return LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=Decimal('75000.00'),
        credit_score=720,
        loan_amount=Decimal('25000.00'),
        loan_term_months=36,
        debt_to_income=Decimal('0.2800'),
        employment_length=5,
        purpose='personal',
        home_ownership='rent',
        has_cosigner=False,
    )
