"""Security tests for authentication: CSRF rotation, token blacklisting, cookie flags,
failed login tracking, and account lockout.

Uses pytest + Django test client with cookie-based JWT auth.
"""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from django.utils import timezone
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


def _post_login(client, username, password):
    return client.post(LOGIN_URL, {"username": username, "password": password})


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
        login_resp = _post_login(auth_client, login_user.username, PASSWORD)
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
        login_resp = _post_login(auth_client, login_user.username, PASSWORD)
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
        login_resp = _post_login(auth_client, login_user.username, PASSWORD)
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
            resp = _post_login(auth_client, login_user.username, "wrong_password")
            assert resp.status_code == status.HTTP_400_BAD_REQUEST

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 3, (
            f"Expected 3 failed attempts, got {login_user.failed_login_attempts}"
        )

    def test_successful_login_resets_counter(self, auth_client, login_user):
        """A successful login after failures should reset the counter to 0."""
        # Fail twice
        for _ in range(2):
            _post_login(auth_client, login_user.username, "wrong_password")

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 2

        # Succeed
        resp = _post_login(auth_client, login_user.username, PASSWORD)
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
            resp = _post_login(auth_client, login_user.username, "wrong_password")
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
                f"Attempt {i + 1}: expected 400, got {resp.status_code}"
            )

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 5
        assert login_user.is_locked, "Account should be locked after 5 failures"

        # Now try with the CORRECT password -- should still be rejected
        resp = _post_login(auth_client, login_user.username, PASSWORD)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
            "Login with correct password should fail while account is locked"
        )

    def test_lockout_applies_when_authenticating_by_email(self, auth_client, login_user):
        """Submitting the EMAIL in the username field must be subject to the same
        lockout + failed-attempt accounting (regression: email login bypassed the
        lockout entirely because the view resolved the user only by username)."""
        for i in range(5):
            resp = _post_login(auth_client, login_user.email, "wrong_password")
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, f"Attempt {i + 1}"

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 5, "Failed attempts must count for email login"
        assert login_user.is_locked, "Account should lock after 5 email-based failures"

        # Correct password via email must still be rejected while locked.
        resp = _post_login(auth_client, login_user.email, PASSWORD)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
            "Correct password via email should fail while the account is locked"
        )


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestCookieAuthCSRFEnforcement:
    """Cookie-based JWT auth must enforce CSRF on mutating requests."""

    def _login(self, client, user):
        resp = _post_login(client, user.username, PASSWORD)
        assert resp.status_code == status.HTTP_200_OK, resp.content
        return resp

    def test_cookie_auth_without_csrf_header_rejected(self, auth_client, login_user):
        """POST with cookie auth but no X-CSRFToken must return 403 CSRF Failed."""
        client = APIClient(enforce_csrf_checks=True)
        self._login(client, login_user)
        resp = client.post("/api/v1/loans/", data={"loan_amount": 1000}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        body = resp.json() if resp.content else {}
        assert "CSRF" in (body.get("detail") or "")

    def test_cookie_auth_with_valid_csrf_header_accepted(self, auth_client, login_user):
        """POST with cookie auth AND a valid X-CSRFToken must pass CSRF."""
        client = APIClient(enforce_csrf_checks=True)
        self._login(client, login_user)
        csrf_cookie = client.cookies.get("csrftoken")
        assert csrf_cookie is not None, "Login should set csrftoken cookie"
        resp = client.post(
            "/api/v1/loans/",
            data={},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_cookie.value,
        )
        assert resp.status_code != status.HTTP_403_FORBIDDEN or "CSRF" not in (resp.json().get("detail") or "")

    def test_bearer_header_auth_bypasses_csrf(self, auth_client, login_user):
        """Authorization: Bearer path (programmatic clients) must NOT require CSRF."""
        from rest_framework_simplejwt.tokens import RefreshToken

        token = str(RefreshToken.for_user(login_user).access_token)
        client = APIClient(enforce_csrf_checks=True)
        resp = client.post(
            "/api/v1/loans/",
            data={},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert not (resp.status_code == 403 and "CSRF" in (resp.json().get("detail") or ""))


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestFailedLoginsExpire:
    """Failures only add up while they keep coming. The count used to grow until
    a successful sign-in, and from 15 failures each wrong password locked the
    account for 24 hours: one request a day kept a staff account locked."""

    def _fail_once(self, client, user):
        resp = _post_login(client, user.username, "wrong_password")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize(
        "last_failure_age",
        [
            pytest.param(timedelta(hours=25), id="long-ago"),
            # Rows from before migration 0013 have a count but no failure time.
            pytest.param(None, id="never-recorded"),
        ],
    )
    def test_stale_count_starts_again(self, auth_client, login_user, last_failure_age):
        now = timezone.now()
        CustomUser.objects.filter(pk=login_user.pk).update(
            failed_login_attempts=15,
            locked_until=now - timedelta(minutes=1),
            last_failed_login_at=None if last_failure_age is None else now - last_failure_age,
        )

        self._fail_once(auth_client, login_user)

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 1
        assert not login_user.is_locked

    def test_failures_inside_the_window_still_add_up(self, auth_client, login_user):
        CustomUser.objects.filter(pk=login_user.pk).update(
            failed_login_attempts=4, last_failed_login_at=timezone.now() - timedelta(minutes=5)
        )

        self._fail_once(auth_client, login_user)

        login_user.refresh_from_db()
        assert login_user.failed_login_attempts == 5
        assert login_user.is_locked

    def test_lock_lasts_minutes_not_a_day(self, login_user):
        for _ in range(20):
            login_user.record_failed_login()

        login_user.refresh_from_db()
        assert login_user.is_locked
        assert login_user.locked_until <= timezone.now() + timedelta(minutes=15)


@pytest.fixture
def hash_calls(monkeypatch):
    """Record every password hash computed or verified. All hashes in these
    tests use Argon2, the first configured hasher, and its verify() does not
    call encode(), so each entry is one hash."""
    from django.contrib.auth.hashers import Argon2PasswordHasher

    from apps.accounts.views import _dummy_password_hash

    _dummy_password_hash()  # built once per process, before counting starts
    calls = []
    for name in ("encode", "verify"):
        original = getattr(Argon2PasswordHasher, name)

        def counted(self, *args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Argon2PasswordHasher, name, counted)
    return calls


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
class TestLoginSpendsOneHash:
    """Each sign-in branch spends exactly one password hash, so response time
    does not reveal whether an account exists or is locked. Before: an unknown
    username cost two (the view's dummy check plus ModelBackend's own) and a
    locked account cost none."""

    @pytest.mark.parametrize(
        ("username", "password", "expected_status"),
        [
            pytest.param("no_such_user", "wrong_password", status.HTTP_400_BAD_REQUEST, id="unknown-username"),
            pytest.param("nobody@test.com", "wrong_password", status.HTTP_400_BAD_REQUEST, id="unknown-email"),
            pytest.param("security_test_user", "wrong_password", status.HTTP_400_BAD_REQUEST, id="wrong-password"),
            pytest.param("security_test_user", "", status.HTTP_400_BAD_REQUEST, id="blank-password"),
            pytest.param("security_test_user", PASSWORD, status.HTTP_200_OK, id="success"),
        ],
    )
    def test_one_hash(self, auth_client, login_user, hash_calls, username, password, expected_status):
        hash_calls.clear()
        resp = _post_login(auth_client, username, password)
        assert resp.status_code == expected_status
        assert len(hash_calls) == 1, hash_calls

    def test_locked_account(self, auth_client, login_user, hash_calls):
        CustomUser.objects.filter(pk=login_user.pk).update(locked_until=timezone.now() + timedelta(minutes=5))
        hash_calls.clear()
        resp = _post_login(auth_client, login_user.username, PASSWORD)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert len(hash_calls) == 1, hash_calls


# The two bodies an HTML form on another site can post without a preflight.
_NON_JSON_BODIES = {
    "form-encoded": lambda body: {"data": urlencode(body), "content_type": "application/x-www-form-urlencoded"},
    "multipart": lambda body: {"data": body, "format": "multipart"},
}


@pytest.mark.django_db
@patch("apps.accounts.views.LoginRateThrottle.allow_request", _no_throttle)
@patch("apps.accounts.views.RegisterRateThrottle.allow_request", _no_throttle)
class TestAuthEndpointsAcceptJsonOnly:
    """Login and registration skip authentication, so nothing checks CSRF on
    them. A form on another site can post form-encoded or multipart data
    cross-site without a preflight, which would let it sign a visitor in to
    an account the attacker controls."""

    @pytest.mark.parametrize("encoding", _NON_JSON_BODIES)
    def test_non_json_login_is_rejected(self, auth_client, login_user, encoding):
        body = {"username": login_user.username, "password": PASSWORD}
        resp = auth_client.post(LOGIN_URL, **_NON_JSON_BODIES[encoding](body))
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        assert "access_token" not in resp.cookies

    def test_form_encoded_register_is_rejected(self, auth_client):
        body = {
            "username": "form_registrant",
            "email": "form@test.com",
            "password": "Long-Enough-Pass-1",
            "password2": "Long-Enough-Pass-1",
        }
        resp = auth_client.post("/api/v1/auth/register/", **_NON_JSON_BODIES["form-encoded"](body))
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        assert "access_token" not in resp.cookies
        assert not CustomUser.objects.filter(username="form_registrant").exists()

    def test_json_login_still_works(self, auth_client, login_user):
        resp = _post_login(auth_client, login_user.username, PASSWORD)
        assert resp.status_code == status.HTTP_200_OK
        assert "access_token" in resp.cookies
