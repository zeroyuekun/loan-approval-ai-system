"""Fix-1 regression guard: NameError must not occur when NextBestOffer.objects.create
raises after a successful LLM generate() call.

The bug: nbo_record was never initialised before the try-block, so if .create()
raised, the later ``if nbo_result and nbo_result.get("offers"):`` block attempted
``nbo_record.marketing_message = ...`` → NameError.

The fix: initialise nbo_record = None before the try, and guard every downstream
use with ``nbo_record is not None``.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.agents.services.marketing_pipeline import MarketingPipelineService
from apps.agents.services.step_tracker import StepTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_application():
    app = MagicMock()
    app.pk = "app-fix1-test"
    app.id = "app-fix1-test"
    app.loan_amount = Decimal("20000")
    app.annual_income = Decimal("65000")
    app.credit_score = 620
    app.employment_length = 3
    app.get_purpose_display.return_value = "Personal Loan"
    return app


def _make_mock_agent_run():
    run = MagicMock()
    run.pk = "run-fix1-test"
    return run


def _valid_nbo_result():
    return {
        "offers": [
            {
                "name": "Secured Personal Loan",
                "type": "secured_personal",
                "amount": 15000.0,
                "estimated_rate": 8.99,
                "term_months": 36,
                "monthly_repayment": 476.50,
                "benefit": "Lower rate due to savings",
                "reasoning": "Good savings buffer",
            }
        ],
        "analysis": "Cross-sell opportunity",
        "customer_retention_score": 72,
        "loyalty_factors": ["4-year tenure"],
        "personalized_message": "We value your business.",
    }


# ---------------------------------------------------------------------------
# Test: NBO generate() succeeds but DB create() raises → no NameError
# ---------------------------------------------------------------------------


class TestNboDbFailureDoesNotRaiseNameError:
    """Regression: NameError was raised when nbo_record was never assigned."""

    def test_no_name_error_when_db_create_fails(self):
        """If NextBestOffer.objects.create raises, the pipeline must not NameError."""
        tracker = StepTracker()
        svc = MarketingPipelineService(step_tracker=tracker)

        app = _make_mock_application()
        agent_run = _make_mock_agent_run()
        steps = []

        with (
            patch("apps.agents.services.marketing_pipeline.NextBestOfferGenerator") as mock_gen_cls,
            patch("apps.agents.services.marketing_pipeline.NextBestOffer") as mock_nbo_model,
        ):
            # LLM generate() succeeds and returns a valid result with offers
            mock_gen_cls.return_value.generate.return_value = _valid_nbo_result()

            # DB create() fails — this is the trigger for the NameError
            mock_nbo_model.objects.create.side_effect = Exception("DB connection error")

            # Must not raise NameError (or any other exception from control flow)
            result = svc.run(
                application=app,
                agent_run=agent_run,
                steps=steps,
                denial_reasons="credit score",
                profile_context={},
            )

        # Pipeline should return the steps list (not crash)
        assert isinstance(result, list)

    def test_nbo_step_recorded_as_failed_when_db_create_raises(self):
        """The next_best_offers step must be recorded as 'failed' when create() raises."""
        tracker = StepTracker()
        svc = MarketingPipelineService(step_tracker=tracker)

        app = _make_mock_application()
        agent_run = _make_mock_agent_run()
        steps = []

        with (
            patch("apps.agents.services.marketing_pipeline.NextBestOfferGenerator") as mock_gen_cls,
            patch("apps.agents.services.marketing_pipeline.NextBestOffer") as mock_nbo_model,
        ):
            mock_gen_cls.return_value.generate.return_value = _valid_nbo_result()
            mock_nbo_model.objects.create.side_effect = Exception("DB write failed")

            result = svc.run(
                application=app,
                agent_run=agent_run,
                steps=steps,
                denial_reasons="credit score",
                profile_context={},
            )

        # The first step should be the NBO step, and it should be failed
        nbo_steps = [s for s in result if s.get("step_name") == "next_best_offers"]
        assert len(nbo_steps) == 1
        assert nbo_steps[0]["status"] == "failed"

    def test_marketing_steps_skipped_when_nbo_record_is_none(self):
        """When nbo_record is None (DB failed), marketing sub-steps must NOT run."""
        tracker = StepTracker()
        svc = MarketingPipelineService(step_tracker=tracker)

        app = _make_mock_application()
        agent_run = _make_mock_agent_run()
        steps = []

        with (
            patch("apps.agents.services.marketing_pipeline.NextBestOfferGenerator") as mock_gen_cls,
            patch("apps.agents.services.marketing_pipeline.NextBestOffer") as mock_nbo_model,
        ):
            mock_gen_cls.return_value.generate.return_value = _valid_nbo_result()
            mock_nbo_model.objects.create.side_effect = Exception("DB write failed")

            result = svc.run(
                application=app,
                agent_run=agent_run,
                steps=steps,
                denial_reasons="credit score",
                profile_context={},
            )

        # No marketing message or email steps should have been started
        step_names = [s.get("step_name") for s in result]
        assert "marketing_message_generation" not in step_names
        assert "marketing_email_generation" not in step_names

        # generate_marketing_message should never be called
        mock_gen_cls.return_value.generate_marketing_message.assert_not_called()

    def test_nbo_fails_entirely_skips_all_marketing(self):
        """When NBO generate() itself fails, all marketing steps must be skipped."""
        tracker = StepTracker()
        svc = MarketingPipelineService(step_tracker=tracker)

        app = _make_mock_application()
        agent_run = _make_mock_agent_run()
        steps = []

        with patch("apps.agents.services.marketing_pipeline.NextBestOfferGenerator") as mock_gen_cls:
            # LLM call itself fails
            mock_gen_cls.return_value.generate.side_effect = ConnectionError("timeout")

            result = svc.run(
                application=app,
                agent_run=agent_run,
                steps=steps,
                denial_reasons="credit score",
                profile_context={},
            )

        step_names = [s.get("step_name") for s in result]
        assert "marketing_message_generation" not in step_names
        assert "marketing_email_generation" not in step_names
        # NBO step should be marked as failed
        nbo_steps = [s for s in result if s.get("step_name") == "next_best_offers"]
        assert nbo_steps[0]["status"] == "failed"
