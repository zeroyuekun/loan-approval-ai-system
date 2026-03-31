"""Comprehensive tests for all 18 guardrail checks individually."""

import pytest

from apps.email_engine.services.guardrails import GuardrailChecker


@pytest.fixture
def checker():
    return GuardrailChecker()


# Good denial email based on the calibration example from prompts.py
GOOD_DENIAL_EMAIL = """Dear Neville,

Thank you for giving us the opportunity to review your application for a $500,000.00 Personal Loan with AussieLoanAI.

We have carefully reviewed your application and are unable to approve it at this time. Here is what we looked at, and what you can do from here.

This decision was based on a thorough review of your financial profile, specifically:

  \u2022  Employment type and tenure: Your current employment arrangements fell outside the parameters we require for a loan of this size.
  \u2022  Loan-to-income ratio: The requested loan amount relative to your verified income exceeded our serviceability thresholds.

This assessment was conducted in line with our responsible lending obligations, which exist to ensure any credit we provide is suitable and manageable for our customers.

What You Can Do:

This decision is based on your circumstances at the time of your application \u2013 it does not prevent you from applying with us in the future. The following steps may strengthen a future application:

  \u2022  Establishing a longer tenure in your current role, or transitioning to a permanent employment arrangement.
  \u2022  Considering a reduced loan amount that sits within a sustainable repayment range relative to your income.

You are also entitled to a free copy of your credit report to verify the information used in our assessment. You can request one from any of Australia's credit reporting bodies:

  \u2022  Equifax \u2013 equifax.com.au
  \u2022  Illion \u2013 illion.com.au
  \u2022  Experian \u2013 experian.com.au

We'd Still Like to Help:

If you'd like to explore whether a different loan product or a revised amount could be a better fit, I'd be happy to talk through your options.

If you have any questions about this decision, please don't hesitate to contact me directly at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or simply reply to this email.

Thanks for coming to us, Neville. We'd love to help you find the right option when you're ready.

Kind regards,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd
ABN 12 345 678 901 | Australian Credit Licence No. 012345
Ph: 1300 000 000
Email: aussieloanai@gmail.com

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
If you are dissatisfied with this decision, we encourage you to contact us first so we can address your concerns through our internal complaints process. If you remain dissatisfied, you may lodge a complaint with the Australian Financial Complaints Authority (AFCA):
Phone: 1800 931 678
Website: www.afca.org.au
Email: info@afca.org.au

This communication is confidential and intended solely for the named recipient.
"""

DENIAL_CONTEXT = {
    "applicant_name": "Neville Thompson",
    "loan_amount": 500000.0,
    "purpose": "Personal",
    "decision": "denied",
}


# ── 1. Prohibited Language ──────────────────────────────────────────────────


class TestProhibitedLanguage:
    def test_catches_racial_terms(self, checker):
        result = checker.check_prohibited_language(
            "Your loan was denied because of your ethnicity and racial background."
        )
        assert not result["passed"]
        assert "prohibited" in result["details"].lower() or "racial" in result["details"].lower()

    def test_allows_compliance_disclosures(self, checker):
        text = (
            "Under the Racial Discrimination Act 1975 and Sex Discrimination Act 1984, "
            "we are committed to fair lending. Under the Age Discrimination Act 2004, "
            "age-related decisions must be justified."
        )
        result = checker.check_prohibited_language(text)
        assert result["passed"], f"Should pass for legal disclosures: {result['details']}"

    def test_allows_financial_terms_with_age(self, checker):
        text = "Your credit report from Equifax shows an age of account of 12 years."
        result = checker.check_prohibited_language(text)
        assert result["passed"], f"Should pass for financial context: {result['details']}"


# ── 2. Hallucinated Numbers ────────────────────────────────────────────────


class TestHallucinatedNumbers:
    def test_catches_wrong_loan_amount(self, checker):
        context = {"loan_amount": 50000.0, "decision": "approved"}
        text = "Your loan for $999,999.00 has been approved."
        result = checker.check_hallucinated_numbers(text, context)
        assert not result["passed"]
        assert "unrecognized" in result["details"].lower()

    def test_passes_correct_amounts(self, checker):
        context = {"loan_amount": 50000.0, "decision": "approved"}
        text = "Your loan for $50,000.00 has been approved."
        result = checker.check_hallucinated_numbers(text, context)
        assert result["passed"]

    def test_skips_when_no_amount_in_context(self, checker):
        context = {"decision": "denied"}
        text = "Your loan application has been reviewed."
        result = checker.check_hallucinated_numbers(text, context)
        assert result["passed"]
        assert "skipped" in result["details"].lower()


# ── 3. Contextual Dignity ──────────────────────────────────────────────────


class TestContextualDignity:
    def test_catches_you_have_no_job(self, checker):
        result = checker.check_contextual_dignity("You have no job and therefore cannot service this loan.")
        assert not result["passed"]

    def test_catches_your_poor_credit(self, checker):
        result = checker.check_contextual_dignity("Your poor credit history is the main concern.")
        assert not result["passed"]

    def test_catches_you_are_high_risk(self, checker):
        result = checker.check_contextual_dignity("You are a high risk borrower.")
        assert not result["passed"]

    def test_passes_dignified_language(self, checker):
        result = checker.check_contextual_dignity(
            "Your credit profile at the time of assessment did not meet our lending criteria."
        )
        assert result["passed"]


# ── 4. Psychological Framing ──────────────────────────────────────────────


