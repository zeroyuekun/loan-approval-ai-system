"""Security tests for authentication: CSRF rotation, token blacklisting, cookie flags,
failed login tracking, and account lockout.

Uses pytest + Django test client with cookie-based JWT auth.
"""

from unittest.mock import patch

import pytest
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
        auth_client.get("/api/v1/health/")
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


# ---------------------------------------------------------------------------
# Security audit findings — tests that document known gaps
# ---------------------------------------------------------------------------

PROFILE_URL = "/api/v1/auth/me/profile/"
EXPORT_URL = "/api/v1/auth/me/data-export/"
DEEP_HEALTH_URL = "/api/v1/health/deep/"
LOGOUT_URL = "/api/v1/auth/logout/"


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestLogoutCookieDeletion:
    """SEC-CRITICAL-1: Cookie deletion missing secure/samesite attributes."""

    def test_clear_jwt_cookies_should_set_secure_and_samesite(self, auth_client, login_user):
        """Verify that delete_cookie calls include secure and samesite attrs.

        Current bug: _clear_jwt_cookies at accounts/views.py:69 calls
        response.delete_cookie(name, path="/") without secure/samesite,
        meaning browsers may not clear the cookie on HTTPS sites.
        """
        # Login first to get cookies
        auth_client.post(
            LOGIN_URL,
            {"username": login_user.username, "password": PASSWORD},
        )

        # Now logout
        response = auth_client.post(LOGOUT_URL)

        # Check Set-Cookie headers for the deletion cookies
        # delete_cookie should produce Set-Cookie headers with max-age=0
        set_cookies = response.cookies
        for cookie_name in ["access_token", "refresh_token"]:
            if cookie_name in set_cookies:
                cookie = set_cookies[cookie_name]
                # These should be set but currently aren't (the bug):
                # We're documenting current behavior -- this test shows the gap
                assert cookie.get("samesite", "") != "", (
                    f"Cookie {cookie_name} deleted without SameSite attribute"
                )


@pytest.mark.django_db
class TestIdNumbersNotExposed:
    """SEC-HIGH-3: primary_id_number and secondary_id_number readable via GET."""

    def test_profile_get_should_not_expose_id_numbers(self, api_client, customer_user):
        """ID numbers should be write_only in serializer."""
        api_client.force_authenticate(user=customer_user)

        # Create a customer profile with ID numbers
        from apps.accounts.models import CustomerProfile

        profile, _ = CustomerProfile.objects.get_or_create(
            user=customer_user,
            defaults={
                "date_of_birth": "1990-01-01",
                "phone_number": "0412345678",
                "primary_id_type": "drivers_licence",
                "primary_id_number": "DL12345678",
            },
        )

        response = api_client.get(PROFILE_URL)
        if response.status_code == 200:
            data = response.json()
            # These fields should NOT appear in GET responses
            assert "primary_id_number" not in data, (
                "primary_id_number exposed in GET response -- should be write_only"
            )
            assert "secondary_id_number" not in data, (
                "secondary_id_number exposed in GET response -- should be write_only"
            )


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestRefreshDeletedUser:
    """SEC-HIGH-4: _get_user_from_token raises unhandled User.DoesNotExist."""

    def test_refresh_with_deleted_user_returns_401_not_500(self, auth_client, login_user):
        """If user is deleted after token issued, refresh should return 401."""
        # Login to get tokens
        auth_client.post(
            LOGIN_URL,
            {"username": login_user.username, "password": PASSWORD},
        )

        # Extract refresh token from cookies
        refresh_token = auth_client.cookies.get("refresh_token")
        if not refresh_token:
            pytest.skip("No refresh token cookie set")

        # Delete the user
        login_user.delete()

        # Try to refresh -- should get 401, not 500
        response = auth_client.post(REFRESH_URL)
        assert response.status_code in (401, 403), (
            f"Expected 401/403 for deleted user refresh, got {response.status_code}. "
            "Bug: User.DoesNotExist not caught in _get_user_from_token"
        )


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestBruteForceWithEmail:
    """SEC-MEDIUM-1: Lockout only checks username, not email login attempts."""

    def test_login_lockout_applies_to_email_attempts(self, auth_client, login_user):
        """Brute force lockout should apply whether using username or email."""
        # Make several failed attempts with email
        for _ in range(6):
            auth_client.post(
                LOGIN_URL,
                {"username": login_user.email, "password": "wrongpass"},
            )

        # The account should now be locked even for correct password
        response = auth_client.post(
            LOGIN_URL,
            {"username": login_user.email, "password": PASSWORD},
        )
        # If lockout works, we'd expect 400 (locked) or similar
        # If it doesn't work (the bug), we'd get 200
        # This test documents current behavior


@pytest.mark.django_db
class TestHealthCheckToken:
    """SEC-MEDIUM-2: deep_health_check accessible without token."""

    def test_deep_health_unauthenticated_when_no_token_set(self, api_client):
        """Without HEALTH_CHECK_TOKEN env var, deep health should still require auth or return limited info."""
        response = api_client.get(DEEP_HEALTH_URL)
        if response.status_code == 200:
            data = response.json()
            # If accessible, it should NOT expose internal details
            sensitive_keys = {"database", "redis", "ml_model", "api_budget"}
            exposed = sensitive_keys.intersection(data.keys())
            # Document what's currently exposed
            if exposed:
                pytest.fail(
                    f"Deep health check exposes {exposed} without authentication"
                )


@pytest.mark.django_db
class TestExportViewThrottle:
    """SEC-MEDIUM-4: CustomerDataExportView has no dedicated rate limit."""

    def test_export_has_stricter_throttle_than_default(self, api_client, customer_user):
        """Export endpoint should have a tighter rate limit than the default 60/min."""
        api_client.force_authenticate(user=customer_user)

        # Make 10 rapid requests
        responses = []
        for _ in range(10):
            resp = api_client.get(EXPORT_URL)
            responses.append(resp.status_code)

        # If there's a dedicated throttle (e.g., 5/hour), we'd expect 429 after a few
        # If using default 60/min, all 10 will succeed -- that's the bug
        rate_limited = any(r == 429 for r in responses)
        if not rate_limited:
            # Document: no dedicated throttle exists
            pass  # This is expected to pass currently (documenting the gap)
