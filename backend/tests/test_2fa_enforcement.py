"""Two-factor authentication enforcement — PR-4 of security gap-closure.

Spec: docs/superpowers/specs/2026-05-25-security-gap-closure-design.md

Covers the login-flow gate and the optional endpoint-level enforcement
gate (gated by ``ENFORCE_2FA_FOR_STAFF`` setting, default off).

Recovery codes are deferred to a follow-up PR — they need a coordinated
display-once UX in the frontend and so don't belong in this backend-only
landing.
"""

from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase, override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog


def _make_device(user, *, confirmed: bool = True) -> TOTPDevice:
    """Build a TOTP device with a known secret so tests can compute
    valid codes via django_otp's own TOTP helper (no third-party dep)."""
    # 20-byte secret (RFC 6238 recommendation), all-zero so the key is
    # deterministic across test runs.
    secret_hex = "00" * 20
    device = TOTPDevice.objects.create(
        user=user,
        name="default",
        confirmed=confirmed,
        key=secret_hex,
        step=30,
        digits=6,
    )
    return device


def _valid_token(device: TOTPDevice) -> str:
    """Compute the current TOTP code for ``device`` using django_otp's
    own oath.totp — the same algorithm verify_token uses, so a token
    minted here is guaranteed to verify."""
    secret_bytes = bytes.fromhex(device.key)
    code = totp(
        key=secret_bytes,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=0,
    )
    return f"{code:0{device.digits}d}"


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class LoginTwoFactorGateTests(TestCase):
    """LoginView's 2FA flow — applies regardless of
    ENFORCE_2FA_FOR_STAFF setting (the gate kicks in based on whether
    the user has a confirmed device, not on a global flag)."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        AuditLog.objects.all().delete()

    # -- Customer (never gated) ------------------------------------------------

    def test_customer_login_unchanged(self):
        """Customers don't need 2FA — login proceeds as before."""
        CustomUser.objects.create_user(
            username="customer1",
            password="TestPass123!",
            email="customer1@example.com",
            role="customer",
        )
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "customer1", "password": "TestPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.cookies)
        self.assertNotIn("requires_2fa", response.data)
        self.assertNotIn("requires_2fa_setup", response.data)

    # -- Admin / officer WITHOUT a confirmed TOTP device -----------------------

    def test_admin_without_totp_gets_jwt_plus_setup_flag(self):
        """Frontend redirects to /2fa/setup based on the flag."""
        CustomUser.objects.create_user(
            username="admin1",
            password="TestPass123!",
            email="admin1@example.com",
            role="admin",
        )
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "admin1", "password": "TestPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.cookies)
        self.assertTrue(response.data.get("requires_2fa_setup"))
        # Audit-logged as a distinct action
        actions = list(
            AuditLog.objects.filter(action__startswith="login_").values_list("action", flat=True)
        )
        self.assertIn("login_success_no_2fa_setup", actions)

    def test_officer_without_totp_gets_jwt_plus_setup_flag(self):
        CustomUser.objects.create_user(
            username="officer1",
            password="TestPass123!",
            email="officer1@example.com",
            role="officer",
        )
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "officer1", "password": "TestPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.cookies)
        self.assertTrue(response.data.get("requires_2fa_setup"))

    # -- Admin / officer WITH a confirmed TOTP device --------------------------

    def test_admin_with_totp_missing_otp_returns_requires_2fa_no_jwt(self):
        user = CustomUser.objects.create_user(
            username="admin2",
            password="TestPass123!",
            email="admin2@example.com",
            role="admin",
        )
        _make_device(user, confirmed=True)

        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "admin2", "password": "TestPass123!"},
        )
        # Returns 200 with a flag — NOT a 4xx because creds were valid;
        # the gate is the second factor, not an auth failure.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("requires_2fa"))
        # No JWT issued
        self.assertNotIn("access_token", response.cookies)
        # Audit-logged
        self.assertTrue(
            AuditLog.objects.filter(action="login_2fa_required").exists()
        )

    def test_admin_with_totp_and_valid_otp_gets_jwt(self):
        user = CustomUser.objects.create_user(
            username="admin3",
            password="TestPass123!",
            email="admin3@example.com",
            role="admin",
        )
        device = _make_device(user, confirmed=True)

        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "admin3",
                "password": "TestPass123!",
                "otp_token": _valid_token(device),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.cookies)
        self.assertNotIn("requires_2fa", response.data)
        self.assertNotIn("requires_2fa_setup", response.data)
        # Audit-logged as normal success (not the no-setup variant)
        self.assertTrue(
            AuditLog.objects.filter(action="login_success").exists()
        )

    def test_admin_with_totp_and_invalid_otp_rejected(self):
        user = CustomUser.objects.create_user(
            username="admin4",
            password="TestPass123!",
            email="admin4@example.com",
            role="admin",
        )
        _make_device(user, confirmed=True)

        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "admin4",
                "password": "TestPass123!",
                "otp_token": "000000",  # almost certainly not the current code
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access_token", response.cookies)
        # Failed-login attempt counter incremented (so brute-force is gated)
        user.refresh_from_db()
        self.assertGreaterEqual(user.failed_login_attempts, 1)
        # Audit-logged
        self.assertTrue(
            AuditLog.objects.filter(action="login_2fa_invalid").exists()
        )

    def test_admin_with_unconfirmed_totp_still_gets_setup_flag(self):
        """An unconfirmed device doesn't count — user needs to verify first.
        Treat them the same as 'no device'."""
        user = CustomUser.objects.create_user(
            username="admin5",
            password="TestPass123!",
            email="admin5@example.com",
            role="admin",
        )
        _make_device(user, confirmed=False)

        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "admin5", "password": "TestPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.cookies)
        self.assertTrue(response.data.get("requires_2fa_setup"))

    # -- Break-glass via ALLOW_2FA_BYPASS --------------------------------------

    @override_settings(ALLOW_2FA_BYPASS=True)
    def test_bypass_skips_otp_check(self):
        """ALLOW_2FA_BYPASS lets admin in without an OTP code even when
        a device is enrolled. Audit-logged so incident-response can
        review every use."""
        user = CustomUser.objects.create_user(
            username="admin6",
            password="TestPass123!",
            email="admin6@example.com",
            role="admin",
        )
        _make_device(user, confirmed=True)

        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "admin6", "password": "TestPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.cookies)
        self.assertTrue(
            AuditLog.objects.filter(action="login_2fa_bypassed").exists()
        )


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    ENFORCE_2FA_FOR_STAFF=True,
)
class EndpointEnforcementTests(TestCase):
    """When ENFORCE_2FA_FOR_STAFF=True, IsAdmin/IsAdminOrOfficer
    permissions also gate on the user having a confirmed TOTP device.

    Pre-rollout (default off): admin/officer endpoints behave as before.
    Post-rollout (admins all enrolled): flip the flag, endpoints reject
    any admin/officer without 2FA."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _login_admin(self, username="enforced_admin", with_totp=False):
        user = CustomUser.objects.create_user(
            username=username,
            password="TestPass123!",
            email=f"{username}@example.com",
            role="admin",
        )
        kwargs = {"username": username, "password": "TestPass123!"}
        if with_totp:
            device = _make_device(user, confirmed=True)
            kwargs["otp_token"] = _valid_token(device)
        response = self.client.post("/api/v1/auth/login/", kwargs)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return user

    def test_admin_without_totp_blocked_from_staff_endpoint(self):
        """The customers-list endpoint uses IsAdminOrOfficer — blocked
        when admin hasn't enrolled in 2FA and enforcement is on."""
        self._login_admin(with_totp=False)
        response = self.client.get("/api/v1/auth/customers/")
        # Permission denied — either 403 (DRF default) or 401 if the
        # auth scheme rejects first. Both are acceptable rejection codes.
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_admin_with_totp_can_reach_staff_endpoint(self):
        self._login_admin(username="enrolled_admin", with_totp=True)
        response = self.client.get("/api/v1/auth/customers/")
        # The endpoint exists and responds 200 (or 200-equivalent) for
        # an authenticated admin with confirmed 2FA.
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_endpoint_unaffected_by_2fa_setting(self):
        """Customers never need 2FA — the enforcement flag must not
        accidentally lock them out of their own profile."""
        CustomUser.objects.create_user(
            username="customer_under_enforcement",
            password="TestPass123!",
            email="cust_e@example.com",
            role="customer",
        )
        self.client.post(
            "/api/v1/auth/login/",
            {"username": "customer_under_enforcement", "password": "TestPass123!"},
        )
        # /api/v1/auth/me/ is IsAuthenticated — works for customers
        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class HasConfirmedTOTPHelperTests(TestCase):
    """The CustomUser.has_confirmed_totp() helper used by the login
    view and the permissions."""

    def test_returns_false_when_no_devices(self):
        user = CustomUser.objects.create_user(
            username="no_device",
            password="x",
            email="nodev@example.com",
            role="admin",
        )
        self.assertFalse(user.has_confirmed_totp())

    def test_returns_false_when_only_unconfirmed_devices(self):
        user = CustomUser.objects.create_user(
            username="unconfirmed",
            password="x",
            email="unc@example.com",
            role="admin",
        )
        _make_device(user, confirmed=False)
        self.assertFalse(user.has_confirmed_totp())

    def test_returns_true_when_confirmed_device_exists(self):
        user = CustomUser.objects.create_user(
            username="confirmed",
            password="x",
            email="conf@example.com",
            role="admin",
        )
        _make_device(user, confirmed=True)
        self.assertTrue(user.has_confirmed_totp())
