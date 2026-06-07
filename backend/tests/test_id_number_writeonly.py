"""FIX-2 — CustomerProfileSerializer must NOT return raw ID numbers.

primary_id_number and secondary_id_number are encrypted-at-rest government
IDs. GET /api/v1/auth/me/profile/ must return only the masked variants
(**** 1234); the raw decrypted values must not appear in the response body.

PATCH /api/v1/auth/me/profile/ must still accept and persist new values
(write-only semantics).
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile, CustomUser

pytestmark = pytest.mark.django_db

PROFILE_URL = "/api/v1/auth/me/profile/"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def customer_with_ids(db):
    user = CustomUser.objects.create_user(
        username="id_test_customer",
        email="id_test@example.com",
        password="TestPass123!",
        role="customer",
        first_name="Test",
        last_name="Customer",
    )
    # A CustomerProfile is auto-created by the post_save signal, so use
    # get_or_create and then update the fields we need for the tests.
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.primary_id_number = "DL12345678"
    profile.secondary_id_number = "PP87654321"
    profile.primary_id_type = "drivers_licence"
    profile.secondary_id_type = "passport"
    profile.save()
    return user, profile


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Core assertion: raw ID numbers absent; masked variants present
# ---------------------------------------------------------------------------


def test_get_profile_does_not_return_raw_id_numbers(customer_with_ids):
    """GET /me/profile/ must NOT include raw primary_id_number / secondary_id_number."""
    user, _profile = customer_with_ids
    resp = _authed_client(user).get(PROFILE_URL)

    assert resp.status_code == 200, resp.data

    data = resp.data
    # Raw decrypted values must not appear
    assert "DL12345678" not in str(data), "Raw primary_id_number leaked in response"
    assert "PP87654321" not in str(data), "Raw secondary_id_number leaked in response"

    # The write-only fields must not be present as readable keys
    assert "primary_id_number" not in data or data.get("primary_id_number") is None, (
        "primary_id_number should not be readable (write_only=True)"
    )
    assert "secondary_id_number" not in data or data.get("secondary_id_number") is None, (
        "secondary_id_number should not be readable (write_only=True)"
    )


def test_get_profile_returns_masked_variants(customer_with_ids):
    """GET /me/profile/ must return the masked ****XXXX variants."""
    user, _profile = customer_with_ids
    resp = _authed_client(user).get(PROFILE_URL)

    assert resp.status_code == 200, resp.data
    data = resp.data

    assert "primary_id_number_masked" in data, "primary_id_number_masked not in response"
    assert "secondary_id_number_masked" in data, "secondary_id_number_masked not in response"

    # Masked values should show only last 4 chars
    assert data["primary_id_number_masked"] == "****5678", (
        f"Expected ****5678, got {data['primary_id_number_masked']}"
    )
    assert data["secondary_id_number_masked"] == "****4321", (
        f"Expected ****4321, got {data['secondary_id_number_masked']}"
    )


def test_patch_profile_can_update_id_number(customer_with_ids):
    """PATCH /me/profile/ can still set/update primary_id_number (write-only)."""
    user, _profile = customer_with_ids
    client = _authed_client(user)

    new_id = "DL99887766"
    resp = client.patch(PROFILE_URL, {"primary_id_number": new_id}, format="json")

    assert resp.status_code in (200, 204), resp.data

    # Raw value persisted in DB (encrypted)
    _profile.refresh_from_db()
    assert _profile.primary_id_number == new_id

    # But GET still doesn't expose the raw value
    resp2 = client.get(PROFILE_URL)
    assert resp2.status_code == 200
    assert new_id not in str(resp2.data), "Updated raw ID number leaked in GET response"
    # Masked variant reflects new value
    assert resp2.data.get("primary_id_number_masked") == "****7766", (
        f"Masked variant not updated: {resp2.data.get('primary_id_number_masked')}"
    )


# ---------------------------------------------------------------------------
# Serializer unit-level check (no HTTP overhead)
# ---------------------------------------------------------------------------


def test_serializer_write_only_flag():
    """CustomerProfileSerializer.fields marks id numbers as write_only."""
    from apps.accounts.serializers import CustomerProfileSerializer

    s = CustomerProfileSerializer()
    assert s.fields["primary_id_number"].write_only is True, (
        "primary_id_number must be write_only on CustomerProfileSerializer"
    )
    assert s.fields["secondary_id_number"].write_only is True, (
        "secondary_id_number must be write_only on CustomerProfileSerializer"
    )
