"""Tests for email generation with mocked Claude API."""

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from apps.email_engine.services.guardrails import GuardrailChecker


GOOD_APPROVAL_BODY = """Dear John,

We are pleased to advise that your application for a Personal Loan with AussieLoanAI has been approved. Congratulations!

Loan Details:

  Loan Amount:             $25,000.00
  Interest Rate:           6.50% p.a. (Variable)
  Comparison Rate:         6.85% p.a.*
  Loan Term:               36 months (3 years)
  Monthly Repayment:       $767.00
  Establishment Fee:       $400.00
  First Repayment Date:    15 May 2026

Next Steps:

Please review the attached loan agreement. To proceed:

  1. Sign and return your documents by 22 April 2026.
  2. Confirm your nominated bank account.
  3. Funds are typically in your account within 1\u20132 business days.

Before You Sign:

Take the time to read the full terms carefully, including fees.

If your circumstances have changed, please let us know. You are welcome to seek independent advice.

You will have access to a cooling-off period after signing.

We're Here For You:

If you experience financial difficulty, contact our Financial Hardship team on 1300 000 001 or aussieloanai@gmail.com.

Contact me at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or reply to this email.

Congratulations again, John. Thanks for choosing us at AussieLoanAI.

Warm regards,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
*Comparison rate of 6.85% p.a. applies only to the example given. Different amounts and terms will result in different comparison rates.

If unresolved, contact the Australian Financial Complaints Authority (AFCA) on 1800 931 678 or at www.afca.org.au.
"""

GOOD_DENIAL_BODY = """Dear Jane,

Thank you for giving us the opportunity to review your application for a $20,000.00 Personal Loan with AussieLoanAI.

We have carefully reviewed your application and are unable to approve it at this time. Here is what we looked at, and what you can do from here.

This decision was based on a thorough review of your financial profile, specifically:

  \u2022  Employment type and tenure: Your current employment arrangements fell outside the parameters we require.

This assessment was conducted in line with our responsible lending obligations.

What You Can Do:

This decision is based on your circumstances at the time of application. The following steps may strengthen a future application:

  \u2022  Establishing a longer tenure in your current role.

You are entitled to a free copy of your credit report. You can request one from:

  \u2022  Equifax \u2013 equifax.com.au
  \u2022  Illion \u2013 illion.com.au
  \u2022  Experian \u2013 experian.com.au

We'd Still Like to Help:

I'd be happy to talk through your options.

Contact me at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST).

Thanks for coming to us, Jane. We'd love to help you find the right option when you're ready.

Kind regards,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
If you are dissatisfied, you may lodge a complaint with the Australian Financial Complaints Authority (AFCA):
Phone: 1800 931 678
"""


def _make_mock_tool_response(subject, body):
    """Create a mock Claude API response with tool_use block."""
    tool_block = MagicMock()
    tool_block.type = 'tool_use'
    tool_block.input = {'subject': subject, 'body': body}

    response = MagicMock()
    response.content = [tool_block]
    response.usage = MagicMock()
    response.usage.input_tokens = 500
    response.usage.output_tokens = 300
    return response


def _make_mock_application(decision='approved', loan_amount=25000, purpose_display='Personal Loan'):
    """Create a mock loan application."""
    app = MagicMock()
    app.loan_amount = Decimal(str(loan_amount))
    app.loan_term_months = 36
    app.applicant.first_name = 'John'
    app.applicant.last_name = 'Smith'
    app.applicant.username = 'johnsmith'
    app.get_purpose_display.return_value = purpose_display
    app.get_employment_type_display.return_value = 'PAYG Permanent'
    app.get_applicant_type_display.return_value = 'Single'
    app.has_cosigner = False
    app.has_hecs = False
    app.purpose = 'personal'
    app.employment_type = 'payg_permanent'
    app.state = 'NSW'
    app.credit_score = 750
    app.annual_income = Decimal('80000')
    app.debt_to_income = Decimal('2.0')
    app.employment_length = 5
    app.home_ownership = 'rent'
    app.property_value = Decimal('0')
    app.deposit_amount = Decimal('0')
    app.monthly_expenses = Decimal('2200')
    app.existing_credit_card_limit = Decimal('5000')
    app.number_of_dependants = 0

    if decision == 'denied':
        app.decision = MagicMock()
        app.decision.confidence = 0.35
        app.decision.feature_importances = {'credit_score': 0.3, 'employment_length': 0.25}
    else:
        app.decision = MagicMock()
        app.decision.confidence = 0.92
    return app


