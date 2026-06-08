"""L28: ReferralListView clamps a non-integer/out-of-range ?limit instead of 500.

int(request.query_params.get("limit")) previously raised ValueError on
?limit=abc, surfacing as an unhandled HTTP 500. Sibling views all wrap parsing.
"""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

REFERRALS_URL = "/api/v1/loans/referrals/"


@pytest.fixture
def admin_client(django_user_model):
    admin = django_user_model.objects.create_user(
        username="ref_admin",
        email="ref_admin@example.com",
        password="x",
        role="admin",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(admin)
    return client


def test_non_integer_limit_does_not_500(admin_client):
    resp = admin_client.get(REFERRALS_URL, {"limit": "abc"})
    assert resp.status_code == 200
    assert "results" in resp.data


def test_limit_clamped_to_max(admin_client):
    resp = admin_client.get(REFERRALS_URL, {"limit": "99999"})
    assert resp.status_code == 200
    assert "results" in resp.data


def test_negative_limit_falls_back(admin_client):
    resp = admin_client.get(REFERRALS_URL, {"limit": "-5"})
    assert resp.status_code == 200
    assert "results" in resp.data


def test_valid_limit_succeeds(admin_client):
    resp = admin_client.get(REFERRALS_URL, {"limit": "10"})
    assert resp.status_code == 200
    assert "results" in resp.data
