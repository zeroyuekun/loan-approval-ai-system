"""I1 — anonymous throttles key on the real client IP, not a spoofable header.

DRF's BaseThrottle.get_ident uses the whole X-Forwarded-For header as the
bucket key when REST_FRAMEWORK["NUM_PROXIES"] is None (the DRF default), so a
client that sends a different X-Forwarded-For on every request gets a fresh
bucket each time and the login / register / refresh limits never apply.
"""

import itertools

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

LOCMEM = override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
_counter = itertools.count()


def _login(client, **extra):
    return client.post(
        "/api/v1/auth/login/",
        {"username": f"nobody{next(_counter)}", "password": "wrong-password"},
        format="json",
        **extra,
    )


def test_num_proxies_is_configured():
    # None means "trust the whole client-supplied header".
    assert settings.REST_FRAMEWORK.get("NUM_PROXIES") is not None


@LOCMEM
@pytest.mark.django_db
def test_spoofed_forwarded_for_does_not_open_a_fresh_login_bucket():
    """No proxy in front (dev/compose): X-Forwarded-For is ignored entirely."""
    cache.clear()
    client = APIClient()
    statuses = [_login(client, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code for i in range(8)]
    assert 429 in statuses, statuses


@LOCMEM
@pytest.mark.django_db
def test_behind_one_proxy_the_bucket_is_the_address_the_proxy_appended():
    """One hop (k8s ingress): only the right-most entry, which the ingress
    appended from the TCP peer, is trusted; the client-controlled prefix is not."""
    cache.clear()
    rf = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    with override_settings(REST_FRAMEWORK=rf):
        client = APIClient()
        statuses = [_login(client, HTTP_X_FORWARDED_FOR=f"6.6.6.{i}, 203.0.113.7").status_code for i in range(8)]
        assert 429 in statuses, statuses

        other = APIClient()
        # A different real client behind the same proxy still has its own bucket.
        assert _login(other, HTTP_X_FORWARDED_FOR="203.0.113.8").status_code != 429
