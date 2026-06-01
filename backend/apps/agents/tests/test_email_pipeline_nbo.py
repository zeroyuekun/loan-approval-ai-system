"""EmailPipelineService must inject a deterministic NBO teaser offer into
profile_context for denial decisions (Phase 05 enhancement)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.agents.services.email_pipeline import EmailPipelineService
from apps.agents.services.step_tracker import StepTracker
from apps.loans.models import LoanDecision


def _capture_generate_kwargs():
    """A fake EmailGenerator.generate that records the profile_context it saw."""
    captured = {}

    def _fake_generate(application, decision, confidence=None, profile_context=None):
        captured["profile_context"] = profile_context
        return {
            "subject": "s",
            "body": "b",
            "prompt_used": "p",
            "guardrail_results": [],
            "passed_guardrails": True,
            "quality_score": 100,
            "generation_time_ms": 1,
            "attempt_number": 1,
            "template_fallback": False,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    return captured, _fake_generate


class TestEmailPipelineNboInjection:
    @patch("apps.email_engine.services.sender.send_decision_email")
    @patch("apps.agents.services.email_pipeline.EmailGenerator")
    @patch("apps.agents.services.email_pipeline.EmailPersistenceService")
    @patch("apps.agents.services.email_pipeline.RecommendationEngine")
    def test_denial_injects_best_offer_into_profile_context(
        self, mock_engine_cls, mock_persist, mock_gen_cls, mock_send
    ):
        captured, fake_generate = _capture_generate_kwargs()
        mock_gen_cls.return_value.generate.side_effect = fake_generate
        mock_persist.save_generated_email.return_value = MagicMock()
        mock_send.return_value = {"sent": True}

        mock_engine_cls.return_value.recommend.return_value = {
            "offers": [
                {"name": "Secured Personal Loan", "type": "secured_personal", "amount": 15000.0},
                {"name": "Goal Saver", "type": "savings", "amount": None},
            ]
        }

        application = MagicMock()
        application.pk = 1
        application.loan_amount = Decimal("20000")
        application.get_purpose_display.return_value = "Personal Loan"

        svc = EmailPipelineService(StepTracker())
        # The counterfactual block calls LoanDecision.objects.get; with a mock
        # application there is no real row, so force DoesNotExist to skip it
        # cleanly and isolate the NBO injection under test.
        patch_cf = patch.object(LoanDecision.objects, "get", side_effect=LoanDecision.DoesNotExist)
        # Bias detector path runs after generate; mock it so the pipeline reaches
        # the end. We only assert on the captured profile_context.
        with patch_cf, patch("apps.agents.services.email_pipeline.BiasDetector") as mock_bias:
            mock_bias.return_value.analyze.return_value = {
                "score": 0,
                "flagged": False,
                "requires_human_review": False,
                "categories": [],
                "analysis": "",
                "deterministic_score": 0,
                "llm_raw_score": None,
                "score_source": "x",
            }
            with patch("apps.agents.models.BiasReport.objects.create"):
                svc.run(application, MagicMock(), {}, {"probability": 0.3}, "denied", [], [])

        assert captured["profile_context"]["nbo_offer"]["name"] == "Secured Personal Loan"
