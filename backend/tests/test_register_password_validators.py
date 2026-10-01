"""I9 — registration runs the configured AUTH_PASSWORD_VALIDATORS.

RegisterSerializer only checked length and character classes, so the
common-password and user-attribute-similarity validators in settings never
ran: "Password1234" or a password built from the username was accepted.
"""

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


def _register(username, password):
    cache.clear()  # register is throttled per IP
    return APIClient().post(
        "/api/v1/auth/register/",
        {
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "password2": password,
            "first_name": "Jane",
            "last_name": "Citizen",
        },
        format="json",
    )


@LOCMEM
@pytest.mark.django_db
def test_common_password_is_rejected():
    resp = _register("commonpw", "Password1234")
    assert resp.status_code == 400, resp.data
    assert "password" in resp.data


@LOCMEM
@pytest.mark.django_db
def test_password_similar_to_the_username_is_rejected():
    resp = _register("janecitizen", "Janecitizen1")
    assert resp.status_code == 400, resp.data
    assert "password" in resp.data


@LOCMEM
@pytest.mark.django_db
def test_strong_password_is_accepted():
    resp = _register("strongpw", "Vq7#tLw2!mZp")
    assert resp.status_code == 201, resp.data
