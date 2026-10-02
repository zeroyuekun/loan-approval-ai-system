"""Audit rows record the client's address, not the reverse proxy's.

Behind the ingress every request arrives from the proxy, so REMOTE_ADDR is
the same for everyone. The throttles already derive the client address from
X-Forwarded-For according to NUM_PROXIES; the audit trail has to use the same
rule.
"""

import pytest
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.common.http import client_ip
from apps.loans.models import AuditLog

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def _rest_framework(num_proxies):
    from django.conf import settings

    return {**settings.REST_FRAMEWORK, "NUM_PROXIES": num_proxies}


@pytest.mark.django_db
def test_login_audit_row_records_the_forwarded_client_address():
    CustomUser.objects.create_user(username="ipuser", email="ip@x.com", password="Str0ng!Passw0rd#", role="customer")
    with override_settings(REST_FRAMEWORK=_rest_framework(1), CACHES=LOCMEM):
        resp = APIClient().post(
            "/api/v1/auth/login/",
            {"username": "ipuser", "password": "Str0ng!Passw0rd#"},
            format="json",
            REMOTE_ADDR="10.0.0.5",
            HTTP_X_FORWARDED_FOR="203.0.113.7",
        )
    assert resp.status_code == 200, resp.data
    assert AuditLog.objects.get(action="login_success").ip_address == "203.0.113.7"


def test_client_ip_ignores_the_forwarded_header_without_trusted_proxies():
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="203.0.113.7")
    with override_settings(REST_FRAMEWORK=_rest_framework(0)):
        assert client_ip(request) == "10.0.0.5"


def test_client_ip_takes_the_address_the_trusted_proxy_appended():
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7")
    with override_settings(REST_FRAMEWORK=_rest_framework(1)):
        assert client_ip(request) == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr_when_the_header_is_not_an_address():
    """A client that reaches the backend directly can send any header; a
    non-address must not reach the inet column."""
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="not-an-ip")
    with override_settings(REST_FRAMEWORK=_rest_framework(1)):
        assert client_ip(request) == "10.0.0.5"
