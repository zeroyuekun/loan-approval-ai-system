"""The recommendation engine must assess serviceability with the same rules as
the underwriting engine that labels the training data.

It used to carry its own copy of the HEM table and income-shading constants,
and that copy drifted: no very-low / very-high income brackets, dependants
capped at 2 instead of 4, no state multiplier, and no tenure rules for
self-employed and casual income. The offers it computed for a denied
applicant were then sized against a different expense floor and a different
income figure than the ones the model was trained on.

Pure-function tests: CustomerSnapshot is built directly (``make_snapshot`` in
conftest.py), no database.
"""

import pytest


# CustomerSnapshot gets its HEM from UnderwritingEngine.get_hem, so comparing
# the two would compare a function with itself. These cases instead pin that
# every argument reaches the lookup, against values worked out by hand from
# HEM_TABLE x STATE_HEM_MULTIPLIER (truncated to whole dollars).
@pytest.mark.parametrize(
    "applicant_type, dependants, income, state, expected_hem",
    [
        # State multiplier: the same household in four states.
        ("single", 0, 90000.0, "NSW", 2357),  # mid 2050 x 1.15
        ("single", 0, 90000.0, "VIC", 2214),  # mid 2050 x 1.08
        ("single", 0, 90000.0, "SA", 1886),  # mid 2050 x 0.92
        ("single", 0, 90000.0, "QLD", 2050),  # mid 2050 x 1.00
        # Couple vs single, same income and state.
        ("couple", 0, 90000.0, "NSW", 3392),  # mid 2950 x 1.15
        # Dependants 3 and 4 have their own rows; 5+ uses the 4 row.
        ("couple", 3, 90000.0, "NSW", 4830),  # mid 4200 x 1.15
        ("single", 4, 150000.0, "QLD", 4300),  # high 4300 x 1.00
        ("single", 5, 50000.0, "TAS", 2835),  # low (4 row) 3150 x 0.90
        # The outer income brackets.
        ("single", 0, 30000.0, "QLD", 1400),  # very_low 1400 x 1.00
        ("couple", 2, 250000.0, "WA", 5460),  # very_high 5200 x 1.05
    ],
)
def test_hem_passes_household_income_and_state_to_the_lookup(
    make_snapshot, applicant_type, dependants, income, state, expected_hem
):
    snap = make_snapshot(
        annual_income=income,
        applicant_type=applicant_type,
        number_of_dependants=dependants,
        state=state,
    )
    assert snap.hem_expenses == expected_hem


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
def test_income_shading_applies_tenure_rules(make_snapshot, employment_type, employment_length, expected_shade):
    snap = make_snapshot(
        annual_income=120000.0,
        employment_type=employment_type,
        employment_length=employment_length,
    )
    assert snap.shaded_monthly_income == pytest.approx(120000.0 * expected_shade / 12)


def test_state_defaults_to_nsw_when_not_supplied(make_snapshot):
    # Callers that predate the state field still get the underwriting default.
    # The shared factory's defaults carry no ``state``.
    snap = make_snapshot()
    assert snap.state == "NSW"
    assert snap.hem_expenses == 2875  # single, no dependants, $120k (high 2500) x NSW 1.15


@pytest.mark.parametrize("has_hecs", [False, True])
def test_hecs_is_not_deducted_from_surplus(make_snapshot, has_hecs):
    # compute_approval leaves HECS/HELP out of the serviceability surplus (Big 4
    # policy from 30 Sept 2025), so an offer must not shrink for a HECS debt.
    snap = make_snapshot(
        annual_income=90000.0,
        has_hecs=has_hecs,
        debt_to_income=0.5,
        loan_amount=40000.0,
        monthly_expenses=1500.0,
        existing_credit_card_limit=0.0,
    )
    # 7500.00 shaded income (payg_permanent, 90000 / 12)
    # - 1482.33 tax (4288 + 0.30 x 45000 = 17788 a year)
    # - 2357.00 HEM (single, mid 2050 x NSW 1.15) over 1500 declared
    # -   36.00 existing debt (90000 x (0.5 - 40000 / 90000) = 5000, x 0.0072)
    assert snap.monthly_surplus == pytest.approx(3624.67, abs=0.01)
