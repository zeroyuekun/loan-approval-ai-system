"""
Tests for CORS/ALLOWED_HOSTS whitespace stripping and OpenAPI schema endpoints.
"""

import os
from unittest.mock import patch

import pytest
from django.test.utils import override_settings
from rest_framework.test import APIClient


def _redis_available():
    """Check if Redis is reachable (needed for Django cache in schema tests)."""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=1, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


skip_without_redis = pytest.mark.skipif(
    not _redis_available(),
    reason='Redis not available (tests run in Docker/CI)',
)


# ---------------------------------------------------------------------------
# Helper: replicate the parsing logic from base.py so we can unit-test it
# without importing Django settings (which would freeze the values).
# ---------------------------------------------------------------------------

def _parse_allowed_hosts(env_value=None):
    raw = env_value if env_value is not None else 'localhost,127.0.0.1'
    return [h.strip() for h in raw.split(',') if h.strip()]


def _parse_cors_origins(env_value=None):
    raw = env_value if env_value is not None else 'http://localhost:3000,http://127.0.0.1:3000'
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


# ---------------------------------------------------------------------------
# CORS / ALLOWED_HOSTS parsing tests (pure logic, no DB needed)
# ---------------------------------------------------------------------------

class TestAllowedHostsParsing:

    def test_default_values(self):
        result = _parse_allowed_hosts()
        assert result == ['localhost', '127.0.0.1']

    def test_whitespace_stripped(self):
        result = _parse_allowed_hosts(' localhost , 127.0.0.1 , example.com ')
        assert result == ['localhost', '127.0.0.1', 'example.com']

    def test_trailing_comma_filtered(self):
        result = _parse_allowed_hosts('localhost,127.0.0.1,')
        assert result == ['localhost', '127.0.0.1']

    def test_leading_comma_filtered(self):
        result = _parse_allowed_hosts(',localhost')
        assert result == ['localhost']

    def test_empty_string(self):
        result = _parse_allowed_hosts('')
        assert result == []

    def test_only_commas(self):
        result = _parse_allowed_hosts(',,,')
        assert result == []


class TestCorsOriginsParsing:

    def test_default_values(self):
        result = _parse_cors_origins()
        assert result == ['http://localhost:3000', 'http://127.0.0.1:3000']

    def test_whitespace_stripped(self):
        result = _parse_cors_origins(
            ' http://localhost:3000 , http://example.com '
        )
        assert result == ['http://localhost:3000', 'http://example.com']

    def test_trailing_comma_filtered(self):
        result = _parse_cors_origins('http://localhost:3000,')
        assert result == ['http://localhost:3000']

    def test_empty_string(self):
        result = _parse_cors_origins('')
        assert result == []

    def test_multiple_origins(self):
        result = _parse_cors_origins(
            'http://localhost:3000,https://app.example.com,https://staging.example.com'
        )
        assert result == [
            'http://localhost:3000',
            'https://app.example.com',
            'https://staging.example.com',
        ]


# ---------------------------------------------------------------------------
# OpenAPI schema / Swagger UI endpoint tests (need Django test client + DB)
# ---------------------------------------------------------------------------

@skip_without_redis
@pytest.mark.django_db
class TestSchemaEndpoints:

    @pytest.fixture(autouse=True)
    def setup_client(self, admin_user, api_client):
        self.client = api_client
        self.client.force_authenticate(user=admin_user)

    def test_openapi_schema_returns_200(self):
        response = self.client.get('/api/schema/', format='json')
        assert response.status_code == 200

    def test_openapi_schema_contains_key(self):
        response = self.client.get('/api/schema/', format='json')
        data = response.json()
        assert 'openapi' in data

    def test_swagger_ui_returns_200(self):
        response = self.client.get('/api/docs/')
        assert response.status_code == 200
