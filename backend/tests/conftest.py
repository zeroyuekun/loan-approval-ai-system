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
        debt_to_income=Decimal('1.50'),
        employment_length=5,
        purpose='personal',
        home_ownership='rent',
        has_cosigner=False,
        monthly_expenses=Decimal('2200.00'),
        existing_credit_card_limit=Decimal('8000.00'),
        number_of_dependants=0,
        employment_type='payg_permanent',
        applicant_type='single',
        has_hecs=False,
        has_bankruptcy=False,
    )


@pytest.fixture
def home_loan_application(db, customer_user):
    """Home loan: couple, PAYG permanent, with HECS, property + deposit."""
    return LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=Decimal('140000.00'),
        credit_score=780,
        loan_amount=Decimal('550000.00'),
        loan_term_months=360,
        debt_to_income=Decimal('4.20'),
        employment_length=8,
        purpose='home',
        home_ownership='rent',
        has_cosigner=False,
        property_value=Decimal('700000.00'),
        deposit_amount=Decimal('150000.00'),
        monthly_expenses=Decimal('3200.00'),
        existing_credit_card_limit=Decimal('12000.00'),
        number_of_dependants=1,
        employment_type='payg_permanent',
        applicant_type='couple',
        has_hecs=True,
        has_bankruptcy=False,
    )


@pytest.fixture
def borderline_application(db, customer_user):
    """Borderline case: self-employed, high DTI, moderate credit."""
    return LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=Decimal('85000.00'),
        credit_score=690,
        loan_amount=Decimal('35000.00'),
        loan_term_months=60,
        debt_to_income=Decimal('3.80'),
        employment_length=3,
        purpose='business',
        home_ownership='mortgage',
        has_cosigner=False,
        monthly_expenses=Decimal('2800.00'),
        existing_credit_card_limit=Decimal('15000.00'),
        number_of_dependants=2,
        employment_type='self_employed',
        applicant_type='single',
        has_hecs=False,
        has_bankruptcy=False,
    )


@pytest.fixture
def denied_application(db, customer_user):
    """High-risk: casual, high DTI, low credit, bankruptcy history."""
    return LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=Decimal('48000.00'),
        credit_score=580,
        loan_amount=Decimal('20000.00'),
        loan_term_months=36,
        debt_to_income=Decimal('5.50'),
        employment_length=1,
        purpose='personal',
        home_ownership='rent',
        has_cosigner=False,
        monthly_expenses=Decimal('2600.00'),
        existing_credit_card_limit=Decimal('5000.00'),
        number_of_dependants=3,
        employment_type='payg_casual',
        applicant_type='single',
        has_hecs=True,
        has_bankruptcy=True,
    )
