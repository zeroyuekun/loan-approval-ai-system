"""Unit tests for the EMAIL_USE_CLAUDE_API gate on MarketingAgent.generate()."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_application():
    app = MagicMock()
    app.id = 1
    app.loan_amount = Decimal("20000")
    app.annual_income = Decimal("80000")
    app.credit_score = 620
    app.employment_length = 2
    app.applicant.first_name = "Jane"
    app.applicant.last_name = "Doe"
    app.applicant.username = "janedoe"
    app.get_purpose_display.return_value = "Personal Loan"
    app.get_employment_type_display.return_value = "PAYG Permanent"
    # Profile for banking context
    profile = MagicMock()
    profile.savings_balance = Decimal("5000")
    profile.checking_balance = Decimal("1500")
    profile.account_tenure_years = 3
    profile.num_products = 2
    profile.on_time_payment_pct = 97.5
    profile.is_loyal_customer = True
    profile.get_loyalty_tier_display.return_value = "Silver"
    app.applicant.profile = profile
    return app


def _make_nbo_result():
    return {
        "offers": [
            {
                "name": "Personal Loan (reduced amount)",
                "type": "personal_loan",
                "amount": 15000,
                "estimated_rate": 8.5,
                "term_months": 36,
                "monthly_repayment": 475.0,
                "benefit": "Smaller amount better suited to current profile.",
            }
        ],
        "customer_retention_score": 72,
        "loyalty_factors": ["Long tenure"],
        "analysis": "Offer a reduced amount.",
    }


class TestMarketingAgentGate:
    """Gate: when EMAIL_USE_CLAUDE_API is False, Claude is bypassed entirely."""

    @patch("apps.agents.services.marketing_agent.anthropic.Anthropic")
    def test_gate_off_skips_claude(self, mock_anthropic_cls, settings):
        settings.EMAIL_USE_CLAUDE_API = False
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from apps.agents.services.marketing_agent import MarketingAgent

        agent = MarketingAgent()
        app = _make_mock_application()
        result = agent.generate(app, _make_nbo_result(), denial_reasons="Employment tenure")

        # Claude must never be called
        assert mock_client.messages.create.call_count == 0
        assert result["template_fallback"] is True
        assert "TEMPLATE" in result.get("prompt_used", "")
        assert "Jane" in result["body"]

    @patch("apps.agents.services.marketing_agent.guarded_api_call")
    @patch("apps.agents.services.marketing_agent.anthropic.Anthropic")
    def test_gate_on_uses_claude(self, mock_anthropic_cls, mock_guarded_call, settings, monkeypatch):
        settings.EMAIL_USE_CLAUDE_API = True
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")

        # Mock Claude response
        fake_response = MagicMock()
        fake_block = MagicMock()
        fake_block.text = (
            "Subject: Next steps for your AussieLoanAI loan application\n\n"
            "Dear Jane,\n\nWe appreciate your interest...\n\n"
            "You can contact me directly at 1300 000 000.\n\n"
            "Kind regards,\nSarah Mitchell\nSenior Lending Officer\nAussieLoanAI Pty Ltd"
        )
        fake_response.content = [fake_block]
        mock_guarded_call.return_value = fake_response
        mock_anthropic_cls.return_value = MagicMock()

        from apps.agents.services.marketing_agent import MarketingAgent

        agent = MarketingAgent()
        app = _make_mock_application()
        agent.generate(app, _make_nbo_result(), denial_reasons="Employment tenure")

        # guarded_api_call must have been invoked at least once
        assert mock_guarded_call.call_count >= 1
