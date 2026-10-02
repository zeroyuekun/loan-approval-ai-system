"""Two-factor authentication was removed: staff sign in with a password.

These tests log in through the real login endpoint (not force_authenticate),
because the old 2FA gate lived in authentication and a shortcut would skip it.
"""

import pytest
from rest_framework.test import APIClient

PASSWORD = "Corr3ct-horse-battery"


def _login(django_user_model, username, **fields):
    django_user_model.objects.create_user(username=username, password=PASSWORD, email=f"{username}@x.com", **fields)
    client = APIClient()
    resp = client.post("/api/v1/auth/login/", {"username": username, "password": PASSWORD}, format="json")
    assert resp.status_code == 200, resp.data
    return client, resp


@pytest.mark.django_db
def test_staff_password_login_reaches_a_staff_endpoint(django_user_model, settings):
    # The old enforcement flag must have no effect any more.
    settings.ENFORCE_2FA_FOR_STAFF = True
    client, resp = _login(django_user_model, "officer_pw", role="officer")
    assert resp.data["user"]["role"] == "officer"
    assert "requires_2fa" not in resp.data
    assert "requires_2fa_setup" not in resp.data
    assert client.get("/api/v1/auth/customers/").status_code == 200


@pytest.mark.django_db
def test_superuser_with_the_customer_role_still_counts_as_staff(django_user_model):
    # createsuperuser leaves role at the "customer" default; is_superuser
    # alone must still open staff endpoints.
    client, _resp = _login(django_user_model, "root_pw", role="customer", is_superuser=True, is_staff=True)
    assert client.get("/api/v1/auth/customers/").status_code == 200


@pytest.mark.django_db
def test_customer_cannot_reach_a_staff_endpoint(django_user_model):
    client, _resp = _login(django_user_model, "cust_pw", role="customer")
    assert client.get("/api/v1/auth/customers/").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["setup", "verify", "status", "disable"])
def test_two_factor_routes_are_gone(path):
    assert APIClient().get(f"/api/v1/auth/2fa/{path}/").status_code == 404


def test_otp_apps_are_not_installed(settings):
    assert not [app for app in settings.INSTALLED_APPS if app.startswith("django_otp")]
    assert "django_otp.middleware.OTPMiddleware" not in settings.MIDDLEWARE
