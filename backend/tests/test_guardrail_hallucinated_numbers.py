"""FIX-4 — Guardrail hallucinated-numbers: tightened NBO sub-threshold bypass.

Previously any dollar figure < $5,000 in an NBO email was unconditionally
whitelisted.  The fix replaces this with a computed-band check: a value is
only allowed if it is within ±10 % of an amount plausibly derivable from a
real NBO offer (principal × rate, ÷ 12, ÷ 26).

Tests assert:
  (a) A fabricated sub-$5k amount unrelated to any NBO offer is NOW FLAGGED.
  (b) A legitimately derived small amount (annual interest = principal × rate)
      still PASSES.
  (c) The prior passing-email regression continues to pass (no false positives
      on legitimate amounts).
"""

import pytest

from apps.email_engine.services.guardrails import GuardrailChecker


@pytest.fixture
def checker():
    return GuardrailChecker()


# ---------------------------------------------------------------------------
# (a) Fabricated amount: unrelated sub-$5k value is flagged
# ---------------------------------------------------------------------------


def test_fabricated_sub5k_amount_is_flagged(checker):
    """$4,999 that has no derivable relationship to the NBO offer must be flagged."""
    # NBO offer: $20,000 principal.  Plausible derived amounts include:
    #   annual interest (20000 × 0.30 = $6,000) → monthly $500 / fortnightly ~$231
    #   monthly principal ($20,000 / 12 ≈ $1,667)
    # $4,999 is not within ±10 % of any of these.
    text = "We can offer you a loan of $20,000. A fee of $4,999 applies."
    context = {
        "loan_amount": 20000,
        "nbo_amounts": [20000],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert not result["passed"], "Expected $4,999 to be flagged as an unrecognised hallucinated amount"
    assert "4,999" in result["details"] or "4999" in result["details"], result["details"]


def test_completely_invented_small_amount_flagged(checker):
    """$333 that cannot be derived from any NBO figure must be flagged."""
    # NBO offer: $50,000.  Plausible derived amounts and their ±10% bands:
    #   annual interest (max 30%): $15,000  → band $13,500–$16,500
    #   monthly interest:          $1,250   → band $1,125–$1,375
    #   fortnightly interest:      ~$577    → band $519–$635
    #   monthly principal:         $4,167   → band $3,750–$4,583
    #   fortnightly principal:     $1,923   → band $1,731–$2,115
    # $333 is well outside all of these bands.
    text = "Alternative offer: $50,000 loan. Processing surcharge: $333."
    context = {
        "loan_amount": 50000,
        "nbo_amounts": [50000],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert not result["passed"], "Expected $333 (not derivable from $50k offer) to be flagged"


# ---------------------------------------------------------------------------
# (b) Legitimately derived small amounts still pass
# ---------------------------------------------------------------------------


def test_annual_interest_passess(checker):
    """Annual interest amount (principal × rate) is within the derived band."""
    # NBO offer: $32,500. At 5% rate, annual interest = $1,625.
    # $1,625 is within ±10 % of (32,500 × 0.30 / 12 × some sub-path?
    # More direct: $32,500 / 12 ≈ $2,708; $32,500 * 0.30 = $9,750 / 12 = $812.50.
    # $1,625 is not auto-derivable from the ±10% band of (32500 × 0.30) / 12 = $812.
    # Let's use a clear case: NBO $10,000. Annual interest max = $3,000.
    # $2,850 is within ±10% of $3,000 → should pass.
    text = "With a $10,000 loan at 28.5% p.a., your annual interest is $2,850."
    context = {
        "loan_amount": 10000,
        "nbo_amounts": [10000],
        "pricing": {
            "interest_rate_number": 28.5,
            "comparison_rate_number": 29.0,
        },
    }
    result = checker.check_hallucinated_numbers(text, context)
    # $2,850 must be within ±10% of $3,000 (10000 × 0.30) → allowed
    assert result["passed"], f"Legitimately derived annual interest $2,850 should pass: {result['details']}"


def test_monthly_repayment_derived_from_nbo_passes(checker):
    """A monthly repayment figure derivable from the NBO principal ÷ 12 passes."""
    # NBO: $24,000. Monthly principal = $2,000. A value of $1,850 is within ±10%.
    text = "Your alternative loan of $24,000 costs around $1,850/month."
    context = {
        "loan_amount": 24000,
        "nbo_amounts": [24000],
    }
    result = checker.check_hallucinated_numbers(text, context)
    # $1,850 vs $2,000 = 7.5% difference → within 10% → should pass
    assert result["passed"], f"Monthly amount $1,850 derived from $24,000 NBO should pass: {result['details']}"


def test_exact_nbo_amount_always_passes(checker):
    """The NBO offer principal itself must always be a valid amount."""
    text = "You may qualify for a $15,000 personal loan."
    context = {
        "loan_amount": 20000,
        "nbo_amounts": [15000],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert result["passed"], f"Exact NBO amount should pass: {result['details']}"


# ---------------------------------------------------------------------------
# (c) No false positives — existing passing email still passes
# ---------------------------------------------------------------------------


def test_no_false_positive_on_passing_nbo_email(checker):
    """Full NBO email with legitimate amounts produces no blocking failures."""
    # Amounts: $25,000 (original), $15,000 (NBO), $625/month (derived: 15000/12 ≈ 1250 - no,
    # let's use $1,100 which is within 10% of 15000/12 = 1250 actually not.
    # Use $1,200 which is within 10% of $1,250 (15000/12).
    text = (
        "Dear Customer, your $25,000 application has been reviewed. "
        "We're pleased to offer you an alternative: a $15,000 loan at around $1,200/month."
    )
    context = {
        "loan_amount": 25000,
        "nbo_amounts": [15000],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert result["passed"], f"Legitimate NBO email with derivable amounts should pass: {result['details']}"


def test_no_nbo_unaffected(checker):
    """Without any NBO offer, the sub-$5k bypass is simply not applied (no regression)."""
    # $4,999 in a non-NBO email was always correctly flagged — ensure it still is.
    text = "Your loan of $25,000 includes a fee of $4,999."
    context = {
        "loan_amount": 25000,
        "nbo_amounts": [],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert not result["passed"], "Unrecognised $4,999 without NBO context should remain flagged"


# ---------------------------------------------------------------------------
# (d) Delta-sweep S1-F1 — real-rate-derived references from context
#
# The 30%-band derivations alone reject CORRECT interest figures computed at
# each offer's actual estimated_rate (4.50–12.49% catalogue range), which the
# marketing prompt explicitly hands to the LLM.  The caller supplies the
# offers as `nbo_offers` and the checker must accept interest derived at each
# offer's actual rate (annual/monthly/fortnightly, ±10 %).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "rate", "text"),
    [
        # 20000 × 0.049 = 980 (annual), 81.67 (monthly), 37.69 (fortnightly).
        # None of these fall in the 30%-band derivations (annual $6,000 band
        # $5,400–$6,600; P/12 $1,667 band $1,500–$1,833; P/26 $769 band $692–$846).
        (20000, 4.90, "With our $20,000 offer, you could save around $980 in interest over the first year."),
        # $2,997/yr exceeds the P/12 band ceiling ($2,750).
        (30000, 9.99, "A $30,000 consolidation loan would cost about $2,997 in interest for the first year."),
    ],
    ids=["low-rate", "mid-rate"],
)
def test_interest_at_actual_rate_passes_with_offer_rates(checker, amount, rate, text):
    """Interest that is correct at the offer's actual rate, but outside the
    30%-band derivations, must pass when the caller passes the offer with its rate."""
    context = {
        "loan_amount": amount,
        "nbo_amounts": [amount],
        "nbo_offers": [{"amount": amount, "estimated_rate": rate}],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert result["passed"], f"Correct interest at the offer's actual {rate}% rate should pass: {result['details']}"


def test_fabricated_amount_still_flagged_with_offer_rates(checker):
    """Regression: a figure matching neither the offer-rate references nor
    the 30%-band derivations is still flagged."""
    # $7,777 vs offer-rate refs {980, 81.67, 37.69} and 30%-band refs
    # {6000, 500, 230.77, 1666.67, 769.23} — outside every ±10 % band.
    text = "Your $20,000 offer comes with a bonus of $7,777."
    context = {
        "loan_amount": 20000,
        "nbo_amounts": [20000],
        "nbo_offers": [{"amount": 20000, "estimated_rate": 4.90}],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert not result["passed"], "Fabricated $7,777 must remain flagged even with offer rates"
    assert "7,777" in result["details"] or "7777" in result["details"], result["details"]


def test_offers_without_amount_or_rate_ignored(checker):
    """Offers without a usable amount/rate are skipped, valid ones still apply."""
    text = "You could save around $980 in interest in the first year on a $20,000 loan."
    context = {
        "loan_amount": 20000,
        "nbo_amounts": [20000],
        "nbo_offers": [
            {"amount": 2000},  # no rate
            {"estimated_rate": 4.75},  # no amount
            {"amount": "bad", "estimated_rate": "data"},
            None,
            {"amount": 20000, "estimated_rate": 4.90},
        ],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert result["passed"], f"Valid offer should still apply: {result['details']}"


_GOAL_SAVER = {
    "amount": None,
    "estimated_rate": 5.20,
    "benefit": (
        "Goal Saver account at 5.20% p.a. bonus rate – save $100/month to strengthen "
        "your next application (~$62 interest in 12 months)"
    ),
}


def test_figures_stated_in_offer_benefit_pass(checker):
    """The recommendation engine writes figures into an offer's benefit text
    (Goal Saver has no principal), so the email quoting them is not inventing them."""
    text = "Goal Saver account at 5.20% p.a. - save $100/month (~$62 interest in 12 months)."
    context = {
        "loan_amount": 50000,
        "nbo_amounts": [85000],
        "nbo_offers": [{"amount": 85000, "estimated_rate": 5.00}, _GOAL_SAVER],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert result["passed"], result["details"]


def test_fabricated_amount_flagged_despite_offer_benefit(checker):
    """Only the figures in the benefit text are accepted, not any small amount."""
    text = "Goal Saver account - save $100/month and earn a $450 bonus."
    context = {"loan_amount": 50000, "nbo_amounts": [], "nbo_offers": [_GOAL_SAVER]}
    result = checker.check_hallucinated_numbers(text, context)
    assert not result["passed"]
    assert "$450" in result["details"], result["details"]


# ---------------------------------------------------------------------------
# I7 — rate validation: no whole-line keyword skips; denial / NBO rates checked
# ---------------------------------------------------------------------------

_PRICING = {"interest_rate_number": 7.49, "comparison_rate_number": 7.89}


def test_rate_on_a_line_mentioning_income_is_still_checked(checker):
    """A broad word such as "income" used to exempt the whole line."""
    text = "Based on your income, your interest rate is 12.99% p.a."
    result = checker.check_hallucinated_numbers(
        text, {"loan_amount": 20000, "decision": "approved", "pricing": _PRICING}
    )
    assert not result["passed"]
    assert "12.99" in result["details"]


def test_correct_rate_next_to_income_passes(checker):
    text = "Based on your income, your interest rate is 7.49% p.a. (comparison rate 7.89% p.a.)."
    result = checker.check_hallucinated_numbers(
        text, {"loan_amount": 20000, "decision": "approved", "pricing": _PRICING}
    )
    assert result["passed"], result["details"]


def test_disclaimer_percentages_stay_exempt(checker):
    text = (
        "Repayments above 30% of your income are not assessed as affordable.\n"
        "A deposit of 20% avoids LMI, and an 80% LVR applies.\n"
        "Your interest rate is 7.49% p.a."
    )
    result = checker.check_hallucinated_numbers(
        text, {"loan_amount": 20000, "decision": "approved", "pricing": _PRICING}
    )
    assert result["passed"], result["details"]


def test_denial_teaser_rate_validated_against_offer(checker):
    ctx = {
        "loan_amount": 20000,
        "decision": "denied",
        "nbo_amounts": [5000],
        "nbo_offers": [{"amount": 5000, "estimated_rate": 7.49}],
    }
    bad = checker.check_hallucinated_numbers("You may qualify for $5,000 at 3.10% p.a.", ctx)
    assert not bad["passed"] and "3.10" in bad["details"]
    good = checker.check_hallucinated_numbers("You may qualify for $5,000 at 7.49% p.a.", ctx)
    assert good["passed"], good["details"]


def test_denial_without_offer_cannot_quote_a_rate(checker):
    result = checker.check_hallucinated_numbers(
        "A smaller loan could be offered at 12.99% p.a.", {"loan_amount": 20000, "decision": "denied"}
    )
    assert not result["passed"]


def test_decision_email_path_passes_offer_rates_to_guardrails(sample_application):
    """S1-F1: the decision email passed nbo_amounts but not nbo_offers."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from apps.email_engine.services.email_generator import EmailGenerator

    seen = {}
    gen = EmailGenerator()
    gen.client = object()
    real = gen.guardrail_checker.run_all_checks

    def _spy(body, context, **kw):
        seen.update(context)
        return real(body, context, **kw)

    gen.guardrail_checker.run_all_checks = _spy
    offer = {"name": "Secured Loan", "amount": 5000, "estimated_rate": 7.49}
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"subject": "S", "body": "B"})], usage=None, stop_reason="x"
    )
    with (
        patch("apps.agents.services.api_budget.ApiBudgetGuard.check_budget"),
        patch("apps.agents.services.api_budget.guarded_api_call", return_value=resp),
        patch.object(EmailGenerator, "MAX_RETRIES", 1),
    ):
        gen.generate(sample_application, "denied", profile_context={"nbo_offer": offer})
    assert seen.get("nbo_offers") == [offer]
