"""Tests for loan application CRUD and role-based permissions."""

from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class LoanCRUDTestCase(TestCase):
    def setUp(self):
        self.customer = CustomUser.objects.create_user(
            username='customer1', password='TestPass123!',
            email='customer@example.com', role='customer',
        )
        self.officer = CustomUser.objects.create_user(
            username='officer1', password='TestPass123!',
            email='officer@example.com', role='officer',
        )
        self.admin = CustomUser.objects.create_user(
            username='admin1', password='TestPass123!',
            email='admin@example.com', role='admin',
        )
        self.client = APIClient()
        self.loan_data = {
            'annual_income': '85000.00',
            'credit_score': 780,
            'loan_amount': '350000.00',
            'loan_term_months': 360,
            'debt_to_income': '4.12',
            'employment_length': 5,
            'purpose': 'home',
            'home_ownership': 'mortgage',
            'employment_type': 'payg_permanent',
            'applicant_type': 'single',
            'state': 'NSW',
        }

    def _login(self, username, password='TestPass123!'):
        self.client.post('/api/v1/auth/login/', {
            'username': username, 'password': password,
        })

    def test_customer_can_create_loan(self):
        self._login('customer1')
        response = self.client.post('/api/v1/loans/', self.loan_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['purpose'], 'home')

    def test_customer_can_only_see_own_loans(self):
        self._login('customer1')
        self.client.post('/api/v1/loans/', self.loan_data)

        # Another customer should see no loans
        customer2 = CustomUser.objects.create_user(
            username='customer2', password='TestPass123!',
            email='c2@example.com', role='customer',
        )
        self._login('customer2')
        response = self.client.get('/api/v1/loans/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_officer_can_see_all_loans(self):
        # Create a loan as customer
        self._login('customer1')
        self.client.post('/api/v1/loans/', self.loan_data)

        # Officer should see it
        self._login('officer1')
        response = self.client.get('/api/v1/loans/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['count'], 1)

    def test_unauthenticated_cannot_access_loans(self):
        client = APIClient()
        response = client.get('/api/v1/loans/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
