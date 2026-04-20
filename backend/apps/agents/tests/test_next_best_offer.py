"""Tests for apps.agents.services.next_best_offer.NextBestOfferGenerator.

Covers generate() / _generate_messaging() with RecommendationEngine and Claude
mocked, the deterministic generate_marketing_message() fallback path,
_format_precalculated_offers() / _get_customer_context() in isolation, and the
module-level _extract_tool_result() helper.
"""

import json
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import anthropic

from apps.agents.services.next_best_offer import (
    NextBestOfferGenerator,
    _extract_tool_result,
)

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_tool_use_response(tool_input):
    """Claude response with a tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = tool_input

    response = MagicMock()
    response.content = [tool_block]
    return response


def _make_text_response(text):
    """Claude response with a single text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    response = MagicMock()
    response.content = [block]
    return response


def _make_mock_application(
    first_name="Jane",
    last_name="Doe",
    loan_amount=25000,
    credit_score=640,
    annual_income=80000,
    employment_length=4,
    has_profile=True,
):
    app = MagicMock()
    app.loan_amount = Decimal(str(loan_amount))
    app.annual_income = Decimal(str(annual_income))
    app.credit_score = credit_score
    app.employment_length = employment_length
    app.get_purpose_display.return_value = "Personal Loan"
    app.get_employment_type_display.return_value = "PAYG Permanent"

    if has_profile:
        app.applicant.first_name = first_name
        app.applicant.last_name = last_name
        app.applicant.profile.savings_balance = Decimal("10000")
        app.applicant.profile.checking_balance = Decimal("3000")
        app.applicant.profile.total_deposits = Decimal("13000")
        app.applicant.profile.account_tenure_years = 5
        app.applicant.profile.get_loyalty_tier_display.return_value = "Gold"
        app.applicant.profile.has_credit_card = True
        app.applicant.profile.has_mortgage = False
        app.applicant.profile.has_auto_loan = False
        app.applicant.profile.num_products = 3
        app.applicant.profile.on_time_payment_pct = 99.2
        app.applicant.profile.previous_loans_repaid = 2
        app.applicant.profile.is_loyal_customer = True
    else:
        app.applicant = MagicMock(spec=["first_name", "last_name"])
        app.applicant.first_name = first_name
        app.applicant.last_name = last_name
    return app


def _sample_offers():
    return [
        {
            "name": "Secured Personal Loan",
            "type": "secured_personal",
            "amount": 15000.0,
            "estimated_rate": 8.99,
            "term_months": 36,
            "monthly_repayment": 476.50,
            "benefit": "Lower rate with collateral",
        },
        {
            "name": "Goal Saver Account",
            "type": "savings",
            "estimated_rate": 4.75,
            "benefit": "Build deposit",
        },
    ]


def _engine_result_with_offers():
    return {
        "offers": _sample_offers(),
        "customer_retention_score": 78,
        "loyalty_factors": ["5-year tenure", "Gold tier"],
    }


def _engine_result_empty():
    return {"offers": [], "customer_retention_score": 10, "loyalty_factors": []}


# ---------------------------------------------------------------------------
# Module-level: _extract_tool_result
# ---------------------------------------------------------------------------