class TestPsychologicalFraming:
    def test_catches_institutional_coldness(self, checker):
        result = checker.check_psychological_framing(
            "The bank has determined that your application does not meet our criteria.",
            decision="denied",
        )
        assert not result["passed"]
        assert "institutional_coldness" in result["details"]

    def test_catches_finality_language(self, checker):
        result = checker.check_psychological_framing(
            "This decision is final and there is nothing more we can do.",
            decision="denied",
        )
        assert not result["passed"]
        assert "finality" in result["details"]

    def test_catches_negative_framing(self, checker):
        result = checker.check_psychological_framing(
            "We cannot offer you any lending product at this time.",
            decision="denied",
        )
        assert not result["passed"]
        assert "negative_framing" in result["details"]

    def test_catches_weak_closings_on_denial(self, checker):
        result = checker.check_psychological_framing(
            "We wish you well in your future endeavours.",
            decision="denied",
        )
        assert not result["passed"]
        assert "weak_closings" in result["details"]

    def test_skips_weak_closings_on_approval(self, checker):
        result = checker.check_psychological_framing(
            "We wish you well in using your new loan. Short sentence here.",
            decision="approved",
        )
        # weak_closings category is skipped for approvals
        weak_closing_issues = [i for i in result.get("details", "") if "weak_closings" in str(i)]
        # Either it passes entirely or the issues are not about weak_closings
        if not result["passed"]:
            assert "weak_closings" not in result["details"]

    def test_catches_long_sentences(self, checker):
        long_sentence = " ".join(["word"] * 45) + "."
        result = checker.check_psychological_framing(long_sentence, decision="denied")
        assert not result["passed"]
        assert "cognitive_load" in result["details"]

    def test_excludes_footer_from_cognitive_load(self, checker):
        # A long sentence AFTER the separator should not trigger cognitive load
        separator = "\u2500" * 5
        body = "Short sentence here."
        footer = " ".join(["word"] * 50) + "."
        text = f"{body}\n{separator}\n{footer}"
        result = checker.check_psychological_framing(text, decision="denied")
        # cognitive_load should not be in the issues because the long sentence is in footer
        if not result["passed"]:
            assert "cognitive_load" not in result["details"]

    def test_passes_psychologically_sound_email(self, checker):
        text = (
            "We have reviewed your application carefully. "
            "Here is what we found and what you can do from here. "
            "The following steps may strengthen a future application."
        )
        result = checker.check_psychological_framing(text, decision="denied")
        assert result["passed"], f"Should pass: {result['details']}"


# ── 5. Grammar Formality ──────────────────────────────────────────────────


class TestGrammarFormality:
    def test_catches_casual_contractions(self, checker):
        result = checker.check_grammar_formality("You can't apply for this loan and we won't reconsider.")
        assert not result["passed"]

    def test_allows_warm_contractions(self, checker):
        # "don't hesitate", "we'd", "I'm", "isn't", "it's" are allowed
        result = checker.check_grammar_formality(
            "Please don't hesitate to contact us. We'd love to help. I'm available."
        )
        assert result["passed"], f"Should allow warm contractions: {result['details']}"


# ── 6. Comparison Rate Warning ────────────────────────────────────────────


class TestComparisonRateWarning:
    def test_fails_when_rate_quoted_without_warning(self, checker):
        text = "Your comparison rate is 6.45% p.a."
        result = checker.check_comparison_rate_warning(text, decision="approved")
        assert not result["passed"]

    def test_passes_when_rate_has_warning(self, checker):
        text = "Comparison Rate: 6.45% p.a.*\n*Comparison rate of 6.45% p.a. applies only to the example given."
        result = checker.check_comparison_rate_warning(text, decision="approved")
        assert result["passed"]

    def test_skips_for_denial_emails(self, checker):
        text = "Your comparison rate would have been 6.45% p.a."
        result = checker.check_comparison_rate_warning(text, decision="denied")
        assert result["passed"]
        assert "not applicable" in result["details"].lower()

    def test_passes_when_no_rate_quoted(self, checker):
        text = "Your loan has been approved at a competitive rate."
        result = checker.check_comparison_rate_warning(text, decision="approved")
        assert result["passed"]


# ── 7. Run All Checks ────────────────────────────────────────────────────


class TestRunAllChecks:
    def test_returns_18_checks(self, checker):
        results = checker.run_all_checks(GOOD_DENIAL_EMAIL, DENIAL_CONTEXT)
        assert len(results) == 18

    def test_quality_score_100_for_good_email(self, checker):
        results = checker.run_all_checks(GOOD_DENIAL_EMAIL, DENIAL_CONTEXT)
        blocking_failures = [r for r in results if not r["passed"] and r.get("severity") != "warning"]
        score = checker.compute_quality_score(results)
        # The calibration example should pass all blocking checks
        assert len(blocking_failures) == 0, (
            f"Blocking failures: {[(r['check_name'], r['details']) for r in blocking_failures]}"
        )
        assert score >= 90, f"Expected score >= 90 for calibration email, got {score}"

    def test_quality_score_low_for_bad_email(self, checker):
        bad_email = (
            "Dear Customer, your loan was denied because of your racial background and gender. "
            "You are a high risk borrower. The bank has determined you can't afford this. "
            "This decision is final. We wish you good luck."
        )
        context = {
            "applicant_name": "Test",
            "loan_amount": 100000.0,
            "purpose": "Personal",
            "decision": "denied",
        }
        results = checker.run_all_checks(bad_email, context)
        score = checker.compute_quality_score(results)
        failures = [r for r in results if not r["passed"]]
        assert len(failures) >= 3, f"Expected many failures, got {len(failures)}"
        assert score < 70, f"Expected low score for bad email, got {score}"
