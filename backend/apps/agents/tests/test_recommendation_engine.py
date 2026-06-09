"""Direct unit tests for RecommendationEngine product evaluators.

Builds a CustomerSnapshot directly (no DB) and asserts deterministic term
selection. Guards the L19 affordability-constraint fix for unsecured personal.
"""

from apps.agents.services.recommendation_engine import (
    CustomerSnapshot,
    RecommendationEngine,
    _monthly_repayment,
)


def _snapshot(**overrides):
    """A high-credit, high-surplus snapshot eligible for unsecured personal."""
    base = dict(
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
    base.update(overrides)
    return CustomerSnapshot(**base)


class TestUnsecuredPersonalTermSelection:
    def test_high_surplus_picks_a_shorter_affordable_term_not_always_60(self):
        """With strong surplus, the engine must pick a term shorter than 60
        when a shorter term's repayment still fits the affordability cap."""
        eng = RecommendationEngine()
        s = _snapshot(annual_income=200000.0, monthly_expenses=1000.0)
        rec = eng._evaluate_unsecured_personal(s)
        assert rec is not None
        # The dead loop always returned 60; a real constraint must allow < 60.
        assert rec.term_months in (12, 24, 36, 60)
        assert rec.term_months < 60

    def test_term_is_affordable_under_the_cap(self):
        """Whatever term is chosen, its repayment must be <= the affordability
        cap (15% of monthly income), unless no term fits and we fall back to 60."""
        eng = RecommendationEngine()
        s = _snapshot(annual_income=200000.0, monthly_expenses=1000.0)
        rec = eng._evaluate_unsecured_personal(s)
        cap = (s.annual_income / 12) * 0.15
        rep = _monthly_repayment(rec.amount, rec.estimated_rate, rec.term_months)
        assert rep <= cap + 0.01

    def test_tight_surplus_falls_back_to_longest_term_60(self):
        """When even the smallest repayment (longest term) exceeds the cap,
        the engine falls back to the longest available term (60)."""
        eng = RecommendationEngine()
        # Low income relative to a borderline-eligible amount: no term fits the
        # cap, so the most affordable (longest) term must be chosen.
        s = _snapshot(annual_income=70000.0, monthly_expenses=1800.0)
        rec = eng._evaluate_unsecured_personal(s)
        if rec is not None:
            assert rec.term_months == 60


class TestSecuredPersonalServiceability:
    """Guards the M19-parity fix for secured personal loans (review #3). The
    secured offer used to size max_amount for a 60-month horizon but quote the
    repayment at the chosen (possibly shorter) term, so the quote could exceed
    the customer's demonstrated serviceable surplus. After the fix max_amount is
    re-sized at the selected term, so repayment <= surplus in every case."""

    def test_repayment_never_exceeds_serviceable_surplus(self):
        eng = RecommendationEngine()
        # High income (a short term fits the 15%-of-gross ceiling) + ample
        # savings (the savings cap doesn't bind) — the exact shape that made the
        # old code quote a short-term repayment above the demonstrated surplus.
        s = _snapshot(
            annual_income=240000.0,
            monthly_expenses=2000.0,
            savings_balance=120000.0,
            credit_score=780,
        )
        rec = eng._evaluate_secured_personal(s)
        assert rec is not None
        assert rec.monthly_repayment <= s.monthly_surplus + 0.01, (
            f"quoted ${rec.monthly_repayment:,.0f}/mo exceeds serviceable surplus ${s.monthly_surplus:,.0f}/mo"
        )

    def test_quoted_repayment_is_internally_consistent_with_amount_and_term(self):
        eng = RecommendationEngine()
        s = _snapshot(
            annual_income=300000.0,
            monthly_expenses=2000.0,
            savings_balance=200000.0,
            credit_score=800,
        )
        rec = eng._evaluate_secured_personal(s)
        assert rec is not None
        recomputed = _monthly_repayment(rec.amount, rec.estimated_rate, rec.term_months)
        assert abs(recomputed - rec.monthly_repayment) < 0.01
        assert rec.monthly_repayment <= s.monthly_surplus + 0.01
