"""Tests for the security/resilience fixes in fix/audit-critical-issues.

Covers:
- Token refresh returns 401 (not 500) when the token's user has been deleted
- ApiBudgetGuard raises BudgetExhausted (not fail-open) after N consecutive
  Redis failures within a single process
"""

from unittest.mock import patch

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


class ApiBudgetRedisFailClosedTests(TestCase):
    """Regression: previously failed open on Redis errors, allowing unbounded
    API spend during Redis outages."""

    def _guard(self):
        from apps.agents.services import api_budget

        # Reset the process-local counter between tests
        api_budget._REDIS_FALLBACK_CALLS = 0
        return api_budget.ApiBudgetGuard()

    def test_brief_redis_blip_still_allows_calls(self):
        """Less than fallback limit of Redis failures should not raise."""
        from apps.agents.services import api_budget

        guard = self._guard()
        with patch.object(guard, "_get_redis", side_effect=ConnectionError("redis down")):
            for _ in range(api_budget._REDIS_FALLBACK_LIMIT):
                guard.check_budget()  # must not raise

    def test_sustained_redis_outage_raises_budget_exhausted(self):
        """After the fallback limit, check_budget must fail closed."""
        from apps.agents.services import api_budget
        from apps.agents.services.api_budget import BudgetExhausted

        guard = self._guard()
        with patch.object(guard, "_get_redis", side_effect=ConnectionError("redis down")):
            # Consume the fallback budget
            for _ in range(api_budget._REDIS_FALLBACK_LIMIT):
                guard.check_budget()
            # Next call must raise — this is the behaviour change
            with self.assertRaises(BudgetExhausted):
                guard.check_budget()
