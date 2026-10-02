"""Tests for PipelineOrchestrator.resume_after_review() -- resuming escalated pipelines."""

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.agents.models import AgentRun

ORCH = "apps.agents.services.orchestrator"
HUMAN_REVIEW = "apps.agents.services.human_review_handler"
MKT_PIPE = "apps.agents.services.marketing_pipeline"
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
        patch("apps.email_engine.services.decision_email.EmailGenerator") as eg,
        patch("apps.email_engine.services.decision_email.EmailPersistenceService") as eps,
        patch(f"{MKT_PIPE}.MarketingBiasDetector") as mbd,
        patch(f"{MKT_PIPE}.MarketingEmailReviewer") as mer,
        patch(f"{MKT_PIPE}.NextBestOfferGenerator") as nbo,
        patch(f"{MKT_PIPE}.MarketingAgent") as ma,
        patch(SENDER, return_value={"sent": True}) as sd,
        patch("django.db.models.QuerySet.select_for_update", _noop_select_for_update),
    ):
        yield {
            "predictor": mp,
            "email_gen": eg,
            "persistence": eps,
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
    # A real row: the resume's bias report is persisted against the email.
    from apps.email_engine.models import GeneratedEmail

    resume_mocks["persistence"].save_generated_email.return_value = GeneratedEmail.objects.create(
        application=escalated_agent_run.application,
        decision="approved",
        subject="Your Loan Decision",
        body="Dear Customer, ...",
        prompt_used="p",
        passed_guardrails=True,
    )
    resume_mocks["persistence"].save_guardrail_logs.return_value = []

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    assert run.status == "completed"
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

    # The denied resume now issues the denial email before the marketing follow-up.
    from apps.email_engine.models import GeneratedEmail

    resume_mocks["email_gen"].return_value.generate.return_value = _email()
    resume_mocks["persistence"].save_generated_email.return_value = GeneratedEmail.objects.create(
        application=escalated_agent_run.application,
        decision="denied",
        subject="Your Loan Decision",
        body="Dear Customer, ...",
        prompt_used="p",
        passed_guardrails=True,
    )
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

    assert run.status == "completed"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "denied"
    resume_mocks["nbo"].return_value.generate.assert_called_once()
    denial_sends = [c for c in resume_mocks["send"].call_args_list if c.kwargs.get("email_type") == "denial"]
    assert len(denial_sends) == 1


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


# --- Bias routing on resume matches the pipeline --------------------------
# The pipeline escalates only at/above BIAS_THRESHOLD_REVIEW, withholds the
# email (but applies the decision) on a guardrail failure, and fails open in
# BIAS_FAILURE_MODE=warn. The resume used to re-escalate on any flag (> 30)
# and on guardrail failures, so a moderate score looped in review forever.


def _approved_resume_email(escalated_agent_run, resume_mocks, *, passed_guardrails=True):
    from apps.email_engine.models import GeneratedEmail

    email = _email()
    email["passed_guardrails"] = passed_guardrails
    if not passed_guardrails:
        email["guardrail_results"] = [{"check_name": "tone", "passed": False}]
    resume_mocks["email_gen"].return_value.generate.return_value = email
    resume_mocks["persistence"].save_generated_email.return_value = GeneratedEmail.objects.create(
        application=escalated_agent_run.application,
        decision="approved",
        subject="Your Loan Decision",
        body="Dear Customer, ...",
        prompt_used="p",
        passed_guardrails=passed_guardrails,
    )
    resume_mocks["persistence"].save_guardrail_logs.return_value = []


def _bias(score):
    return {
        "score": score,
        "flagged": score > 30,
        "requires_human_review": score > 30,
        "categories": [],
        "analysis": "",
        "score_source": "composite",
    }


@CACHE_OVERRIDE
@override_settings(BIAS_THRESHOLD_REVIEW=60)
@pytest.mark.django_db
def test_resume_completes_a_moderately_flagged_run_whose_template_checks_clean(escalated_agent_run, resume_mocks):
    """A moderate score on resume completes the run when the template that
    replaces the LLM text checks clean, instead of sending it back to the
    review queue it came from."""
    _approved_resume_email(escalated_agent_run, resume_mocks)
    from apps.agents.services.orchestrator import PipelineOrchestrator

    with patch(f"{HUMAN_REVIEW}.BiasDetector") as bd:
        bd.return_value.analyze.side_effect = [_bias(40), _bias(5)]
        run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    assert run.status == "completed"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "approved"
    assert resume_mocks["send"].call_count == 1


@CACHE_OVERRIDE
@override_settings(BIAS_THRESHOLD_REVIEW=60)
@pytest.mark.django_db
def test_resume_reescalates_a_severe_email(escalated_agent_run, resume_mocks):
    _approved_resume_email(escalated_agent_run, resume_mocks)
    from apps.agents.services.orchestrator import PipelineOrchestrator

    with patch(f"{HUMAN_REVIEW}.BiasDetector") as bd:
        bd.return_value.analyze.return_value = _bias(60)
        run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    assert run.status == "escalated"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "review"
    resume_mocks["send"].assert_not_called()


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_guardrail_failure_withholds_the_email_and_applies_the_decision(escalated_agent_run, resume_mocks):
    _approved_resume_email(escalated_agent_run, resume_mocks, passed_guardrails=False)
    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    assert run.status == "completed"
    delivery = [s for s in run.steps if s.get("step_name") == "email_delivery"]
    assert delivery and delivery[-1]["result_summary"]["sent"] is False
    assert delivery[-1]["result_summary"]["failed_guardrails"] == ["tone"]
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "approved"
    resume_mocks["send"].assert_not_called()


@CACHE_OVERRIDE
@override_settings(BIAS_FAILURE_MODE="warn")
@pytest.mark.django_db
def test_resume_bias_unavailable_in_warn_mode_fails_open(escalated_agent_run, resume_mocks):
    _approved_resume_email(escalated_agent_run, resume_mocks)
    from apps.agents.services.orchestrator import PipelineOrchestrator

    with patch(f"{HUMAN_REVIEW}.BiasDetector") as bd:
        bd.return_value.analyze.side_effect = RuntimeError("bias service down")
        run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    assert run.status == "completed"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "approved"
    assert resume_mocks["send"].call_count == 1


@CACHE_OVERRIDE
@override_settings(BIAS_FAILURE_MODE="block")
@pytest.mark.django_db
def test_resume_bias_unavailable_in_block_mode_holds_the_run_in_review(escalated_agent_run, resume_mocks):
    """Block mode keeps the reviewer's case actionable instead of dropping it to PENDING."""
    _approved_resume_email(escalated_agent_run, resume_mocks)
    from apps.agents.services.orchestrator import PipelineOrchestrator

    with patch(f"{HUMAN_REVIEW}.BiasDetector") as bd:
        bd.return_value.analyze.side_effect = RuntimeError("bias service down")
        run = PipelineOrchestrator().resume_after_review(escalated_agent_run.pk)

    assert run.status == "escalated"
    escalated_agent_run.application.refresh_from_db()
    assert escalated_agent_run.application.status == "review"
    resume_mocks["send"].assert_not_called()
