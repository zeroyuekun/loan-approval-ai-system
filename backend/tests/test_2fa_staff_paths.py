"""I2 — ENFORCE_2FA_FOR_STAFF applies to every staff path, not only the views
that happen to use IsAdmin / IsAdminOrOfficer.

Most staff data access was decided by role-string compares in querysets,
check_loan_access and TaskStatusView, none of which called the 2FA check, so an
un-enrolled officer could list every application with enforcement on.

These tests log in for real (cookie JWT) instead of force_authenticate, so the
request goes through the authentication class like production traffic does.
"""

import pytest
from django.core.cache import cache
from django.test import override_settings
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import Complaint, DecisionReview, LoanDecision

PASSWORD = "Tr1cky-Passw0rd!x"
ENFORCED = override_settings(
    ENFORCE_2FA_FOR_STAFF=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


def _login(username, role, *, enrolled=False, **extra):
    user = CustomUser.objects.create_user(
        username=username, password=PASSWORD, email=f"{username}@example.com", role=role, **extra
    )
    if enrolled:
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    client = APIClient()
    # An enrolled user's login needs an OTP; issue the cookie directly instead.
    from rest_framework_simplejwt.tokens import RefreshToken

    client.cookies["access_token"] = str(RefreshToken.for_user(user).access_token)
    return user, client


@pytest.fixture
def staff_targets(sample_application, customer_user):
    LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.3)
    Complaint.objects.create(
        complainant=customer_user,
        loan_application=sample_application,
        category="decision",
        subject="s",
        description="d",
    )
    DecisionReview.objects.create(application=sample_application, requested_by=customer_user, reason="r")
    return sample_application


def _staff_paths(app):
    return [
        ("get", "/api/v1/loans/"),
        ("get", f"/api/v1/loans/{app.pk}/"),
        ("patch", f"/api/v1/loans/{app.pk}/"),
        ("get", "/api/v1/loans/complaints/"),
        ("get", "/api/v1/loans/decision-reviews/"),
        # check_loan_access callers (email, agents, ml)
        ("get", f"/api/v1/emails/{app.pk}/"),
        ("get", f"/api/v1/agents/runs/{app.pk}/"),
        ("get", "/api/v1/tasks/some-task-id/status/"),
        # IsAdminOrOfficer path (already gated before; must stay gated)
        ("get", "/api/v1/auth/customers/"),
    ]


@ENFORCED
@pytest.mark.django_db
@pytest.mark.parametrize("index", range(9))
def test_unenrolled_officer_is_blocked_on_every_staff_path(staff_targets, index):
    cache.clear()
    _, client = _login("unenrolled_officer", "officer")
    method, url = _staff_paths(staff_targets)[index]
    resp = getattr(client, method)(url, {}, format="json")
    assert resp.status_code == 403, (url, resp.status_code, getattr(resp, "data", None))
    assert resp.data["code"] == "2fa_enrolment_required"


@ENFORCED
@pytest.mark.django_db
def test_unenrolled_superuser_is_blocked_too(staff_targets):
    """createsuperuser defaults role to customer; is_superuser is still staff."""
    cache.clear()
    _, client = _login("root", "customer", is_superuser=True, is_staff=True)
    resp = client.get("/api/v1/loans/")
    assert resp.status_code == 403
    assert resp.data["code"] == "2fa_enrolment_required"


@ENFORCED
@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/api/v1/auth/2fa/status/"),
        ("post", "/api/v1/auth/2fa/setup/"),
        ("get", "/api/v1/auth/me/"),
        ("post", "/api/v1/auth/logout/"),
    ],
)
def test_enrolment_endpoints_stay_reachable_for_unenrolled_staff(method, url, db):
    cache.clear()
    _, client = _login("enrolling_officer", "officer")
    resp = getattr(client, method)(url, {}, format="json")
    # Reached the view (logout answers 400 without a refresh token): not
    # rejected by authentication or the enrolment gate.
    assert resp.status_code not in (401, 403), (url, resp.status_code, getattr(resp, "data", None))


@ENFORCED
@pytest.mark.django_db
def test_enrolled_officer_reaches_staff_paths(staff_targets):
    cache.clear()
    _, client = _login("enrolled_officer", "officer", enrolled=True)
    resp = client.get("/api/v1/loans/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1  # staff scope: sees the customer's application


@ENFORCED
@pytest.mark.django_db
def test_customers_are_never_gated(staff_targets, customer_user):
    cache.clear()
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    client.cookies["access_token"] = str(RefreshToken.for_user(customer_user).access_token)
    assert client.get("/api/v1/loans/").status_code == 200


@pytest.mark.django_db
def test_enforcement_off_leaves_unenrolled_staff_alone(staff_targets):
    cache.clear()
    _, client = _login("relaxed_officer", "officer")
    assert client.get("/api/v1/loans/").status_code == 200


@pytest.mark.django_db
def test_django_admin_requires_a_verified_otp_session_when_enforced(db):
    """The Django admin is a staff path too (session auth, not the API)."""
    from django.conf import settings
    from django.test import Client

    officer = CustomUser.objects.create_user(
        username="admin_site_officer", password=PASSWORD, email="aso@example.com", role="admin", is_staff=True
    )
    TOTPDevice.objects.create(user=officer, name="default", confirmed=True)
    client = Client()
    client.force_login(officer)  # password-only session: not OTP-verified
    url = f"/{settings.DJANGO_ADMIN_URL}"

    with override_settings(ENFORCE_2FA_FOR_STAFF=True):
        assert client.get(url).status_code == 302  # sent back to the (OTP) login form
    with override_settings(ENFORCE_2FA_FOR_STAFF=False):
        assert client.get(url).status_code == 200
