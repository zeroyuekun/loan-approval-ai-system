"""Tests for email guardrail compliance checks."""

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

Important Information:
Under the National Consumer Credit Protection Act 2009, you have a 14-day cooling-off period.
For complaints, contact the Australian Financial Complaints Authority (AFCA) at www.afca.org.au.

*Comparison rate calculated on a secured loan of $150,000 over 25 years.

Kind regards,
AussieLoanAI Lending Team
"""
        context = {
            'applicant_name': 'John Smith',
            'loan_amount': 350000.0,
            'purpose': 'Home Purchase',
            'decision': 'approved',
            'pricing': {
                'interest_rate': '6.14% p.a.',
                'comparison_rate': '6.45% p.a.',
                'monthly_payment': '$2,134.56',
                'loan_term_display': '30 years',
                'establishment_fee': '$600.00',
            },
        }
        results = self.checker.run_all_checks(body, context)
        blocking_failures = [r for r in results if not r['passed'] and r.get('severity') != 'warning']
        # Should have no blocking failures
        self.assertEqual(len(blocking_failures), 0,
            f"Unexpected failures: {[r['check_name'] + ': ' + r['details'] for r in blocking_failures]}")

    def test_discrimination_language_detected(self):
        """Email containing discriminatory language should fail."""
        body = "Dear Customer, your loan was denied because of your age and gender."
        context = {
            'applicant_name': 'Test',
            'loan_amount': 100000.0,
            'purpose': 'Personal',
            'decision': 'denied',
        }
        results = self.checker.run_all_checks(body, context)
        failed_names = [r['check_name'] for r in results if not r['passed']]
        # Should detect discrimination
        self.assertTrue(len(failed_names) > 0, 'Expected guardrail failures for discriminatory language')
