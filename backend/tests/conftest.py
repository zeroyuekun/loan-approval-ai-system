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
        state='NSW',
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
        state='VIC',
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
        state='VIC',
    )


@pytest.fixture
def denied_application(db, customer_user):
    """Denied: casual worker, under 12 months tenure (single disqualifier)."""
    return LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=Decimal('52000.00'),
        credit_score=710,
        loan_amount=Decimal('20000.00'),
        loan_term_months=36,
        debt_to_income=Decimal('2.40'),
        employment_length=0,
        purpose='personal',
        home_ownership='rent',
        has_cosigner=False,
        monthly_expenses=Decimal('1800.00'),
        existing_credit_card_limit=Decimal('3000.00'),
        number_of_dependants=0,
        employment_type='payg_casual',
        applicant_type='single',
        has_hecs=True,
        has_bankruptcy=False,
        state='QLD',
    )


@pytest.fixture
def approved_home_loan(db, customer_user):
    """Approved home loan for stress testing."""
    return LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=Decimal('120000.00'),
        credit_score=800,
        loan_amount=Decimal('480000.00'),
        loan_term_months=360,
        debt_to_income=Decimal('4.00'),
        employment_length=10,
        purpose='home',
        home_ownership='mortgage',
        has_cosigner=False,
        property_value=Decimal('600000.00'),
        deposit_amount=Decimal('120000.00'),
        monthly_expenses=Decimal('3500.00'),
        existing_credit_card_limit=Decimal('10000.00'),
        number_of_dependants=1,
        employment_type='payg_permanent',
        applicant_type='couple',
        has_hecs=False,
        has_bankruptcy=False,
        state='NSW',
        status='approved',
    )


@pytest.fixture
def application_no_profile(db):
    """Customer without CustomerProfile for graceful degradation tests."""
    user = CustomUser.objects.create_user(
        username='noprofile_customer',
        email='noprofile@example.com',
        password='testpass123',
        role='customer',
        first_name='No',
        last_name='Profile',
    )
    # No CustomerProfile created for this user
    application = LoanApplication.objects.create(
        applicant=user,
        annual_income=75000,
        credit_score=700,
        loan_amount=20000,
        loan_term_months=36,
        purpose='personal',
        employment_type='payg_permanent',
        employment_length=5,
        debt_to_income=0.3,
        existing_credit_card_limit=5000,
        home_ownership='rent',
        applicant_type='single',
        number_of_dependants=0,
    )
    return application


@pytest.fixture
def escalated_agent_run(sample_application, db):
    """Pre-built escalated AgentRun for resume_after_review tests."""
    from apps.agents.models import AgentRun
    from apps.loans.models import LoanDecision

    sample_application.status = 'review'
    sample_application.save()

    run = AgentRun.objects.create(
        application=sample_application,
        status='escalated',
        steps=[{'step_name': 'bias_check', 'status': 'completed'}],
    )

    LoanDecision.objects.create(
        application=sample_application,
        decision='approved',
        confidence=0.85,
        model_version='test-v1',
    )

    return run


# ---------------------------------------------------------------------------
# Celery integration fixtures (for tests that go through real Redis broker)
# ---------------------------------------------------------------------------

def _redis_available():
    """Check if Redis broker is reachable."""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


skip_without_redis = pytest.mark.skipif(
    not _redis_available(),
    reason='Redis not available (tests run in Docker/CI)',
)


@pytest.fixture(scope='session')
def celery_config():
    """Configure Celery for integration testing."""
    return {
        'broker_url': 'redis://localhost:6379/0',
        'result_backend': 'redis://localhost:6379/0',
        'task_always_eager': False,
        'task_eager_propagates': False,
    }
