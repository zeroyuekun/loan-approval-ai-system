"""Tests for GET /api/v1/ml/quotes/."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ml_engine.models import QuoteLog

URL = "/api/v1/ml/quotes/"


def _make_user(username: str, role: str = "customer"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="x-pass", role=role)


def _make_quote(user, eligible: bool = True) -> QuoteLog:
    kwargs = {
        "user": user,
        "inputs_hash": "x" * 64,
        "eligible": eligible,
        "expires_at": timezone.now() + datetime.timedelta(days=7),
    }
    if eligible:
        kwargs.update(
            rate_min=Decimal("6.50"),
            rate_max=Decimal("8.50"),
            comparison_rate=Decimal("8.00"),
            estimated_monthly_repayment=Decimal("506.12"),
        )
    return QuoteLog.objects.create(**kwargs)


@pytest.mark.django_db
def test_list_returns_only_own_quotes_for_customer():
    owner = _make_user("owner-list")
    other = _make_user("other-list")
    own_a = _make_quote(owner)
    own_b = _make_quote(owner, eligible=False)
    _make_quote(other)  # noise

    client = APIClient()
    client.force_authenticate(user=owner)
    resp = client.get(URL)

    assert resp.status_code == 200
    body = resp.json()
    ids = {item["quote_id"] for item in body["results"]}
    assert ids == {str(own_a.id), str(own_b.id)}
    # Newest first
    assert body["results"][0]["quote_id"] == str(own_b.id)


@pytest.mark.django_db
def test_list_returns_all_quotes_for_staff():
    user_a = _make_user("a-list")
    user_b = _make_user("b-list")
    q_a = _make_quote(user_a)
    q_b = _make_quote(user_b)
    staff = _make_user("officer-list", role="officer")

    client = APIClient()
    client.force_authenticate(user=staff)
    resp = client.get(URL)

    assert resp.status_code == 200
    ids = {item["quote_id"] for item in resp.json()["results"]}
    assert {str(q_a.id), str(q_b.id)}.issubset(ids)


@pytest.mark.django_db
def test_list_empty_when_user_has_no_quotes():
    user = _make_user("empty-list")
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.get(URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["results"] == []


@pytest.mark.django_db
def test_list_rejects_unauthenticated():
    client = APIClient()
    resp = client.get(URL)
    assert resp.status_code in (401, 403)
