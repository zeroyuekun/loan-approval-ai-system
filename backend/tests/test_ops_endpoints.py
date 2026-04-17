"""Tests for operational endpoint gating: /metrics and /api/v1/health/deep/.

Both endpoints must be unreachable without either staff session or a valid
X-Health-Token. Deep health must also refuse to respond in production-like
settings when HEALTH_CHECK_TOKEN is unset.
"""

import pytest
from django.test.utils import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser


@pytest.fixture
def staff_user(db):
    return CustomUser.objects.create_user(
        username="ops_staff",
        email="ops@test.com",
        password="testpass123",
        role="admin",
        is_staff=True,
        first_name="Ops",
        last_name="Staff",
    )


@pytest.fixture
def regular_user(db):
    return CustomUser.objects.create_user(
        username="ops_regular",
        email="regular@test.com",
        password="testpass123",
        role="customer",
        is_staff=False,
        first_name="Regular",
        last_name="User",
    )


@pytest.mark.django_db
class TestMetricsEndpointGating:
    """GET /metrics must be gated behind staff session or X-Health-Token."""

    def test_unauthenticated_denied(self):
        client = APIClient()
        resp = client.get("/metrics")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_non_staff_user_denied(self, regular_user):
        client = APIClient()
        client.login(username="ops_regular", password="testpass123")
        resp = client.get("/metrics")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_user_allowed(self, staff_user):
        client = APIClient()
        client.login(username="ops_staff", password="testpass123")
        resp = client.get("/metrics")
        assert resp.status_code == status.HTTP_200_OK
        assert b"django_http_requests_total" in resp.content or b"# HELP" in resp.content

    @override_settings(HEALTH_CHECK_TOKEN="s3cr3t-ops-token")
    def test_valid_token_header_allowed(self):
        client = APIClient()
        resp = client.get("/metrics", HTTP_X_HEALTH_TOKEN="s3cr3t-ops-token")
        assert resp.status_code == status.HTTP_200_OK

    @override_settings(HEALTH_CHECK_TOKEN="s3cr3t-ops-token")
    def test_invalid_token_header_denied(self):
        client = APIClient()
        resp = client.get("/metrics", HTTP_X_HEALTH_TOKEN="wrong-token")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDeepHealthConfigured:
    """Deep health must refuse to respond if token is unconfigured in production."""

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="")
    def test_unconfigured_token_in_prod_returns_503(self):
        client = APIClient()
        resp = client.get("/api/v1/health/deep/")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "not configured" in resp.json().get("error", "").lower()

    @override_settings(DEBUG=True, HEALTH_CHECK_TOKEN="")
    def test_unconfigured_token_in_debug_allowed(self):
        """Local dev with DEBUG=True may run deep health without a token."""
        client = APIClient()
        resp = client.get("/api/v1/health/deep/")
        # 200 healthy or 503 degraded (no DB/Redis locally) — both OK, not "unconfigured"
        body = resp.json()
        assert "error" not in body or "not configured" not in body.get("error", "")

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="health-tok-xyz")
    def test_configured_token_wrong_header_denied(self):
        client = APIClient()
        resp = client.get("/api/v1/health/deep/", HTTP_X_HEALTH_TOKEN="wrong")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="health-tok-xyz")
    def test_configured_token_correct_header_allowed(self):
        client = APIClient()
        resp = client.get("/api/v1/health/deep/", HTTP_X_HEALTH_TOKEN="health-tok-xyz")
        # Status may be 200 or 503 depending on DB/Redis availability — both pass auth
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert body.get("error") != "unauthorized"
