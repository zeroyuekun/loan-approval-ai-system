"""Guardrail unit tests — pure-Python, no DB dependency.

Converted off django.test.TestCase since GuardrailChecker is stateless and
does not touch the database. Matches the pattern in
test_guardrails_comprehensive.py.
"""

import pytest


@pytest.fixture
def checker():
    from apps.email_engine.services.guardrails import GuardrailChecker

    return GuardrailChecker()


class TestGuardrails:
    def test_passing_email(self, checker):
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
        results = checker.run_all_checks(body, context)
        blocking_failures = [r for r in results if not r["passed"] and r.get("severity") != "warning"]
        assert len(blocking_failures) == 0, (
            f"Unexpected failures: {[r['check_name'] + ': ' + r['details'] for r in blocking_failures]}"
        )

    def test_discrimination_language_detected(self, checker):
        """Email containing discriminatory language should fail."""
        body = "Dear Customer, your loan was denied because of your age and gender."
        context = {
            "applicant_name": "Test",
            "loan_amount": 100000.0,
            "purpose": "Personal",
            "decision": "denied",
        }
        results = checker.run_all_checks(body, context)
        failed_names = [r["check_name"] for r in results if not r["passed"]]
        assert len(failed_names) > 0, "Expected guardrail failures for discriminatory language"
