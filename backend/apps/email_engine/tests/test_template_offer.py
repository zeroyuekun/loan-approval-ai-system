"""Denial emails carry the next-best offer even on the deterministic template path.

Covers: `template_fallback.render_nbo_block` (moved out of
`EmailGenerator._render_nbo_block`, which now delegates to it),
`EmailGenerator._add_nbo_context` (shared by the LLM and template paths), and
`EmailGenerator.generate_template(..., profile_context=...)` reaching the
template fallback with the offer already in context.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.template_fallback import generate_denial_template, render_nbo_block

# Real RecommendationEngine offer dicts (apps/agents/services/recommendation_engine.py
# `recommend()`) carry exactly these keys: type, name, amount, estimated_rate,
# monthly_repayment (plus term_months / reason, not used by the renderer).
OFFER = {
    "name": "Personal Loan",
    "type": "personal",
    "amount": 15000,
    "estimated_rate": 9.99,
    "monthly_repayment": 320,
}


def _make_mock_application(decision="denied", loan_amount=20000):
    app = MagicMock()
    app.loan_amount = Decimal(str(loan_amount))
    app.applicant.first_name = "Jane"
    app.applicant.last_name = "Doe"
    app.applicant.username = "janedoe"
    app.get_purpose_display.return_value = "Personal Loan"
    app.get_employment_type_display.return_value = "PAYG Permanent"
    app.get_applicant_type_display.return_value = "Single"
    app.has_cosigner = False
    app.has_hecs = False
    app.decision = MagicMock()
    if decision == "denied":
        app.decision.confidence = 0.35
        app.decision.feature_importances = {"credit_score": 0.3}
        app.decision.shap_values = {}
    else:
        app.decision.confidence = 0.92
    return app


class TestRenderNboBlock:
    def test_denial_template_contains_offer_block_when_offer_given(self):
        result = generate_denial_template("Jane Doe", 20000.0, "Personal Loan", nbo_offer=OFFER)
        assert render_nbo_block(OFFER) in result["body"]

    def test_denial_template_has_no_offer_language_without_an_offer(self):
        result = generate_denial_template("Jane Doe", 20000.0, "Personal Loan")
        assert "A specific option" not in result["body"]

    def test_generator_render_nbo_block_delegates_to_template_fallback(self):
        gen = EmailGenerator()
        assert gen._render_nbo_block(OFFER) == render_nbo_block(OFFER)

    def test_offer_block_has_no_banned_apology_wording(self):
        block = render_nbo_block(OFFER)
        lowered = block.lower()
        for banned in ("sorry", "apolog", "disappointment"):
            assert banned not in lowered


class TestGenerateTemplateWithOffer:
    def test_denial_generate_template_passes_guardrails_with_offer_amount_in_body(self):
        gen = EmailGenerator()
        app = _make_mock_application(decision="denied")
        result = gen.generate_template(app, "denied", profile_context={"nbo_offer": OFFER})
        assert result["passed_guardrails"], result["guardrail_results"]
        assert "$15,000" in result["body"]

    def test_approved_generate_template_has_no_offer(self):
        gen = EmailGenerator()
        app = _make_mock_application(decision="approved")
        result = gen.generate_template(app, "approved", profile_context={"nbo_offer": OFFER})
        assert "A specific option" not in result["body"]
        assert "$15,000" not in result["body"]
