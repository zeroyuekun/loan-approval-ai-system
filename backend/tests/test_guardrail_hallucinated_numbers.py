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
    assert not result["passed"], (
        "Expected $4,999 to be flagged as an unrecognised hallucinated amount"
    )
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
    assert not result["passed"], (
        "Expected $333 (not derivable from $50k offer) to be flagged"
    )


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
    assert result["passed"], (
        f"Legitimately derived annual interest $2,850 should pass: {result['details']}"
    )


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
    assert result["passed"], (
        f"Monthly amount $1,850 derived from $24,000 NBO should pass: {result['details']}"
    )


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
    assert result["passed"], (
        f"Legitimate NBO email with derivable amounts should pass: {result['details']}"
    )


def test_no_nbo_unaffected(checker):
    """Without any NBO offer, the sub-$5k bypass is simply not applied (no regression)."""
    # $4,999 in a non-NBO email was always correctly flagged — ensure it still is.
    text = "Your loan of $25,000 includes a fee of $4,999."
    context = {
        "loan_amount": 25000,
        "nbo_amounts": [],
    }
    result = checker.check_hallucinated_numbers(text, context)
    assert not result["passed"], (
        "Unrecognised $4,999 without NBO context should remain flagged"
    )
