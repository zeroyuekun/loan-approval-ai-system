import pytest

from apps.agents.services.recommendation_engine import CustomerSnapshot

# A high-credit, high-surplus applicant eligible for unsecured personal.
# No ``state``: the snapshot's own default (NSW) applies unless a test sets one.
SNAPSHOT_DEFAULTS = dict(
    annual_income=120000.0,
    credit_score=780,
    loan_amount=40000.0,
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
    monthly_expenses=1500.0,
    existing_credit_card_limit=0.0,
    has_cosigner=False,
    has_hecs=False,
    has_bankruptcy=False,
)


@pytest.fixture
def make_snapshot():
    """Build a CustomerSnapshot (no database) from SNAPSHOT_DEFAULTS plus overrides."""

    def _make(**overrides):
        return CustomerSnapshot(**{**SNAPSHOT_DEFAULTS, **overrides})

    return _make
