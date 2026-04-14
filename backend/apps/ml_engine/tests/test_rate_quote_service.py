"""Tests for RateQuoteService — rate band mapping, amortisation, top factors."""

from decimal import Decimal

import pytest

from apps.ml_engine.services.rate_quote_service import (
    BAND_EXCELLENT,
    BAND_STANDARD,
    BAND_SUB_PRIME,
    RateQuoteService,
)


@pytest.fixture
def service():
    return RateQuoteService()


def test_band_excellent_when_probability_below_0_08(service):
    band = service.band_for_probability(0.05)
    assert band == BAND_EXCELLENT


def test_band_standard_when_probability_between_0_08_and_0_20(service):
    band = service.band_for_probability(0.15)
    assert band == BAND_STANDARD


def test_band_sub_prime_when_probability_above_0_20(service):
    band = service.band_for_probability(0.35)
    assert band == BAND_SUB_PRIME


def test_band_boundary_at_0_20_maps_to_sub_prime(service):
    # Boundary rule: probability == 0.20 goes to the upper (worse) band.
    band = service.band_for_probability(0.20)
    assert band == BAND_SUB_PRIME


def test_amortisation_25k_60mo_8_375_percent(service):
    payment = service.amortised_monthly_payment(
        principal=Decimal("25000"), apr_percent=Decimal("8.375"), term_months=60
    )
    # Verified externally: P = 25000 * (r / (1 - (1+r)**-60)) with r = 0.08375/12
    # ~ 511.95. Allow +/-$1 tolerance for rounding.
    assert abs(payment - Decimal("511.95")) < Decimal("1.00"), payment


def test_top_factors_highlights_strong_credit_and_weak_dti(service):
    request_fields = {
        "credit_score": 820,
        "employment_length": 15,
        "debt_to_income": 0.5,
        "annual_income": 95000,
        "monthly_expenses": 2800,
        "loan_amount": 20000,
        "loan_term_months": 48,
    }
    factors = service.top_rate_factors(request_fields, n=3)
    names = [f["name"] for f in factors]
    assert "credit_score" in names
    assert "debt_to_income" in names
    cs = next(f for f in factors if f["name"] == "credit_score")
    dti = next(f for f in factors if f["name"] == "debt_to_income")
    assert cs["impact"] == "positive"
    assert dti["impact"] == "negative"
