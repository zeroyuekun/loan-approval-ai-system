from django.test import TestCase


class GuardrailTestCase(TestCase):
    def setUp(self):
        from apps.email_engine.services.guardrails import GuardrailChecker

        self.checker = GuardrailChecker()

    def test_passing_email(self):
        """A well-formed email should pass all checks."""
        body = """Dear John Smith,

We are pleased to advise that your Home Purchase loan application for $350,000.00 has been approved.

Interest Rate: 6.14% p.a. (Variable)
Comparison Rate: 6.45% p.a.*
Loan Term: 30 years
Monthly Repayment: $2,134.56

Next Steps:

Please review the attached loan agreement. To proceed:

  1. Sign and return your documents by 22 April 2026.
  2. Confirm your nominated bank account.
  3. Funds are typically in your account within 1\u20132 business days.

Before You Sign:

Take the time to read the full terms carefully, including fees.

If your circumstances have changed, please let us know. You are welcome to seek independent advice.

You will have access to a cooling-off period after signing.

If you experience financial difficulty, contact our Financial Hardship team on 1300 000 001 or aussieloanai@gmail.com.

Contact me at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or reply to this email.

Kind regards,
AussieLoanAI Lending Team

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
*Comparison rate of 6.45% p.a. applies only to the example given. Different amounts and terms will result in different comparison rates.

If unresolved, contact the Australian Financial Complaints Authority (AFCA) on 1800 931 678 or at www.afca.org.au.
"""
        context = {
            "applicant_name": "John Smith",
            "loan_amount": 350000.0,
            "purpose": "Home Purchase",
            "decision": "approved",
            "pricing": {
                "interest_rate": "6.14% p.a.",
                "comparison_rate": "6.45% p.a.",
                "monthly_payment": "$2,134.56",
                "monthly_payment_number": 2134.56,
                "loan_term_display": "30 years",
                "establishment_fee": "$600.00",
                "establishment_fee_number": 600.00,
            },
        }
        results = self.checker.run_all_checks(body, context)
        blocking_failures = [r for r in results if not r["passed"] and r.get("severity") != "warning"]
        # Should have no blocking failures
        self.assertEqual(
            len(blocking_failures),
            0,
            f"Unexpected failures: {[r['check_name'] + ': ' + r['details'] for r in blocking_failures]}",
        )

    def test_discrimination_language_detected(self):
        """Email containing discriminatory language should fail."""
        body = "Dear Customer, your loan was denied because of your age and gender."
        context = {
            "applicant_name": "Test",
            "loan_amount": 100000.0,
            "purpose": "Personal",
            "decision": "denied",
        }
        results = self.checker.run_all_checks(body, context)
        failed_names = [r["check_name"] for r in results if not r["passed"]]
        # Should detect discrimination
        self.assertTrue(len(failed_names) > 0, "Expected guardrail failures for discriminatory language")


# ---------------------------------------------------------------------------
# Compliance gap tests (pytest-style)
# ---------------------------------------------------------------------------

class TestApologyLanguageGap:
    """EMAIL-LOW-1: No guardrail catches sorry/apologise — hard project rule."""

    def _make_checker(self):
        from apps.email_engine.services.guardrails import GuardrailChecker

        return GuardrailChecker()

    def test_sorry_caught_by_guardrails(self):
        """The word 'sorry' in a denial email should now be caught by the apology guardrail."""
        checker = self._make_checker()
        email_with_sorry = (
            "We're sorry to inform you that your loan application has been denied. "
            "Based on your credit score and debt-to-income ratio, we are unable to approve "
            "your application at this time. You can request a free copy of your credit report "
            "from Equifax. Contact AFCA on 1800 931 678 if you wish to lodge a complaint."
        )
        context = {"decision": "denied", "applicant_name": "Test", "loan_amount": 100000.0, "purpose": "Personal"}
        results = checker.run_all_checks(email_with_sorry, context)
        # After fix: "sorry" is now caught by AI_GIVEAWAY_TERMS
        failed = [r for r in results if not r["passed"] and "sorry" in r.get("details", "").lower()]
        assert len(failed) > 0, "Apology guardrail should now catch 'sorry'"

    def test_apologise_caught_by_guardrails(self):
        """The word 'apologise' should now be caught by the apology guardrail."""
        checker = self._make_checker()
        email_with_apologise = (
            "We apologise but your application could not be approved. "
            "Based on your income assessment, we are unable to offer this product. "
            "You can request a free credit report from Equifax. "
            "Contact AFCA on 1800 931 678."
        )
        context = {"decision": "denied", "applicant_name": "Test", "loan_amount": 100000.0, "purpose": "Personal"}
        results = checker.run_all_checks(email_with_apologise, context)
        failed = [r for r in results if not r["passed"] and "apolog" in r.get("details", "").lower()]
        assert len(failed) > 0, "Apology guardrail should now catch 'apologise'"


