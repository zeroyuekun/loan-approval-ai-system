"""L29 (OPTIONAL): maker/checker gate dispatcher for high-value overturns.

The pure dispatcher decides whether an officer overturn may proceed given the
loan amount, a threshold, the gate mode, and whether the officer has a verified
2FA device. Default mode is "off" (no behaviour change). Wiring tests exercise
the resolve endpoint in "2fa" mode.
"""

import pytest
from rest_framework.test import APIClient

from apps.loans.services.overturn_policy import (
    DEFAULT_MODE,
    evaluate_overturn_gate,
    normalize_overturn_mode,
)

# ---------------------------------------------------------------------------
# Pure dispatcher (no DB)
# ---------------------------------------------------------------------------


def test_default_mode_is_off():
    assert DEFAULT_MODE == "off"


def test_off_mode_allows_any_amount():
    gate = evaluate_overturn_gate(amount=500000, threshold=100000, mode="off", officer_has_2fa=False)
    assert gate["allowed"] is True


def test_below_threshold_allowed_regardless_of_mode():
    gate = evaluate_overturn_gate(amount=50000, threshold=100000, mode="2fa", officer_has_2fa=False)
    assert gate["allowed"] is True


def test_2fa_mode_blocks_high_value_without_verified_device():
    gate = evaluate_overturn_gate(amount=150000, threshold=100000, mode="2fa", officer_has_2fa=False)
    assert gate["allowed"] is False
    assert gate["reason"]


def test_2fa_mode_allows_with_verified_device():
    gate = evaluate_overturn_gate(amount=150000, threshold=100000, mode="2fa", officer_has_2fa=True)
    assert gate["allowed"] is True


def test_second_approver_mode_blocks_high_value():
    gate = evaluate_overturn_gate(amount=150000, threshold=100000, mode="second_approver", officer_has_2fa=True)
    assert gate["allowed"] is False
    assert gate["reason"]


def test_unknown_mode_collapses_to_off():
    assert normalize_overturn_mode("garbage") == "off"
    assert normalize_overturn_mode(None) == "off"


# ---------------------------------------------------------------------------
# Endpoint wiring (DB) — "2fa" mode
# ---------------------------------------------------------------------------


def _denied_app_with_review(django_user_model, amount=150000):
    from apps.loans.models import DecisionReview, LoanApplication, LoanDecision

    cust = django_user_model.objects.create_user(
        username="ovt_cust", password="x", role="customer", email="ovt_cust@x.com"
    )
    app = LoanApplication.objects.create(
        applicant=cust,
        annual_income=80000,
        credit_score=500,
        loan_amount=amount,
        debt_to_income=5,
        employment_length=2,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        status="denied",
    )
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="disagree")
    return cust, app, review


@pytest.mark.django_db
def test_resolve_overturn_blocked_without_2fa(django_user_model, settings):
    settings.DECISION_OVERTURN_GATE_MODE = "2fa"
    settings.DECISION_OVERTURN_THRESHOLD = 100000.0
    officer = django_user_model.objects.create_user(
        username="ovt_officer", password="x", role="officer", email="ovt_officer@x.com"
    )
    _cust, _app, review = _denied_app_with_review(django_user_model, amount=150000)

    client = APIClient()
    client.force_authenticate(officer)
    resp = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned"},
        format="json",
    )
    assert resp.status_code == 403
    review.refresh_from_db()
    assert review.status != "resolved"


@pytest.mark.django_db
def test_resolve_overturn_allowed_with_verified_2fa(django_user_model, settings):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    settings.DECISION_OVERTURN_GATE_MODE = "2fa"
    settings.DECISION_OVERTURN_THRESHOLD = 100000.0
    officer = django_user_model.objects.create_user(
        username="ovt_officer2", password="x", role="officer", email="ovt_officer2@x.com"
    )
    TOTPDevice.objects.create(user=officer, name="d", confirmed=True)
    _cust, _app, review = _denied_app_with_review(django_user_model, amount=150000)

    client = APIClient()
    client.force_authenticate(officer)
    resp = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned"},
        format="json",
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_resolve_overturn_default_off_allows_without_2fa(django_user_model, settings):
    # Default mode (off) must not change behaviour — overturn proceeds.
    settings.DECISION_OVERTURN_GATE_MODE = "off"
    officer = django_user_model.objects.create_user(
        username="ovt_officer3", password="x", role="officer", email="ovt_officer3@x.com"
    )
    _cust, _app, review = _denied_app_with_review(django_user_model, amount=150000)

    client = APIClient()
    client.force_authenticate(officer)
    resp = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned"},
        format="json",
    )
    assert resp.status_code == 200
