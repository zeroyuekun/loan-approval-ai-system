"""Tests for the security/resilience fixes in fix/audit-critical-issues.

Covers:
- Token refresh returns 401 (not 500) when the token's user has been deleted

The ApiBudgetGuard fail-closed behaviour is tested alongside the other
budget-guard scenarios in test_api_budget.py.
"""

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class DeletedUserTokenRefreshTests(TestCase):
    """Regression: previously crashed with 500 on a valid token whose user
    was deleted after issuance."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = CustomUser.objects.create_user(
            username="refreshee",
            password="TestPass123!",
            email="refreshee@example.com",
        )

    def _login(self):
        resp = self.client.post(
            "/api/v1/auth/login/",
            {"username": "refreshee", "password": "TestPass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return resp

    def test_refresh_with_deleted_user_returns_401_not_500(self):
        self._login()
        # Delete the user AFTER the token was issued — simulates the race
        self.user.delete()

        resp = self.client.post("/api/v1/auth/refresh/")

        # Previously returned 500 due to unhandled User.DoesNotExist.
        # Now the view re-raises as TokenError and returns 401.
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