class TestExtractToolResult:
    def test_returns_tool_input_from_tool_use_block(self):
        response = _make_tool_use_response({"offer_reasoning": ["a"], "analysis": "x"})
        out = _extract_tool_result(response, fallback={"fallback": True})
        assert out == {"offer_reasoning": ["a"], "analysis": "x"}

    def test_falls_back_to_text_json_when_no_tool_use(self):
        text = 'Some preamble {"offer_reasoning": ["b"], "analysis": "y"} trailing text'
        response = _make_text_response(text)
        out = _extract_tool_result(response, fallback={"fallback": True})
        assert out == {"offer_reasoning": ["b"], "analysis": "y"}

    def test_returns_fallback_when_text_is_not_json(self):
        response = _make_text_response("this is not json at all")
        fallback = {"fallback": True}
        out = _extract_tool_result(response, fallback=fallback)
        assert out is fallback

    def test_returns_fallback_when_no_blocks_at_all(self):
        response = MagicMock()
        response.content = []
        fallback = {"fallback": True}
        out = _extract_tool_result(response, fallback=fallback)
        assert out is fallback

    def test_handles_mixed_blocks_prefers_tool_use(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = '{"offer_reasoning": ["wrong"]}'
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.input = {"offer_reasoning": ["right"]}
        response = MagicMock()
        response.content = [text_block, tool_block]
        out = _extract_tool_result(response, fallback=None)
        assert out == {"offer_reasoning": ["right"]}


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestNextBestOfferGeneratorInit:
    @patch.dict(os.environ, {}, clear=True)
    def test_no_api_key_sets_client_none(self):
        gen = NextBestOfferGenerator()
        assert gen.client is None
        assert gen.engine is not None

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    def test_with_api_key_creates_client(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        gen = NextBestOfferGenerator()
        assert gen.client is not None
        mock_anthropic_cls.assert_called_once()


# ---------------------------------------------------------------------------
# _format_precalculated_offers
# ---------------------------------------------------------------------------


class TestFormatPrecalculatedOffers:
    def _gen(self):
        with patch.dict(os.environ, {}, clear=True):
            return NextBestOfferGenerator()

    def test_empty_list_returns_empty_string(self):
        assert self._gen()._format_precalculated_offers([]) == ""

    def test_single_offer_with_all_fields(self):
        out = self._gen()._format_precalculated_offers(
            [
                {
                    "name": "Car Loan",
                    "amount": 20000.0,
                    "term_months": 48,
                    "estimated_rate": 7.5,
                    "monthly_repayment": 483.20,
                    "fortnightly_repayment": 222.90,
                    "benefit": "Lower rate secured by vehicle",
                }
            ]
        )
        assert "Offer 1: Car Loan" in out
        assert "$20,000.00" in out
        assert "48 months" in out
        assert "7.50% p.a." in out
        assert "$483.20" in out
        assert "$222.90" in out
        assert "Lower rate secured by vehicle" in out

    def test_multiple_offers_separated(self):
        out = self._gen()._format_precalculated_offers(
            [
                {"name": "A", "amount": 1000.0},
                {"name": "B", "amount": 2000.0},
            ]
        )
        assert "Offer 1: A" in out
        assert "Offer 2: B" in out

    def test_name_falls_back_to_type(self):
        out = self._gen()._format_precalculated_offers([{"type": "savings"}])
        assert "Offer 1: savings" in out

    def test_name_falls_back_to_product_when_neither_provided(self):
        out = self._gen()._format_precalculated_offers([{"amount": 500.0}])
        assert "Offer 1: Product" in out

    def test_omits_missing_fields(self):
        out = self._gen()._format_precalculated_offers([{"name": "Bare"}])
        assert "Offer 1: Bare" in out
        assert "months" not in out
        assert "Rate" not in out
        assert "repayment" not in out


# ---------------------------------------------------------------------------
# _get_customer_context
# ---------------------------------------------------------------------------


class TestGetCustomerContext:
    def _gen(self):
        with patch.dict(os.environ, {}, clear=True):
            return NextBestOfferGenerator()

    def test_with_profile_includes_balances_and_tenure(self):
        gen = self._gen()
        app = _make_mock_application()
        out = gen._get_customer_context(app)
        assert "$10,000.00" in out
        assert "$3,000.00" in out
        assert "$13,000.00" in out
        assert "5 years" in out
        assert "Gold" in out
        assert "Has Credit Card: Yes" in out
        assert "Has Existing Mortgage: No" in out
        assert "99.2%" in out
        assert "Loyal Customer: Yes" in out

    def test_without_profile_returns_new_customer_message(self):
        gen = self._gen()
        app = _make_mock_application(has_profile=False)
        out = gen._get_customer_context(app)
        assert "No banking relationship data available" in out
        assert "new customer" in out


# ---------------------------------------------------------------------------
# generate() — the main entry point
# ---------------------------------------------------------------------------


class TestGenerate:
    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.agents.services.next_best_offer.RecommendationEngine")
    def test_empty_offers_returns_early_without_llm_call(self, mock_engine_cls):
        mock_engine = MagicMock()
        mock_engine.recommend.return_value = _engine_result_empty()
        mock_engine_cls.return_value = mock_engine

        gen = NextBestOfferGenerator()
        with patch.object(gen, "_generate_messaging") as mock_llm:
            result = gen.generate(_make_mock_application(), "credit history")

        assert result["offers"] == []
        assert "building your savings" in result["analysis"]
        assert "personalized_message" in result
        mock_llm.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.agents.services.next_best_offer.RecommendationEngine")
    def test_with_offers_merges_llm_reasoning_into_each_offer(self, mock_engine_cls):
        mock_engine = MagicMock()
        mock_engine.recommend.return_value = _engine_result_with_offers()
        mock_engine_cls.return_value = mock_engine

        gen = NextBestOfferGenerator()
        with patch.object(gen, "_generate_messaging") as mock_llm:
            mock_llm.return_value = {
                "offer_reasoning": [
                    "Reasoning specific to offer 1 (refs $10k savings).",
                    "Reasoning specific to offer 2 (build deposit).",
                ],
                "analysis": "Retention strategy paragraph.",
                "personalized_message": "Thanks Jane.",
            }
            result = gen.generate(_make_mock_application(), "low savings")

        assert len(result["offers"]) == 2
        assert result["offers"][0]["reasoning"] == "Reasoning specific to offer 1 (refs $10k savings)."
        assert result["offers"][1]["reasoning"] == "Reasoning specific to offer 2 (build deposit)."
        assert result["analysis"] == "Retention strategy paragraph."
        assert result["personalized_message"] == "Thanks Jane."

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.agents.services.next_best_offer.RecommendationEngine")
    def test_more_offers_than_reasonings_leaves_extras_without_reasoning(self, mock_engine_cls):
        mock_engine = MagicMock()
        mock_engine.recommend.return_value = _engine_result_with_offers()
        mock_engine_cls.return_value = mock_engine

        gen = NextBestOfferGenerator()
        with patch.object(gen, "_generate_messaging") as mock_llm:
            mock_llm.return_value = {
                "offer_reasoning": ["only one reasoning"],
                "analysis": "x",
                "personalized_message": "y",
            }
            result = gen.generate(_make_mock_application())

        assert result["offers"][0]["reasoning"] == "only one reasoning"
        # Second offer keeps whatever reasoning it already had (or lacks one)
        assert result["offers"][1].get("reasoning") != "only one reasoning"


# ---------------------------------------------------------------------------
# _generate_messaging() — LLM path + fallback branches
# ---------------------------------------------------------------------------


class TestGenerateMessaging:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_success_returns_tool_result(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.return_value = _make_tool_use_response(
            {
                "offer_reasoning": ["r1", "r2"],
                "analysis": "a",
                "personalized_message": "m",
            }
        )
        gen = NextBestOfferGenerator()
        result = gen._generate_messaging(_make_mock_application(), _sample_offers(), "credit")
        assert result["offer_reasoning"] == ["r1", "r2"]
        assert result["analysis"] == "a"
        assert result["personalized_message"] == "m"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_auth_error_returns_benefit_fallback(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.side_effect = anthropic.AuthenticationError(
            message="bad key",
            response=MagicMock(status_code=401),
            body={"error": "x"},
        )
        gen = NextBestOfferGenerator()
        result = gen._generate_messaging(_make_mock_application(), _sample_offers())
        assert result["offer_reasoning"] == [
            "Lower rate with collateral",
            "Build deposit",
        ]
        assert "alternative products" in result["analysis"]
        assert "Thank you" in result["personalized_message"]

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_rate_limit_error_returns_fallback(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.side_effect = anthropic.RateLimitError(
            message="slow down",
            response=MagicMock(status_code=429),
            body={"error": "rate"},
        )
        gen = NextBestOfferGenerator()
        result = gen._generate_messaging(_make_mock_application(), _sample_offers())
        assert "offer_reasoning" in result
        assert len(result["offer_reasoning"]) == 2

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_timeout_error_returns_fallback(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.side_effect = anthropic.APITimeoutError(request=MagicMock())
        gen = NextBestOfferGenerator()
        result = gen._generate_messaging(_make_mock_application(), _sample_offers())
        assert "offer_reasoning" in result

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_unexpected_exception_also_returns_fallback(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.side_effect = ValueError("weird happened")
        gen = NextBestOfferGenerator()
        result = gen._generate_messaging(_make_mock_application(), _sample_offers())
        assert result["offer_reasoning"] == [
            "Lower rate with collateral",
            "Build deposit",
        ]

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_tool_result_none_raises_internally_and_falls_back(self, mock_call, mock_anthropic_cls):
        """When _extract_tool_result returns None, internal ValueError triggers fallback."""
        mock_anthropic_cls.return_value = MagicMock()
        # Response with no tool_use and no valid JSON text -> _extract_tool_result returns None
        response = MagicMock()
        response.content = []
        mock_call.return_value = response
        gen = NextBestOfferGenerator()
        result = gen._generate_messaging(_make_mock_application(), _sample_offers())
        assert "offer_reasoning" in result
        assert len(result["offer_reasoning"]) == 2

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_prompt_includes_customer_numbers(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.return_value = _make_tool_use_response(
            {"offer_reasoning": [], "analysis": "", "personalized_message": ""}
        )
        gen = NextBestOfferGenerator()
        app = _make_mock_application(loan_amount=25000, credit_score=640, annual_income=80000)
        gen._generate_messaging(app, _sample_offers(), "credit")
        prompt = mock_call.call_args.kwargs["messages"][0]["content"]
        assert "25,000.00" in prompt
        assert "640" in prompt
        assert "80,000.00" in prompt
        assert "credit" in prompt


# ---------------------------------------------------------------------------
# generate_marketing_message() — separate LLM path
# ---------------------------------------------------------------------------


class TestGenerateMarketingMessage:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_success_returns_trimmed_message(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        text_block = MagicMock()
        text_block.text = "   Dear Jane,\n\nWe have options.\n\nThe AussieLoanAI Team   "
        response = MagicMock()
        response.content = [text_block]
        mock_call.return_value = response

        gen = NextBestOfferGenerator()
        result = gen.generate_marketing_message(_make_mock_application(), _sample_offers(), "credit")
        assert result["marketing_message"].startswith("Dear Jane")
        assert result["marketing_message"].endswith("AussieLoanAI Team")
        assert "generation_time_ms" in result

    @patch.dict(os.environ, {}, clear=True)
    def test_no_api_key_returns_template_fallback(self):
        """client=None -> guarded_api_call raises BudgetExhausted -> fallback."""
        gen = NextBestOfferGenerator()
        result = gen.generate_marketing_message(_make_mock_application(), _sample_offers())
        msg = result["marketing_message"]
        assert "Dear Jane Doe" in msg
        assert "AussieLoanAI" in msg
        assert "1300 000 000" in msg
        assert "Secured Personal Loan" in msg
        assert "$15,000.00" in msg
        assert "The AussieLoanAI Team" in msg
        assert "generation_time_ms" in result

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("apps.agents.services.next_best_offer.anthropic.Anthropic")
    @patch("apps.agents.services.next_best_offer.guarded_api_call")
    def test_api_exception_returns_template_fallback(self, mock_call, mock_anthropic_cls):
        mock_anthropic_cls.return_value = MagicMock()
        mock_call.side_effect = RuntimeError("anything")
        gen = NextBestOfferGenerator()
        result = gen.generate_marketing_message(_make_mock_application(), _sample_offers())
        assert "Dear Jane Doe" in result["marketing_message"]
        assert "1300 000 000" in result["marketing_message"]

    @patch.dict(os.environ, {}, clear=True)
    def test_template_fallback_handles_offers_without_amount(self):
        gen = NextBestOfferGenerator()
        offers = [{"name": "Savings Account", "benefit": "4.75% p.a."}]
        result = gen.generate_marketing_message(_make_mock_application(), offers)
        assert "Savings Account" in result["marketing_message"]
        # No amount -> no dollar value for this offer
        assert "4.75% p.a." in result["marketing_message"]

    @patch.dict(os.environ, {}, clear=True)
    def test_template_fallback_with_empty_offers_still_renders(self):
        gen = NextBestOfferGenerator()
        result = gen.generate_marketing_message(_make_mock_application(), [])
        assert "Dear Jane Doe" in result["marketing_message"]
        assert "The AussieLoanAI Team" in result["marketing_message"]


# ---------------------------------------------------------------------------
# _extract_tool_result with realistic JSON
# ---------------------------------------------------------------------------


class TestExtractToolResultRealistic:
    def test_nested_json_in_text_is_extracted(self):
        payload = {
            "offer_reasoning": ["reason a", "reason b"],
            "analysis": "retention plan",
            "personalized_message": "hi",
        }
        text = f"Here's my answer: {json.dumps(payload)} hope that helps!"
        response = _make_text_response(text)
        out = _extract_tool_result(response, fallback=None)
        assert out == payload
