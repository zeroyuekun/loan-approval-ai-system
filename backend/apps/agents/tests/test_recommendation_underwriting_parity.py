"""The recommendation engine must assess serviceability with the same rules as
the underwriting engine that labels the training data.

It used to carry its own copy of the HEM table and income-shading constants,
and that copy drifted: no very-low / very-high income brackets, dependants
capped at 2 instead of 4, no state multiplier, and no tenure rules for
self-employed and casual income. The offers it computed for a denied
applicant were then sized against a different expense floor and a different
income figure than the ones the model was trained on.

Pure-function tests: CustomerSnapshot is built directly, no database.
"""

import pytest

from apps.agents.services.recommendation_engine import CustomerSnapshot
from apps.ml_engine.services.datagen.underwriting_engine import UnderwritingEngine


def _snapshot(**overrides):
    base = dict(
        annual_income=90000.0,
        credit_score=720,
        loan_amount=30000.0,
        loan_term_months=60,
        debt_to_income=0.5,
        employment_type="payg_permanent",
        employment_length=5,
        applicant_type="single",
        number_of_dependants=0,
        purpose="personal",
        home_ownership="rent",
        property_value=0.0,
        deposit_amount=0.0,
        monthly_expenses=0.0,
        existing_credit_card_limit=0.0,
        has_cosigner=False,
        has_hecs=False,
        has_bankruptcy=False,
        state="NSW",
    )
    base.update(overrides)
    return CustomerSnapshot(**base)


# One income inside each of the five HEM brackets (<45k, <60k, <120k, <180k, 180k+).
INCOMES = [30000.0, 50000.0, 90000.0, 150000.0, 250000.0]
STATES = sorted(UnderwritingEngine.STATE_HEM_MULTIPLIER)


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("dependants", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("applicant_type", ["single", "couple"])
@pytest.mark.parametrize("income", INCOMES)
def test_hem_matches_underwriting_engine(income, applicant_type, dependants, state):
    snap = _snapshot(
        annual_income=income,
        applicant_type=applicant_type,
        number_of_dependants=dependants,
        state=state,
    )
    expected = UnderwritingEngine().get_hem(applicant_type, dependants, income, state)
    assert snap.hem_expenses == expected


@pytest.mark.parametrize(
    "employment_type, employment_length, expected_shade",
    [
        ("payg_permanent", 0, 1.00),
        ("contract", 3, 0.85),
        ("self_employed", 0, 0.65),
        ("self_employed", 1, 0.75),
        ("self_employed", 2, 0.82),
        ("payg_casual", 0, 0.60),
        ("payg_casual", 1, 0.80),
        ("payg_casual", 2, 1.00),
    ],
)
def test_income_shading_applies_tenure_rules(employment_type, employment_length, expected_shade):
    snap = _snapshot(
        annual_income=120000.0,
        employment_type=employment_type,
        employment_length=employment_length,
    )
    assert snap.shaded_monthly_income == pytest.approx(120000.0 * expected_shade / 12)


def test_state_defaults_to_nsw_when_not_supplied():
    # Callers that predate the state field still get the underwriting default.
    snap_kwargs = dict(
        annual_income=90000.0,
        credit_score=720,
        loan_amount=30000.0,
        loan_term_months=60,
        debt_to_income=0.5,
        employment_type="payg_permanent",
        employment_length=5,
        applicant_type="single",
        number_of_dependants=0,
        purpose="personal",
        home_ownership="rent",
        property_value=0.0,
        deposit_amount=0.0,
        monthly_expenses=0.0,
        existing_credit_card_limit=0.0,
        has_cosigner=False,
        has_hecs=False,
        has_bankruptcy=False,
    )
    snap = CustomerSnapshot(**snap_kwargs)
    assert snap.hem_expenses == UnderwritingEngine().get_hem("single", 0, 90000.0, "NSW")
