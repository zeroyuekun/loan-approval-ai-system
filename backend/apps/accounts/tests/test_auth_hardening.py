"""Auth hardening regression guards (review #6 + gap G1).

#6 — CustomUser.email is not unique. Registering a second account with a
victim's email used to break their email login with an unhandled
MultipleObjectsReturned (500 / account DoS). Registration now rejects duplicate
emails (case-insensitive) and the email-login path resolves any legacy
duplicates to the original account instead of 500ing.

G1 — the login / register / refresh throttles subclassed AnonRateThrottle but
only overrode `rate`, not `scope`, so all three shared the single "anon" per-IP
cache key and interfered with each other's limits. Each now owns a scope.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import CustomUser
from apps.accounts.serializers import LoginSerializer, RegisterSerializer
from apps.accounts.views import LoginRateThrottle, RefreshRateThrottle, RegisterRateThrottle

_PW = "Xx123456789!"  # 13 chars, satisfies length + upper/lower/digit rules


# --- G1: throttle scope isolation ---


def test_auth_throttles_have_distinct_non_anon_scopes():
    scopes = [LoginRateThrottle().scope, RegisterRateThrottle().scope, RefreshRateThrottle().scope]
    assert len(set(scopes)) == 3, f"throttle scopes must be distinct, got {scopes}"
    assert "anon" not in scopes, "auth throttles must not share AnonRateThrottle's 'anon' bucket"


def test_auth_throttle_rates_unchanged():
    assert LoginRateThrottle().rate == "5/min"
    assert RegisterRateThrottle().rate == "3/min"
    assert RefreshRateThrottle().rate == "30/min"


# --- #6: duplicate-email registration + login resolution ---


@pytest.mark.django_db
def test_register_rejects_duplicate_email_case_insensitively():
    CustomUser.objects.create_user(username="victim", email="dup@example.com", password=_PW)
    serializer = RegisterSerializer(
        data={
            "username": "attacker",
            "email": "DUP@example.com",  # case-insensitive collision with the victim
            "password": _PW,
            "password2": _PW,
            "first_name": "Ann",
            "last_name": "Other",
        }
    )
    assert not serializer.is_valid()
    assert "email" in serializer.errors


@pytest.mark.django_db
def test_email_login_with_legacy_duplicate_emails_does_not_500():
    # Two accounts sharing an email, as could exist before the uniqueness check.
    original = CustomUser.objects.create_user(username="orig", email="dup2@example.com", password=_PW)
    CustomUser.objects.create_user(username="second", email="dup2@example.com", password="Yy123456789!")

    serializer = LoginSerializer(data={"username": "dup2@example.com", "password": _PW})

    # Must NOT raise MultipleObjectsReturned; resolves to the original (oldest)
    # account so the victim can still log in by email.
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["user"].id == original.id
