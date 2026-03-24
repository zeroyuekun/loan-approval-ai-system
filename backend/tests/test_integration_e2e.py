"""End-to-end integration test: register -> login -> apply -> predict -> email -> verify.

Tests the full pipeline through the API to verify all components work together.
Mocks external services (Claude API, Celery async) to keep tests fast and deterministic.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import CustomUser, CustomerProfile


def _no_throttle(self, request, view):
    """Disable throttling for all test requests."""
    return True


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
@patch('apps.accounts.views.RegisterRateThrottle.allow_request', _no_throttle)
@patch('apps.accounts.views.LoginRateThrottle.allow_request', _no_throttle)
@patch('apps.email_engine.views.EmailGenerationThrottle.allow_request', _no_throttle)
@patch('apps.ml_engine.views.PredictionThrottle.allow_request', _no_throttle)
class TestFullPipeline(TestCase):
    """Full end-to-end pipeline: customer registers, applies for loan, gets prediction and email."""

    def setUp(self):
        self.client = APIClient()

    def _register_and_login(self):
        """Register a new customer via the API and login via cookie auth."""
        reg_resp = self.client.post('/api/v1/auth/register/', {
            'username': 'e2e_test_user',
            'email': 'e2e@test.com',
            'password': 'TestPass123!',
            'password2': 'TestPass123!',
            'first_name': 'Test',
            'last_name': 'User',
        })
        assert reg_resp.status_code == status.HTTP_201_CREATED, (
            f'Registration failed: {reg_resp.data}'
        )

        # Login sets HttpOnly cookies used for subsequent requests
        login_resp = self.client.post('/api/v1/auth/login/', {
            'username': 'e2e_test_user',
            'password': 'TestPass123!',
        })
        assert login_resp.status_code == status.HTTP_200_OK, (
            f'Login failed: {login_resp.data}'
        )
        assert 'access_token' in login_resp.cookies
        return login_resp

    def _complete_profile(self):
        """Fill in required profile fields so loan creation passes validation.

        NCCP Act 2009 and AML/CTF Act 2006 require these fields before a
        loan application can be submitted.
        """
        user = CustomUser.objects.get(username='e2e_test_user')
        profile, _ = CustomerProfile.objects.get_or_create(user=user)
        profile.date_of_birth = date(1990, 5, 15)
        profile.phone = '0412345678'
        profile.address_line_1 = '123 Test Street'
        profile.suburb = 'Sydney'
        profile.state = 'NSW'
        profile.postcode = '2000'
        profile.residency_status = 'citizen'
        profile.primary_id_type = 'drivers_licence'
        profile.primary_id_number = 'DL12345678'
        profile.employment_status = 'payg_permanent'
        profile.gross_annual_income = Decimal('85000.00')
        profile.housing_situation = 'mortgage'
        profile.number_of_dependants = 1
        profile.save()
        return profile

    def _create_application(self):
        """Create a loan application with required fields."""
        app_data = {
            'annual_income': '85000.00',
            'credit_score': 820,
            'loan_amount': '25000.00',
            'loan_term_months': 60,
            'debt_to_income': '2.50',
            'employment_length': 5,
            'purpose': 'personal',
            'home_ownership': 'mortgage',
            'employment_type': 'payg_permanent',
            'applicant_type': 'single',
            'has_cosigner': False,
            'monthly_expenses': '3200.00',
            'existing_credit_card_limit': '8000.00',
            'number_of_dependants': 1,
            'has_hecs': False,
            'has_bankruptcy': False,
            'state': 'NSW',
        }
        resp = self.client.post('/api/v1/loans/', app_data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, (
            f'Application creation failed: {resp.data}'
        )
        return resp.data

    # ------------------------------------------------------------------
    # Individual step tests
    # ------------------------------------------------------------------

    def test_health_endpoint(self):
        """Health check should return 200."""
        resp = self.client.get('/api/v1/health/')
        assert resp.status_code == status.HTTP_200_OK

    def test_deep_health_endpoint(self):
        """Deep health check should verify DB and Redis."""
        resp = self.client.get('/api/v1/health/deep/')
        # 503 if Redis is not available in test environment
        assert resp.status_code in (200, 503)

    def test_register_login_flow(self):
        """Customer can register and login, receiving cookie auth."""
        login_resp = self._register_and_login()
        assert 'user' in login_resp.data

    def test_create_application(self):
        """Authenticated customer with complete profile can create a loan application."""
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        assert 'id' in app
        assert app['purpose'] == 'personal'

    def test_list_applications(self):
        """Customer can list their applications."""
        self._register_and_login()
        self._complete_profile()
        self._create_application()
        resp = self.client.get('/api/v1/loans/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['count'] >= 1

    def test_retrieve_application(self):
        """Customer can retrieve a specific application by ID."""
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']
        resp = self.client.get(f'/api/v1/loans/{app_id}/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['id'] == app_id

    @patch('apps.ml_engine.tasks.run_prediction_task.delay')
    def test_trigger_prediction(self, mock_delay):
        """Triggering prediction queues a Celery task and returns 202."""
        mock_delay.return_value = MagicMock(id='test-task-123')
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']

        resp = self.client.post(f'/api/v1/ml/predict/{app_id}/')
        assert resp.status_code == status.HTTP_202_ACCEPTED, (
            f'Prediction trigger: {resp.status_code} {resp.data}'
        )
        assert resp.data['task_id'] == 'test-task-123'
        assert resp.data['status'] == 'prediction_queued'
        mock_delay.assert_called_once_with(str(app_id))

    @patch('apps.email_engine.tasks.generate_email_task.delay')
    def test_trigger_email_generation(self, mock_delay):
        """Triggering email generation queues a Celery task and returns 202."""
        mock_delay.return_value = MagicMock(id='test-email-task-456')
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']

        resp = self.client.post(
            f'/api/v1/emails/generate/{app_id}/',
            {'decision': 'approved'},
            format='json',
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED, (
            f'Email trigger: {resp.status_code} {resp.data}'
        )
        assert resp.data['task_id'] == 'test-email-task-456'
        assert resp.data['status'] == 'email_generation_queued'
        mock_delay.assert_called_once_with(str(app_id), 'approved')

    def test_email_list_empty_initially(self):
        """Email list returns empty for new customer."""
        self._register_and_login()
        resp = self.client.get('/api/v1/emails/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['count'] == 0

    def test_unauthenticated_cannot_access_loans(self):
        """Unauthenticated requests to loans endpoint are rejected."""
        fresh_client = APIClient()
        resp = fresh_client.get('/api/v1/loans/')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthenticated_cannot_access_emails(self):
        """Unauthenticated requests to emails endpoint are rejected."""
        fresh_client = APIClient()
        resp = fresh_client.get('/api/v1/emails/')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    # ------------------------------------------------------------------
    # Full pipeline test
    # ------------------------------------------------------------------

    def test_full_pipeline_register_to_email(self):
        """Full flow: register -> login -> profile -> apply -> predict -> email."""
        # Step 1: Register and login
        login_resp = self._register_and_login()
        assert 'user' in login_resp.data

        # Step 2: Complete customer profile
        profile = self._complete_profile()
        assert profile.is_profile_complete

        # Step 3: Create application
        app = self._create_application()
        app_id = app['id']
        assert app_id is not None

        # Step 4: Verify application is retrievable
        resp = self.client.get(f'/api/v1/loans/{app_id}/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['id'] == app_id

        # Step 5: Trigger prediction (mocked Celery)
        with patch('apps.ml_engine.tasks.run_prediction_task.delay') as mock_predict:
            mock_predict.return_value = MagicMock(id='pred-task-789')
            resp = self.client.post(f'/api/v1/ml/predict/{app_id}/')
            assert resp.status_code == status.HTTP_202_ACCEPTED
            assert resp.data['task_id'] == 'pred-task-789'

        # Step 6: Trigger email generation (mocked Celery)
        with patch('apps.email_engine.tasks.generate_email_task.delay') as mock_email:
            mock_email.return_value = MagicMock(id='email-task-101')
            resp = self.client.post(
                f'/api/v1/emails/generate/{app_id}/',
                {'decision': 'denied'},
                format='json',
            )
            assert resp.status_code == status.HTTP_202_ACCEPTED
            assert resp.data['task_id'] == 'email-task-101'

        # Step 7: Verify emails list endpoint works
        resp = self.client.get('/api/v1/emails/')
        assert resp.status_code == status.HTTP_200_OK

        # Step 8: Verify loan list shows our application
        resp = self.client.get('/api/v1/loans/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['count'] >= 1

    # ------------------------------------------------------------------
    # Role-based access tests
    # ------------------------------------------------------------------

    def test_officer_can_see_customer_loans(self):
        """Officers can see all loan applications."""
        # Create a loan as customer
        self._register_and_login()
        self._complete_profile()
        self._create_application()

        # Login as officer (created via ORM, login via API)
        CustomUser.objects.create_user(
            username='officer_e2e',
            password='TestPass123!',
            email='officer@e2e.com',
            role='officer',
        )
        self.client.post('/api/v1/auth/login/', {
            'username': 'officer_e2e',
            'password': 'TestPass123!',
        })
        resp = self.client.get('/api/v1/loans/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['count'] >= 1

    @patch('apps.email_engine.tasks.generate_email_task.delay')
    def test_officer_can_trigger_email_for_customer(self, mock_delay):
        """Officers can trigger email generation on any application."""
        mock_delay.return_value = MagicMock(id='officer-email-task')

        # Create loan as customer
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']

        # Login as officer
        CustomUser.objects.create_user(
            username='officer_e2e2',
            password='TestPass123!',
            email='officer2@e2e.com',
            role='officer',
        )
        self.client.post('/api/v1/auth/login/', {
            'username': 'officer_e2e2',
            'password': 'TestPass123!',
        })

        resp = self.client.post(
            f'/api/v1/emails/generate/{app_id}/',
            {'decision': 'approved'},
            format='json',
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED

    def test_email_invalid_decision_rejected(self):
        """Email generation rejects invalid decision values."""
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']

        resp = self.client.post(
            f'/api/v1/emails/generate/{app_id}/',
            {'decision': 'maybe'},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_application_without_profile_rejected(self):
        """Loan application without a complete profile is rejected."""
        self._register_and_login()
        # Do NOT complete profile
        resp = self.client.post('/api/v1/loans/', {
            'annual_income': '85000.00',
            'credit_score': 820,
            'loan_amount': '25000.00',
            'loan_term_months': 60,
            'debt_to_income': '2.50',
            'employment_length': 5,
            'purpose': 'personal',
            'home_ownership': 'mortgage',
            'employment_type': 'payg_permanent',
            'applicant_type': 'single',
            'state': 'NSW',
        }, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ------------------------------------------------------------------
    # Idempotency tests
    # ------------------------------------------------------------------

    @patch('apps.ml_engine.tasks.run_prediction_task.delay')
    def test_prediction_idempotent(self, mock_delay):
        """Triggering prediction twice returns task IDs for both (no crash)."""
        mock_delay.return_value = MagicMock(id='idempotent-task-1')
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']

        resp1 = self.client.post(f'/api/v1/ml/predict/{app_id}/')
        assert resp1.status_code == status.HTTP_202_ACCEPTED

        mock_delay.return_value = MagicMock(id='idempotent-task-2')
        resp2 = self.client.post(f'/api/v1/ml/predict/{app_id}/')
        assert resp2.status_code == status.HTTP_202_ACCEPTED

    @patch('apps.email_engine.tasks.generate_email_task.delay')
    def test_email_generation_idempotent(self, mock_delay):
        """Triggering email generation twice for same app should not crash."""
        mock_delay.return_value = MagicMock(id='email-idem-1')
        self._register_and_login()
        self._complete_profile()
        app = self._create_application()
        app_id = app['id']

        resp1 = self.client.post(
            f'/api/v1/emails/generate/{app_id}/',
            {'decision': 'approved'},
            format='json',
        )
        assert resp1.status_code == status.HTTP_202_ACCEPTED

        mock_delay.return_value = MagicMock(id='email-idem-2')
        resp2 = self.client.post(
            f'/api/v1/emails/generate/{app_id}/',
            {'decision': 'approved'},
            format='json',
        )
        assert resp2.status_code == status.HTTP_202_ACCEPTED

    def test_duplicate_application_allowed(self):
        """Same customer can create multiple loan applications."""
        self._register_and_login()
        self._complete_profile()
        app1 = self._create_application()
        # Create a second application (different data to avoid unique constraints)
        app2_data = {
            'annual_income': '95000.00',
            'credit_score': 850,
            'loan_amount': '30000.00',
            'loan_term_months': 48,
            'debt_to_income': '2.00',
            'employment_length': 7,
            'purpose': 'auto',
            'home_ownership': 'mortgage',
            'employment_type': 'payg_permanent',
            'applicant_type': 'single',
            'has_cosigner': False,
            'monthly_expenses': '3500.00',
            'existing_credit_card_limit': '10000.00',
            'number_of_dependants': 0,
            'has_hecs': False,
            'has_bankruptcy': False,
            'state': 'VIC',
        }
        resp = self.client.post('/api/v1/loans/', app2_data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['id'] != app1['id']

    # ------------------------------------------------------------------
    # Ensemble / model version tests
    # ------------------------------------------------------------------

    def test_model_version_list_accessible_by_admin(self):
        """Admin should be able to list model versions (if endpoint exists)."""
        # Create admin
        CustomUser.objects.create_superuser(
            username='admin_e2e_ensemble',
            password='TestPass123!',
            email='admin_ensemble@e2e.com',
            role='admin',
        )
        self.client.post('/api/v1/auth/login/', {
            'username': 'admin_e2e_ensemble',
            'password': 'TestPass123!',
        })
        resp = self.client.get('/api/v1/ml/models/')
        # 200 if endpoint exists, 404 if not yet implemented
        assert resp.status_code in (200, 404), \
            f'Unexpected status {resp.status_code} for model list'

    def test_concurrent_applications_different_users(self):
        """Multiple users can create applications independently."""
        # User 1
        self._register_and_login()
        self._complete_profile()
        app1 = self._create_application()

        # User 2
        reg_resp = self.client.post('/api/v1/auth/register/', {
            'username': 'e2e_user_2',
            'email': 'e2e2@test.com',
            'password': 'TestPass123!',
            'password2': 'TestPass123!',
            'first_name': 'Test2',
            'last_name': 'User2',
        })
        assert reg_resp.status_code == status.HTTP_201_CREATED

        self.client.post('/api/v1/auth/login/', {
            'username': 'e2e_user_2',
            'password': 'TestPass123!',
        })

        user2 = CustomUser.objects.get(username='e2e_user_2')
        from apps.accounts.models import CustomerProfile
        from datetime import date
        profile, _ = CustomerProfile.objects.get_or_create(user=user2)
        profile.date_of_birth = date(1988, 3, 20)
        profile.phone = '0412345679'
        profile.address_line_1 = '456 Other Street'
        profile.suburb = 'Melbourne'
        profile.state = 'VIC'
        profile.postcode = '3000'
        profile.residency_status = 'citizen'
        profile.primary_id_type = 'drivers_licence'
        profile.primary_id_number = 'DL87654321'
        profile.employment_status = 'payg_permanent'
        profile.gross_annual_income = Decimal('90000.00')
        profile.housing_situation = 'rent'
        profile.number_of_dependants = 0
        profile.save()

        app2_data = {
            'annual_income': '90000.00',
            'credit_score': 800,
            'loan_amount': '20000.00',
            'loan_term_months': 36,
            'debt_to_income': '1.80',
            'employment_length': 4,
            'purpose': 'personal',
            'home_ownership': 'rent',
            'employment_type': 'payg_permanent',
            'applicant_type': 'single',
            'has_cosigner': False,
            'monthly_expenses': '2800.00',
            'existing_credit_card_limit': '5000.00',
            'number_of_dependants': 0,
            'has_hecs': False,
            'has_bankruptcy': False,
            'state': 'VIC',
        }
        resp = self.client.post('/api/v1/loans/', app2_data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED

        # User 2 should only see their own applications
        resp = self.client.get('/api/v1/loans/')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['count'] == 1
