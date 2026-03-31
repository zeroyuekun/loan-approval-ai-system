"""Tests for PipelineOrchestrator.resume_after_review() -- resuming escalated pipelines."""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.agents.models import AgentRun

ORCH = "apps.agents.services.orchestrator"
SENDER = "apps.email_engine.services.sender.send_decision_email"

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


def _email():
    return {
        "subject": "Your Loan Decision",
        "body": "Dear Customer, ...",
        "passed_guardrails": True,
        "template_fallback": False,
        "prompt_used": "test prompt",
        "guardrail_results": [],
        "generation_time_ms": 100,
        "attempt_number": 1,
        "input_tokens": 500,
        "output_tokens": 200,
        "estimated_cost_usd": 0.002,
    }


def _nbo():
    return {
        "offers": [
            {
                "type": "secured_loan",
                "name": "Secured Loan",
                "amount": 15000,
                "term_months": 36,
                "estimated_rate": 7.5,
                "benefit": "Lower rate",
                "reasoning": "Suits profile",
            }
        ],
        "analysis": "Analysis",
        "customer_retention_score": 65,
        "loyalty_factors": ["tenure"],
        "personalized_message": "Hello",
    }


def _marketing_email():
    return {
        "subject": "Next steps",
        "body": "Dear Customer, options...",
        "prompt_used": "prompt",
        "passed_guardrails": True,
        "guardrail_results": [],
        "generation_time_ms": 200,
        "attempt_number": 1,
    }


def _marketing_msg():
    return {"marketing_message": "Copy", "generation_time_ms": 150}


def _noop_select_for_update(self, **kwargs):
    """Replace select_for_update with a no-op to avoid PostgreSQL outer join limitation."""
    return self


@pytest.fixture
def resume_mocks():
    with (
        patch(f"{ORCH}.ModelPredictor") as mp,
        patch(f"{ORCH}.EmailGenerator") as eg,
        patch(f"{ORCH}.EmailPersistenceService") as eps,
        patch(f"{ORCH}.BiasDetector") as bd,
        patch(f"{ORCH}.AIEmailReviewer") as air,
        patch(f"{ORCH}.MarketingBiasDetector") as mbd,
        patch(f"{ORCH}.MarketingEmailReviewer") as mer,
        patch(f"{ORCH}.NextBestOfferGenerator") as nbo,
        patch(f"{ORCH}.MarketingAgent") as ma,
        patch(SENDER, return_value={"sent": True}) as sd,
        patch("django.db.models.QuerySet.select_for_update", _noop_select_for_update),
    ):
        yield {
            "predictor": mp,
            "email_gen": eg,
            "persistence": eps,
            "bias": bd,
            "ai_reviewer": air,
            "mkt_bias": mbd,
            "mkt_reviewer": mer,
            "nbo": nbo,
            "marketing_agent": ma,
            "send": sd,
        }


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_approved(escalated_agent_run, resume_mocks):
    """Resuming an escalated approved run regenerates and sends approval email."""
    resume_mocks["email_gen"].return_value.generate.return_value = _email()
    resume_mocks["persistence"].save_generated_email.return_value = MagicMock(id="e1")
    resume_mocks["persistence"].save_guardrail_logs.return_value = []

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    # _finalize_run preserves 'escalated' status (by design — the run was human-reviewed)
    assert run.status == "escalated"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "approved"
    resume_mocks["email_gen"].return_value.generate.assert_called_once()


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_denied(escalated_agent_run, resume_mocks):
    """Resuming an escalated denied run triggers NBO + marketing pipeline."""
    decision = escalated_agent_run.application.decision
    decision.decision = "denied"
    decision.feature_importances = {"credit_score": 0.4, "income": 0.3, "dti": 0.2}
    decision.save()

    resume_mocks["nbo"].return_value.generate.return_value = _nbo()
    resume_mocks["nbo"].return_value.generate_marketing_message.return_value = _marketing_msg()
    resume_mocks["marketing_agent"].return_value.generate.return_value = _marketing_email()
    resume_mocks["mkt_bias"].return_value.analyze.return_value = {
        "score": 25,
        "flagged": False,
        "requires_human_review": False,
        "categories": [],
        "analysis": "Clean",
        "score_source": "composite",
    }

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    # _finalize_run preserves 'escalated' status (by design — the run was human-reviewed)
    assert run.status == "escalated"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "denied"
    resume_mocks["nbo"].return_value.generate.assert_called_once()


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_non_escalated_fails(escalated_agent_run, resume_mocks):
    """Cannot resume a run that is not in 'escalated' status."""
    escalated_agent_run.status = "completed"
    escalated_agent_run.save()

    from apps.agents.services.orchestrator import PipelineOrchestrator

    with pytest.raises(ValueError, match="Cannot resume agent run"):
        PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_wrong_app_status(escalated_agent_run, resume_mocks):
    """Cannot resume if application is not in 'review' status."""
    app = escalated_agent_run.application
    app.status = "approved"
    app.save()

    from apps.agents.services.orchestrator import PipelineOrchestrator

    with pytest.raises(ValueError, match="Cannot resume.*application status"):
        PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_no_decision(sample_application, resume_mocks):
    """Cannot resume if no LoanDecision exists for the application."""
    sample_application.status = "review"
    sample_application.save()

    run = AgentRun.objects.create(
        application=sample_application,
        status="escalated",
        steps=[],
    )

    from apps.agents.services.orchestrator import PipelineOrchestrator

    with pytest.raises(ValueError, match="No decision found"):
        PipelineOrchestrator().resume_after_review(run.pk)
