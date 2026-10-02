"""L29 (OPTIONAL): maker/checker gate dispatcher for high-value overturns.

The pure dispatcher decides whether an officer overturn may proceed given the
loan amount, a threshold and the gate mode. Default mode is "off" (no
behaviour change). Wiring tests exercise the resolve endpoint in
"second_approver" mode and with the legacy "2fa" value.
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
    assert evaluate_overturn_gate(amount=500000, threshold=100000, mode="off")["allowed"] is True


def test_below_threshold_allowed_regardless_of_mode():
    assert evaluate_overturn_gate(amount=50000, threshold=100000, mode="second_approver")["allowed"] is True


def test_second_approver_mode_blocks_high_value():
    gate = evaluate_overturn_gate(amount=150000, threshold=100000, mode="second_approver")
    assert gate["allowed"] is False
    assert gate["reason"]


def test_legacy_2fa_mode_maps_to_second_approver():
    # 2FA was removed. A deployment still configured with "2fa" must keep a
    # gate, so the value maps to the stricter remaining mode, never to "off".
    assert normalize_overturn_mode("2fa") == "second_approver"
    assert evaluate_overturn_gate(amount=150000, threshold=100000, mode="2fa")["allowed"] is False


def test_unknown_mode_collapses_to_off():
    assert normalize_overturn_mode("garbage") == "off"
    assert normalize_overturn_mode(None) == "off"


# ---------------------------------------------------------------------------
# Endpoint wiring (DB)
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


def _resolve_as_officer(django_user_model, username):
    officer = django_user_model.objects.create_user(
        username=username, password="x", role="officer", email=f"{username}@x.com"
    )
    _cust, _app, review = _denied_app_with_review(django_user_model, amount=150000)
    client = APIClient()
    client.force_authenticate(officer)
    resp = client.post(
        f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
        {"outcome": "overturned"},
        format="json",
    )
    review.refresh_from_db()
    return resp, review


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["second_approver", "2fa"])
def test_resolve_high_value_overturn_blocked(django_user_model, settings, mode):
    settings.DECISION_OVERTURN_GATE_MODE = mode
    settings.DECISION_OVERTURN_THRESHOLD = 100000.0
    resp, review = _resolve_as_officer(django_user_model, "ovt_officer")
    assert resp.status_code == 403
    assert review.status != "resolved"


@pytest.mark.django_db
def test_resolve_overturn_default_off_allows(django_user_model, settings):
    # Default mode (off) must not change behaviour — overturn proceeds.
    settings.DECISION_OVERTURN_GATE_MODE = "off"
    resp, _review = _resolve_as_officer(django_user_model, "ovt_officer3")
    assert resp.status_code == 200
