"""Integration tests for POST /api/v1/ml/quote/."""

import datetime
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile
from apps.ml_engine.models import QuoteLog

QUOTE_URL = "/api/v1/ml/quote/"


def _valid_request():
    return {
        "loan_amount": "25000.00",
        "loan_term_months": 60,
        "purpose": "personal",
        "annual_income": "80000.00",
        "employment_type": "payg_permanent",
        "employment_length": 5,
        "credit_score": 720,
        "monthly_expenses": "3000.00",
        "home_ownership": "rent",
        "state": "NSW",
        "debt_to_income": "0.25",
    }


@pytest.fixture
def authed_client():
    User = get_user_model()
    user = User.objects.create_user(username="quoter", password="quote-pass", role="customer")
    # min(day, 28) avoids Feb-29 edge case
    today = datetime.date.today()
    dob = datetime.date(today.year - 30, today.month, min(today.day, 28))
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.date_of_birth = dob.isoformat()
    profile.save()
    if hasattr(user, "_state") and "profile" in user._state.fields_cache:
        del user._state.fields_cache["profile"]
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
def test_quote_happy_path(authed_client):
    client, user = authed_client
    fake_prediction = {"probability": 0.05}  # Excellent band
    with patch("apps.ml_engine.services.predictor.ModelPredictor") as mock_cls:
        mock_cls.return_value.predict.return_value = fake_prediction
        resp = client.post(QUOTE_URL, _valid_request(), format="json")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["eligible_for_application"] is True
    assert body["indicative"] is True
    assert body["indicative_rate_range"]["min"] < body["indicative_rate_range"]["max"]
    assert body["estimated_monthly_repayment"] > 0
    assert len(body["top_rate_factors"]) > 0
    assert body["quote_id"]

    # Exactly one QuoteLog was created for this user.
    logs = QuoteLog.objects.filter(user=user)
    assert logs.count() == 1
    log = logs.first()
    assert log.eligible is True
    assert log.rate_min is not None and log.rate_max is not None


@pytest.mark.django_db
def test_quote_ineligible_when_age_over_67_at_maturity():
    User = get_user_model()
    user = User.objects.create_user(username="older-quoter", password="quote-pass", role="customer")
    today = datetime.date.today()
    dob = datetime.date(today.year - 65, today.month, min(today.day, 28))
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.date_of_birth = dob.isoformat()
    profile.save()
    # Invalidate any cached reverse-OneToOne profile on the user instance so
    # the view sees the freshly-saved DOB.
    if hasattr(user, "_state") and "profile" in user._state.fields_cache:
        del user._state.fields_cache["profile"]

    client = APIClient()
    client.force_authenticate(user=user)

    with patch("apps.ml_engine.services.predictor.ModelPredictor") as mock_cls:
        mock_cls.return_value.predict.side_effect = AssertionError("ML predictor should not be called when gate fails")
        resp = client.post(QUOTE_URL, _valid_request(), format="json")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["eligible_for_application"] is False
    assert body["indicative_rate_range"] is None
    assert body["ineligible_reason"]

    log = QuoteLog.objects.get(user=user)
    assert log.eligible is False
    assert log.rate_min is None


@pytest.mark.django_db
def test_quote_rejects_unauthenticated():
    client = APIClient()
    resp = client.post(QUOTE_URL, _valid_request(), format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_quote_rejects_invalid_purpose(authed_client):
    client, _ = authed_client
    body = _valid_request()
    body["purpose"] = "crypto"
    resp = client.post(QUOTE_URL, body, format="json")
    assert resp.status_code == 400
    assert "purpose" in resp.json()
