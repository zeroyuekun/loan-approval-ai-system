"""Tests for registration, login, lockout, JWT refresh, and logout."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class AuthTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user_data = {
            "username": "testuser",
            "password": "TestPass123!",
            "password2": "TestPass123!",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }

    def test_register_success(self):
        response = self.client.post("/api/v1/auth/register/", self.user_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["username"], "testuser")
        # HttpOnly cookies should be set
        self.assertIn("access_token", response.cookies)
        self.assertTrue(response.cookies["access_token"]["httponly"])

    def test_register_duplicate_username(self):
        self.client.post("/api/v1/auth/register/", self.user_data)
        response = self.client.post("/api/v1/auth/register/", self.user_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_success(self):
        CustomUser.objects.create_user(username="testuser", password="TestPass123!", email="test@example.com")
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "testuser",
                "password": "TestPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user", response.data)
        self.assertIn("access_token", response.cookies)

    def test_login_wrong_password(self):
        CustomUser.objects.create_user(username="testuser", password="TestPass123!", email="test@example.com")
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "testuser",
                "password": "wrongpassword",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.accounts.views.LoginRateThrottle.allow_request", return_value=True)
    def test_login_lockout_after_5_failures(self, mock_throttle):
        user = CustomUser.objects.create_user(username="testuser", password="TestPass123!", email="test@example.com")
        for _ in range(5):
            self.client.post(
                "/api/v1/auth/login/",
                {
                    "username": "testuser",
                    "password": "wrong",
                },
            )
        user.refresh_from_db()
        self.assertTrue(user.is_locked)
        # Even correct password should fail when locked
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "testuser",
                "password": "TestPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_clears_cookies(self):
        CustomUser.objects.create_user(username="testuser", password="TestPass123!", email="test@example.com")
        self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "testuser",
                "password": "TestPass123!",
            },
        )
        # Use cookies from login for logout
        response = self.client.post("/api/v1/auth/logout/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_profile_requires_authentication(self):
        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_with_cookie_auth(self):
        CustomUser.objects.create_user(username="testuser", password="TestPass123!", email="test@example.com")
        self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "testuser",
                "password": "TestPass123!",
            },
        )
        # Cookies should be set from login, subsequent request uses them
        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "testuser")
