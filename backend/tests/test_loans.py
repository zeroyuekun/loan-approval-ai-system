"""Tests for loan application CRUD and role-based permissions."""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import CustomerProfile, CustomUser
from apps.loans.models import LoanApplication


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    FIELD_ENCRYPTION_KEY="Q1bXXPr1cYO3Cjd7uP5J8nWRxzdBjQrTAosMayGV3CA=",
)
class LoanCRUDTestCase(TestCase):
    def setUp(self):
        cache.clear()
        # Clear the Fernet lru_cache so it picks up the test encryption key
        from apps.accounts.models import _get_fernet

        _get_fernet.cache_clear()
        self.customer = CustomUser.objects.create_user(
            username="customer1",
            password="TestPass123!",
            email="customer@example.com",
            role="customer",
        )
        # Complete the auto-created customer profile (required by LoanApplicationCreateSerializer)
        profile = self.customer.profile
        profile.date_of_birth = "1990-01-15"
        profile.phone = "0412345678"
        profile.address_line_1 = "123 Test St"
        profile.suburb = "Sydney"
        profile.state = "NSW"
        profile.postcode = "2000"
        profile.residency_status = "citizen"
        profile.primary_id_type = "drivers_licence"
        profile.primary_id_number = "DL12345678"
        profile.employment_status = "payg_permanent"
        profile.gross_annual_income = 85000
        profile.housing_situation = "renting"
        profile.number_of_dependants = 0
        profile.save()
        self.officer = CustomUser.objects.create_user(
            username="officer1",
            password="TestPass123!",
            email="officer@example.com",
            role="officer",
        )
        self.admin = CustomUser.objects.create_user(
            username="admin1",
            password="TestPass123!",
            email="admin@example.com",
            role="admin",
        )
        self.client = APIClient()
        self.loan_data = {
            "annual_income": "85000.00",
            "credit_score": 780,
            "loan_amount": "350000.00",
            "loan_term_months": 360,
            "debt_to_income": "4.12",
            "employment_length": 5,
            "purpose": "home",
            "home_ownership": "mortgage",
            "employment_type": "payg_permanent",
            "applicant_type": "single",
            "state": "NSW",
        }

    def _login(self, username, password="TestPass123!"):
        self.client.post(
            "/api/v1/auth/login/",
            {
                "username": username,
                "password": password,
            },
        )

    def test_customer_can_create_loan(self):
        self._login("customer1")
        response = self.client.post("/api/v1/loans/", self.loan_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["purpose"], "home")

    def test_customer_can_only_see_own_loans(self):
        self._login("customer1")
        self.client.post("/api/v1/loans/", self.loan_data)

        # Another customer should see no loans
        customer2 = CustomUser.objects.create_user(
            username="customer2",
            password="TestPass123!",
            email="c2@example.com",
            role="customer",
        )
        self._login("customer2")
        response = self.client.get("/api/v1/loans/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_officer_can_see_all_loans(self):
        # Create a loan as customer
        self._login("customer1")
        self.client.post("/api/v1/loans/", self.loan_data)

        # Officer should see it
        self._login("officer1")
        response = self.client.get("/api/v1/loans/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

    def test_unauthenticated_cannot_access_loans(self):
        client = APIClient()
        response = client.get("/api/v1/loans/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
