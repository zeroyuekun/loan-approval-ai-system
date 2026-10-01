"""M1 — a stale or invalid access cookie must not 401 the endpoints a user
needs to recover from it.

CookieJWTAuthentication raises InvalidToken for a bad access cookie before any
permission check, and login / register / refresh / logout used the default
authentication classes. After a SECRET_KEY rotation or a user deletion the
HttpOnly cookie (which JS cannot clear) blocked all four for up to an hour.
"""

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.loans.models import AuditLog

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
STALE = "not-a-valid-jwt"


def _stale_client():
    cache.clear()
    client = APIClient()
    client.cookies["access_token"] = STALE
    return client


@LOCMEM
@pytest.mark.django_db
def test_login_works_with_a_stale_access_cookie(customer_user):
    resp = _stale_client().post(
        "/api/v1/auth/login/", {"username": customer_user.username, "password": "testpass123"}, format="json"
    )
    assert resp.status_code == 200, resp.data


@LOCMEM
@pytest.mark.django_db
def test_register_works_with_a_stale_access_cookie(db):
    resp = _stale_client().post(
        "/api/v1/auth/register/",
        {
            "username": "fresh_user",
            "email": "fresh@example.com",
            "password": "Vq7#tLw2!mZp",
            "password2": "Vq7#tLw2!mZp",
            "first_name": "Fresh",
            "last_name": "User",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data


@LOCMEM
@pytest.mark.django_db
def test_refresh_works_with_a_stale_access_cookie(customer_user):
    client = _stale_client()
    client.cookies["refresh_token"] = str(RefreshToken.for_user(customer_user))
    resp = client.post("/api/v1/auth/refresh/", {}, format="json")
    assert resp.status_code == 200, resp.data


@LOCMEM
@pytest.mark.django_db
def test_logout_works_with_a_stale_access_cookie_and_clears_the_session(customer_user):
    client = _stale_client()
    refresh = RefreshToken.for_user(customer_user)
    client.cookies["refresh_token"] = str(refresh)
    resp = client.post("/api/v1/auth/logout/", {}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.cookies["access_token"].value == ""
    assert AuditLog.objects.filter(action="logout", user=customer_user).exists()
    # the refresh token is blacklisted: it can no longer mint access tokens
    reuse = APIClient()
    reuse.cookies["refresh_token"] = str(refresh)
    assert reuse.post("/api/v1/auth/refresh/", {}, format="json").status_code == 401