class TestUnfortunatelyFalsePass:
    """EMAIL-HIGH-1: 'unfortunately' falsely satisfies denial reason requirement."""

    def test_unfortunately_alone_fails_required_elements(self):
        """An email with only 'unfortunately' and no actual reason should now fail.

        EMAIL-HIGH-1 FIX: 'unfortunately' removed from the reason-phrase list.
        """
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        email = (
            "Unfortunately, we are unable to help you at this time. "
            "You can request a free credit report from Equifax. "
            "Contact AFCA on 1800 931 678."
        )
        context = {"decision": "denied", "applicant_name": "Test", "loan_amount": 100000.0, "purpose": "Personal"}
        results = checker.run_all_checks(email, context)
        required_elements = [r for r in results if r["check_name"] == "Required Elements"]
        # After fix: "unfortunately" no longer satisfies the reason requirement
        if required_elements:
            assert required_elements[0]["passed"] is False, (
                "Expected fail — 'unfortunately' alone is not a substantive reason"
            )


class TestMarketingUnsubscribeGap:
    """EMAIL-HIGH-5: No Spam Act 2003 unsubscribe check for marketing emails."""

    def test_marketing_email_without_unsubscribe_fails(self):
        """Marketing email with no unsubscribe link should now fail.

        EMAIL-HIGH-5 FIX: Spam Act 2003 unsubscribe check added.
        """
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        marketing_email = (
            "Great news! Based on your profile, we'd like to offer you our Premium Savings Account "
            "with a competitive 4.5% interest rate. This is a limited-time offer just for you. "
            "Reach out to us at 1300 123 456 to learn more."
        )
        context = {"decision": "approved", "applicant_name": "Test", "loan_amount": 100000.0, "purpose": "Personal"}
        results = checker.run_all_checks(marketing_email, context, email_type="marketing")
        unsubscribe_fails = [r for r in results if not r["passed"] and "unsubscribe" in r.get("details", "").lower()]
        assert len(unsubscribe_fails) > 0, "Unsubscribe check should now catch missing mechanism"


class TestNboDeclineLanguageConflict:
    """EMAIL-MEDIUM-1: NBO personalized_message contains 'unable to approve'
    which would be caught by check_no_decline_language."""

    def test_nbo_fallback_message_conflicts_with_decline_check(self):
        """The hardcoded NBO fallback message triggers the no-decline-language guardrail."""
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        # This is the hardcoded fallback from NextBestOfferGenerator.generate()
        # when there are no offers (next_best_offer.py lines 68-72)
        nbo_message = (
            "We appreciate your interest in banking with us. While we were unable "
            "to approve your application at this time, we have options to help you "
            "work toward your financial goals."
        )
        result = checker.check_no_decline_language(nbo_message)
        # "unable to approve" IS in the decline_phrases list, so this should fail
        assert result["passed"] is False, (
            "NBO hardcoded message contains 'unable to approve' which triggers "
            "check_no_decline_language — this creates a conflict if the message "
            "is used in a marketing email context"
        )
