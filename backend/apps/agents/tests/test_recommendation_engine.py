"""Direct unit tests for RecommendationEngine product evaluators.

Builds a CustomerSnapshot directly (no DB; ``make_snapshot`` lives in
conftest.py) and asserts deterministic term selection. Guards the L19
affordability-constraint fix for unsecured personal.
"""

from apps.agents.services.recommendation_engine import (
    RecommendationEngine,
    _monthly_repayment,
)


class TestUnsecuredPersonalTermSelection:
    def test_high_surplus_picks_a_shorter_affordable_term_not_always_60(self, make_snapshot):
        """With strong surplus, the engine must pick a term shorter than 60
        when a shorter term's repayment still fits the affordability cap."""
        eng = RecommendationEngine()
        s = make_snapshot(annual_income=200000.0, monthly_expenses=1000.0)
        rec = eng._evaluate_unsecured_personal(s)
        assert rec is not None
        # The dead loop always returned 60; a real constraint must allow < 60.
        assert rec.term_months in (12, 24, 36, 60)
        assert rec.term_months < 60

    def test_term_is_affordable_under_the_cap(self, make_snapshot):
        """Whatever term is chosen, its repayment must be <= the affordability
        cap (15% of monthly income), unless no term fits and we fall back to 60."""
        eng = RecommendationEngine()
        s = make_snapshot(annual_income=200000.0, monthly_expenses=1000.0)
        rec = eng._evaluate_unsecured_personal(s)
        cap = (s.annual_income / 12) * 0.15
        rep = _monthly_repayment(rec.amount, rec.estimated_rate, rec.term_months)
        assert rep <= cap + 0.01

    def test_tight_surplus_falls_back_to_longest_term_60(self, make_snapshot):
        """When even the smallest repayment (longest term) exceeds the cap,
        the engine falls back to the longest available term (60)."""
        eng = RecommendationEngine()
        # Low income relative to a borderline-eligible amount: no term fits the
        # cap, so the most affordable (longest) term must be chosen.
        s = make_snapshot(annual_income=70000.0, monthly_expenses=1800.0)
        rec = eng._evaluate_unsecured_personal(s)
        if rec is not None:
            assert rec.term_months == 60

    def test_fallback_resize_respects_the_15pct_of_gross_ceiling(self, make_snapshot):
        """When no term fits and the loop falls back to 60 months, the re-size
        must use the same min(15% of gross, surplus) cap the loop enforced.
        Sized against raw surplus, this snapshot is quoted the $50,000 catalog
        maximum at about $1,087/month, well above its $750/month cap."""
        eng = RecommendationEngine()
        # Gross $5,000/mo -> 15% cap = $750; surplus ~ $2,218 (> cap).
        s = make_snapshot(annual_income=60000.0, monthly_expenses=1000.0, credit_score=720)
        rec = eng._evaluate_unsecured_personal(s)
        assert rec is not None
        assert rec.term_months == 60
        cap = min(0.15 * s.annual_income / 12, s.monthly_surplus)
        assert rec.monthly_repayment <= cap + 0.01, (
            f"quoted ${rec.monthly_repayment:,.2f}/mo exceeds the repayment cap ${cap:,.2f}/mo"
        )


class TestSecuredPersonalServiceability:
    """Guards the M19-parity fix for secured personal loans (review #3). The
    secured offer used to size max_amount for a 60-month horizon but quote the
    repayment at the chosen (possibly shorter) term, so the quote could exceed
    the customer's demonstrated serviceable surplus. After the fix max_amount is
    re-sized at the selected term, so repayment <= surplus in every case."""

    def test_repayment_never_exceeds_serviceable_surplus(self, make_snapshot):
        eng = RecommendationEngine()
        # High income (a short term fits the 15%-of-gross ceiling) + ample
        # savings (the savings cap doesn't bind) — the exact shape that made the
        # old code quote a short-term repayment above the demonstrated surplus.
        s = make_snapshot(
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

    def test_term_84_resize_respects_the_15pct_of_gross_ceiling(self, make_snapshot):
        """Guards the delta-sweep S1-F2 fix. When the term loop selects 84
        months, the re-size must use the SAME target_repayment cap the loop
        enforced (min(15% of gross, surplus)) — not the raw surplus. With raw
        surplus the re-sized amount's repayment breaches the 15%-of-gross leg
        whenever surplus > 15% of gross at a non-premium tier (the premium
        tier escapes only via the $100k catalog ceiling)."""
        eng = RecommendationEngine()
        # Gross $10,000/mo -> 15% cap = $1,500; surplus ~ $1,800.67 (> cap, so
        # the gross leg binds); subprime tier (9.99%) so only term 84 fits the
        # target; savings ample so the 90%-of-savings cap never binds.
        s = make_snapshot(
            annual_income=120_000.0,
            monthly_expenses=5_823.0,
            savings_balance=115_000.0,
            credit_score=660,
        )
        rec = eng._evaluate_secured_personal(s)
        assert rec is not None
        # Prove the breach path is exercised: the 84-month term was selected.
        assert rec.term_months == 84
        cap = min(0.15 * s.annual_income / 12, s.monthly_surplus)
        assert rec.monthly_repayment <= cap + 0.01, (
            f"quoted ${rec.monthly_repayment:,.2f}/mo exceeds the repayment cap ${cap:,.2f}/mo"
        )

    def test_quoted_repayment_is_internally_consistent_with_amount_and_term(self, make_snapshot):
        eng = RecommendationEngine()
        s = make_snapshot(
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
