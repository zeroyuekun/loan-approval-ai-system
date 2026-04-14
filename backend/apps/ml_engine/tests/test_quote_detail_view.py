"""Tests for GET /api/v1/ml/quotes/<quote_id>/."""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ml_engine.models import QuoteLog


def _make_user(username: str, role: str = "customer"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="x-pass", role=role)


def _make_eligible_quote(user) -> QuoteLog:
    return QuoteLog.objects.create(
        user=user,
        inputs_hash="a" * 64,
        rate_min=Decimal("6.50"),
        rate_max=Decimal("8.50"),
        comparison_rate=Decimal("8.00"),
        estimated_monthly_repayment=Decimal("506.12"),
        eligible=True,
        expires_at=timezone.now() + datetime.timedelta(days=7),
    )


def _make_ineligible_quote(user) -> QuoteLog:
    return QuoteLog.objects.create(
        user=user,
        inputs_hash="b" * 64,
        eligible=False,
        ineligible_reason="Age at maturity exceeds 67",
        expires_at=timezone.now() + datetime.timedelta(days=7),
    )


def _url(quote_id) -> str:
    return f"/api/v1/ml/quotes/{quote_id}/"


@pytest.mark.django_db
def test_owner_can_retrieve_eligible_quote():
    user = _make_user("owner")
    quote = _make_eligible_quote(user)
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.get(_url(quote.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["quote_id"] == str(quote.id)
    assert body["indicative_rate_range"] == {"min": 6.50, "max": 8.50}
    assert body["eligible_for_application"] is True


@pytest.mark.django_db
def test_owner_can_retrieve_ineligible_quote():
    user = _make_user("older")
    quote = _make_ineligible_quote(user)
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.get(_url(quote.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible_for_application"] is False
    assert body["indicative_rate_range"] is None
    assert "67" in body["ineligible_reason"]


@pytest.mark.django_db
def test_other_customer_gets_404_not_403():
    owner = _make_user("owner-2")
    intruder = _make_user("intruder")
    quote = _make_eligible_quote(owner)
    client = APIClient()
    client.force_authenticate(user=intruder)

    resp = client.get(_url(quote.id))

    assert resp.status_code == 404


@pytest.mark.django_db
def test_staff_can_retrieve_any_quote():
    owner = _make_user("owner-3")
    staff = _make_user("officer-1", role="officer")
    quote = _make_eligible_quote(owner)
    client = APIClient()
    client.force_authenticate(user=staff)

    resp = client.get(_url(quote.id))

    assert resp.status_code == 200
    assert resp.json()["quote_id"] == str(quote.id)


@pytest.mark.django_db
def test_nonexistent_quote_returns_404():
    user = _make_user("owner-4")
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.get(_url(uuid.uuid4()))

    assert resp.status_code == 404


@pytest.mark.django_db
def test_unauthenticated_request_is_rejected():
    client = APIClient()
    resp = client.get(_url(uuid.uuid4()))
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_detail_reports_is_expired_true_for_past_expiry():
    user = _make_user("expired-owner")
    quote = _make_eligible_quote(user)
    QuoteLog.objects.filter(pk=quote.pk).update(expires_at=timezone.now() - datetime.timedelta(hours=1))

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(_url(quote.id))

    assert resp.status_code == 200
    assert resp.json()["is_expired"] is True


@pytest.mark.django_db
def test_detail_reports_is_expired_false_for_future_expiry():
    user = _make_user("live-owner")
    quote = _make_eligible_quote(user)
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(_url(quote.id))

    assert resp.status_code == 200
    assert resp.json()["is_expired"] is False
