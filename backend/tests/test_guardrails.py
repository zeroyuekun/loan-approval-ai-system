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

    def test_apology_language_blocked_in_denial(self):
        """Denial emails must never contain apology/sorry/regret language.

        This is the project's explicit red line (CLAUDE.md). The LLM prompt
        forbids it, but the deterministic regex is the authoritative safety
        net — if Claude ever drifts from the prompt the guardrail must catch
        it before the email ships.
        """
        context = {
            "applicant_name": "Test",
            "loan_amount": 100000.0,
            "purpose": "Personal",
            "decision": "denied",
        }
        offending_phrases = [
            "We are sorry to inform you",
            "We apologise for this outcome",
            "We apologize that your application was not approved",
            "Our apologies for the decision",
            "We understand your disappointment",
            "We regret that we cannot proceed",
        ]
        for phrase in offending_phrases:
            body = f"Dear Customer, {phrase}. Contact us on 1300 000 000."
            results = self.checker.run_all_checks(body, context)
            failed = [r for r in results if not r["passed"] and r.get("severity") != "warning"]
            self.assertTrue(
                len(failed) > 0,
                f"Expected guardrail failure for apology phrase: {phrase!r}",
            )