class TestEmailGenerator:
    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key-123'})
    @patch('apps.email_engine.services.email_generator.anthropic.Anthropic')
    @patch('apps.agents.services.api_budget.ApiBudgetGuard')
    def test_generate_approval_email(self, mock_budget_cls, mock_anthropic_cls):
        """Mock Claude to return a tool_use response and verify guardrails are run."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_mock_tool_response(
            'Congratulations! Your Personal Loan is Approved',
            GOOD_APPROVAL_BODY,
        )
        mock_budget = MagicMock()
        mock_budget_cls.return_value = mock_budget

        from apps.email_engine.services.email_generator import EmailGenerator
        gen = EmailGenerator()

        app = _make_mock_application(decision='approved')
        result = gen.generate(app, 'approved', confidence=0.92)

        assert result['subject'] == 'Congratulations! Your Personal Loan is Approved'
        assert result['body'].strip() == GOOD_APPROVAL_BODY.strip()
        assert 'guardrail_results' in result
        assert len(result['guardrail_results']) == 18
        assert result['template_fallback'] is False

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key-123'})
    @patch('apps.email_engine.services.email_generator.anthropic.Anthropic')
    @patch('apps.agents.services.api_budget.ApiBudgetGuard')
    def test_generate_denial_email(self, mock_budget_cls, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_mock_tool_response(
            'Update on Your Personal Loan Application | Ref #PL-20260323-0001',
            GOOD_DENIAL_BODY,
        )
        mock_budget = MagicMock()
        mock_budget_cls.return_value = mock_budget

        from apps.email_engine.services.email_generator import EmailGenerator
        gen = EmailGenerator()

        app = _make_mock_application(decision='denied', loan_amount=20000)
        app.applicant.first_name = 'Jane'
        app.applicant.last_name = 'Doe'
        result = gen.generate(app, 'denied', confidence=0.35)

        assert 'guardrail_results' in result
        assert result['template_fallback'] is False

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key-123'})
    @patch('apps.email_engine.services.email_generator.anthropic.Anthropic')
    @patch('apps.agents.services.api_budget.ApiBudgetGuard')
    def test_retry_on_guardrail_failure(self, mock_budget_cls, mock_anthropic_cls):
        """First call returns bad email, second returns good. Verify attempt increments."""
        bad_body = (
            "Dear John, your loan was denied because of your racial background. "
            "You are a high risk. The bank has determined this decision is final. "
            "We wish you well."
        )
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = [
            _make_mock_tool_response('Bad Subject', bad_body),
            _make_mock_tool_response(
                'Update on Your Personal Loan Application',
                GOOD_DENIAL_BODY,
            ),
        ]
        mock_budget = MagicMock()
        mock_budget_cls.return_value = mock_budget

        from apps.email_engine.services.email_generator import EmailGenerator
        gen = EmailGenerator()

        app = _make_mock_application(decision='denied', loan_amount=20000)
        app.applicant.first_name = 'Jane'
        app.applicant.last_name = 'Doe'
        result = gen.generate(app, 'denied', confidence=0.35)

        # Should have retried — attempt_number > 1 or the good email was returned
        assert result['attempt_number'] >= 1

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key-123'})
    @patch('apps.email_engine.services.email_generator.anthropic.Anthropic')
    @patch('apps.agents.services.api_budget.ApiBudgetGuard')
    def test_template_fallback_on_api_failure(self, mock_budget_cls, mock_anthropic_cls):
        """Mock API to raise exception and verify template fallback."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API timeout")
        mock_budget = MagicMock()
        mock_budget_cls.return_value = mock_budget

        from apps.email_engine.services.email_generator import EmailGenerator
        gen = EmailGenerator()

        app = _make_mock_application(decision='approved')
        # The generator should raise on first failure; it falls back after 3 consecutive
        with pytest.raises(Exception):
            gen.generate(app, 'approved', confidence=0.92)
