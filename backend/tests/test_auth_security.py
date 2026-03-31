"""Security tests for authentication: CSRF rotation, token blacklisting, cookie flags,
failed login tracking, and account lockout.

Uses pytest + Django test client with cookie-based JWT auth.
"""

import pytest
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser


def _redis_available():
    try:
        import redis

        r = redis.Redis(host="localhost", port=6379, db=1, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


skip_without_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not available (tests run in Docker/CI)",
)


def _no_throttle(self, request, view):
    """Disable throttling for all test requests."""
    return True


LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/refresh/"
CSRF_URL = "/api/v1/auth/csrf/"

PASSWORD = "testpass123"


@pytest.fixture
def auth_client():
    return APIClient()


@pytest.fixture
def login_user(db):
    """Create a user specifically for login tests."""
    return CustomUser.objects.create_user(
        username="security_test_user",
        email="security@test.com",
        password=PASSWORD,
        role="customer",
        first_name="Security",
        last_name="Tester",
    )


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestCSRFTokenRotation:
    """Verify that CSRF token is rotated on login to prevent session fixation."""

    def test_csrf_token_changes_on_login(self, auth_client, login_user):
        """CSRF token in response cookies should differ from the pre-login token."""
        # Step 1: Get initial CSRF token by hitting any GET endpoint
        # The ensure_csrf_cookie decorator or get_csrf_token call sets csrftoken cookie
        initial_resp = auth_client.get("/api/v1/health/")
        initial_csrf = auth_client.cookies.get("csrftoken")

        # Step 2: Login
        login_resp = auth_client.post(
            LOGIN_URL,
            {
                "username": login_user.username,
                "password": PASSWORD,
            },
        )
        assert login_resp.status_code == status.HTTP_200_OK

        # Step 3: Verify CSRF token changed
        post_login_csrf = login_resp.cookies.get("csrftoken")
        # After rotate_token + get_csrf_token, a new csrftoken cookie should be set
        assert post_login_csrf is not None, "CSRF cookie should be set after login"
        # The token value should be different from the initial one (rotation)
        if initial_csrf:
            assert post_login_csrf.value != initial_csrf.value, (
                "CSRF token must rotate on login to prevent session fixation"
            )


@skip_without_redis
@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestRefreshTokenBlacklisting:
    """Verify that old refresh tokens are blacklisted after rotation."""

    def test_old_refresh_token_rejected_after_rotation(self, auth_client, login_user):
        """After using a refresh token, the old one should be blacklisted."""
        # Step 1: Login to get tokens
        login_resp = auth_client.post(
            LOGIN_URL,
            {
                "username": login_user.username,
                "password": PASSWORD,
            },
        )
        assert login_resp.status_code == status.HTTP_200_OK
        old_refresh = auth_client.cookies.get("refresh_token")
        assert old_refresh is not None, "refresh_token cookie should be set after login"
        old_refresh_value = old_refresh.value

        # Step 2: Use refresh endpoint to rotate tokens
        refresh_resp = auth_client.post(REFRESH_URL)
        assert refresh_resp.status_code == status.HTTP_200_OK

        # Step 3: Try reusing the OLD refresh token -- should fail
        # Create a fresh client with only the old refresh token
        stale_client = APIClient()
        stale_client.cookies["refresh_token"] = old_refresh_value
        reuse_resp = stale_client.post(REFRESH_URL)
        assert reuse_resp.status_code == status.HTTP_401_UNAUTHORIZED, (
            "Old refresh token should be blacklisted after rotation"
        )


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestHttpOnlyCookies:
    """Verify that JWT cookies are set with the httponly flag."""

    def test_login_sets_httponly_cookies(self, auth_client, login_user):
        """access_token and refresh_token cookies must have httponly=True."""
        login_resp = auth_client.post(
            LOGIN_URL,
            {
                "username": login_user.username,
                "password": PASSWORD,
            },
        )
        assert login_resp.status_code == status.HTTP_200_OK

        access_cookie = login_resp.cookies.get("access_token")
        refresh_cookie = login_resp.cookies.get("refresh_token")

        assert access_cookie is not None, "access_token cookie must be present"
        assert refresh_cookie is not None, "refresh_token cookie must be present"

        # Django test client exposes cookie attributes via the Morsel object
        assert access_cookie["httponly"], "access_token must be HttpOnly"
        assert refresh_cookie["httponly"], "refresh_token must be HttpOnly"


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestFailedLoginTracking:
    """Verify that failed login attempts are tracked on the user model."""

    def test_failed_login_increments_counter(self, auth_client, login_user):
        """Three failed login attempts should set failed_login_attempts to 3."""
        for _ in range(3):
            resp = auth_client.post(
                LOGIN_URL,
                {
                    "username": login_user.username,
                    "password": "wrong_password",
                },
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 3, (
            f"Expected 3 failed attempts, got {login_user.failed_login_attempts}"
        )

    def test_successful_login_resets_counter(self, auth_client, login_user):
        """A successful login after failures should reset the counter to 0."""
        # Fail twice
        for _ in range(2):
            auth_client.post(
                LOGIN_URL,
                {
                    "username": login_user.username,
                    "password": "wrong_password",
                },
            )

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 2

        # Succeed
        resp = auth_client.post(
            LOGIN_URL,
            {
                "username": login_user.username,
                "password": PASSWORD,
            },
        )
        assert resp.status_code == status.HTTP_200_OK

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 0


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestAccountLockout:
    """Verify that accounts are locked after exceeding the failure threshold."""

    def test_lockout_after_five_failures(self, auth_client, login_user):
        """After 5 failed attempts the account should be locked, rejecting even valid creds."""
        # Fail 5 times to trigger lockout (threshold is 5 per accounts/models.py)
        for i in range(5):
            resp = auth_client.post(
                LOGIN_URL,
                {
                    "username": login_user.username,
                    "password": "wrong_password",
                },
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
                f"Attempt {i + 1}: expected 400, got {resp.status_code}"
            )

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 5
        assert login_user.is_locked, "Account should be locked after 5 failures"

        # Now try with the CORRECT password -- should still be rejected
        resp = auth_client.post(
            LOGIN_URL,
            {
                "username": login_user.username,
                "password": PASSWORD,
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
            "Login with correct password should fail while account is locked"
        )
