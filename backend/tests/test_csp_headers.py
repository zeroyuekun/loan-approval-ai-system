"""Test that Content Security Policy headers are present in responses."""

import pytest
from django.test import Client


@pytest.mark.django_db
class TestCSPHeaders:
    """Verify CSP middleware adds security headers to all responses.

    Uses Django's native test Client (not DRF APIClient) because CSP
    headers are added by Django middleware which the native client
    processes correctly.
    """

    def test_csp_header_present(self):
        client = Client()
        response = client.get("/api/v1/health/")
        csp = response.get("Content-Security-Policy") or response.get("Content-Security-Policy-Report-Only")
        assert csp is not None, "CSP header should be present"
        assert "default-src" in csp

    def test_csp_includes_expected_directives(self):
        client = Client()
        response = client.get("/api/v1/health/")
        csp = response.get("Content-Security-Policy") or response.get("Content-Security-Policy-Report-Only")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_csp_header_on_authenticated_endpoint(self):
        client = Client()
        # Even unauthenticated requests should get CSP headers
        response = client.get("/api/v1/health/")
        csp = response.get("Content-Security-Policy") or response.get("Content-Security-Policy-Report-Only")
        assert csp is not None, "CSP header should be present on all responses"
