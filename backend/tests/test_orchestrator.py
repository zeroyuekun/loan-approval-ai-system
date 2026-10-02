"""Tests for PipelineOrchestrator covering happy paths, failures, bias escalation, and edge cases."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.loans.models import LoanApplication
from apps.ml_engine.models import ModelVersion

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ORCH = "apps.agents.services.orchestrator"
EMAIL_PIPE = "apps.agents.services.email_pipeline"
MKT_PIPE = "apps.agents.services.marketing_pipeline"
SENDER = "apps.email_engine.services.sender.send_decision_email"

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


def _prediction(decision="approved", probability=0.85, model_version_id=None):
    return {
        "prediction": decision,
        "probability": probability,
        "model_version": model_version_id or "00000000-0000-0000-0000-000000000001",
        "feature_importances": {"credit_score": 0.35, "annual_income": 0.25, "dti": 0.15},
        "processing_time_ms": 42,
        "refer_reasons": [],
    }


def _email(subject="Your Loan Decision", body="Dear Customer, ..."):
    return {
        "subject": subject,
        "body": body,
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


def _bias(score=30, flagged=False):
    return {
        "score": score,
        "flagged": flagged,
        "requires_human_review": False,
        "categories": [],
        "analysis": "No bias detected",
        "deterministic_score": score,
        "llm_raw_score": score,
        "score_source": "composite",
    }


def _review(approved=True, confidence=0.85):
    return {"approved": approved, "confidence": confidence, "reasoning": "Review text"}


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
        "analysis": "NBO analysis",
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


def _wire_approved(mocks):
    """Configure mocks for a standard approved happy path."""
    mv = mocks.get("model_version_id")
    mocks["predictor"].return_value.predict.return_value = _prediction("approved", 0.85, mv)
    mocks["email_gen"].return_value.generate.return_value = _email()
    mocks["bias"].return_value.analyze.return_value = _bias(30)


def _wire_denied(mocks):
    """Configure mocks for a denied path with NBO + marketing."""
    mv = mocks.get("model_version_id")
    mocks["predictor"].return_value.predict.return_value = _prediction("denied", 0.25, mv)
    mocks["email_gen"].return_value.generate.return_value = _email()
    mocks["bias"].return_value.analyze.return_value = _bias(20)
    mocks["nbo"].return_value.generate.return_value = _nbo()
    mocks["nbo"].return_value.generate_marketing_message.return_value = _marketing_msg()
    mocks["marketing_agent"].return_value.generate.return_value = _marketing_email()
    mocks["mkt_bias"].return_value.analyze.return_value = _bias(25)


@pytest.fixture
def model_version(db, settings):
    """Create a ModelVersion record so PredictionLog FK is valid."""
    return ModelVersion.objects.create(
        algorithm="rf",
        version="test-v1",
        file_path=str(settings.ML_MODELS_DIR / "test_model.joblib"),
        is_active=True,
    )


@pytest.fixture
def orch_mocks(model_version):
    """Patch all orchestrator dependencies and yield a dict of mocks.

    EmailPersistenceService is NOT mocked — it creates real DB records so
    that BiasReport.email FK receives a proper GeneratedEmail instance.
    """
    with (
        patch(f"{ORCH}.ModelPredictor") as mock_predictor,
        patch("apps.email_engine.services.decision_email.EmailGenerator") as mock_email_gen,
        patch(f"{EMAIL_PIPE}.BiasDetector") as mock_bias,
        patch(f"{MKT_PIPE}.MarketingBiasDetector") as mock_mkt_bias,
        patch(f"{MKT_PIPE}.MarketingEmailReviewer") as mock_mkt_reviewer,
        patch(f"{MKT_PIPE}.NextBestOfferGenerator") as mock_nbo,
        patch(f"{MKT_PIPE}.MarketingAgent") as mock_marketing_agent,
        patch(SENDER, return_value={"sent": True}) as mock_send,
    ):
        yield {
            "predictor": mock_predictor,
            "email_gen": mock_email_gen,
            "bias": mock_bias,
            "mkt_bias": mock_mkt_bias,
            "mkt_reviewer": mock_mkt_reviewer,
            "nbo": mock_nbo,
            "marketing_agent": mock_marketing_agent,
            "send": mock_send,
            "model_version_id": str(model_version.pk),
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_approved_happy_path(sample_application, orch_mocks):
    """ML approved + low bias -> run completed, app approved."""
    _wire_approved(orch_mocks)

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "completed"
    sample_application.refresh_from_db()
    assert sample_application.status == "approved"
    orch_mocks["predictor"].return_value.predict.assert_called_once()
    orch_mocks["nbo"].return_value.generate.assert_not_called()


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_denied_with_nbo(sample_application, orch_mocks):
    """ML denied + low bias -> NBO generated, marketing email generated."""
    _wire_denied(orch_mocks)

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "completed"
    sample_application.refresh_from_db()
    assert sample_application.status == "denied"
    orch_mocks["nbo"].return_value.generate.assert_called_once()
    orch_mocks["marketing_agent"].return_value.generate.assert_called_once()


@CACHE_OVERRIDE
@pytest.mark.django_db
@pytest.mark.parametrize("error", [Exception("Model unavailable"), ConnectionError("model store unreachable")])
def test_ml_prediction_failure(sample_application, orch_mocks, error):
    """Predictor raises -> run failed, app back to PENDING (re-runnable), reason recorded.

    The human review queue is only for bias flags, so a prediction failure
    (transient or unexpected) must not park the application there."""
    orch_mocks["predictor"].return_value.predict.side_effect = error

    from apps.agents.services.orchestrator import PipelineOrchestrator
    from apps.loans.models import AuditLog

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "failed"
    sample_application.refresh_from_db()
    assert sample_application.status == "pending"
    orch_mocks["email_gen"].return_value.generate.assert_not_called()
    last = AuditLog.objects.filter(resource_id=str(sample_application.pk), action="status_transition").latest(
        "timestamp"
    )
    assert last.details["to_status"] == "pending"
    assert last.details["source"] == "orchestrator_ml_prediction_failure"
    assert str(error) in last.details["error"]


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_email_generation_failure(sample_application, orch_mocks):
    """Email generator raises -> run failed."""
    orch_mocks["predictor"].return_value.predict.return_value = _prediction(
        "approved", 0.85, orch_mocks["model_version_id"]
    )
    orch_mocks["email_gen"].return_value.generate.side_effect = Exception("Claude API error")

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "failed"
    sample_application.refresh_from_db()
    assert sample_application.status == "approved"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_follow_up_failure_after_the_decision_email_keeps_the_decision(sample_application, orch_mocks):
    """The NBO step hits the soft time limit after the denial email was sent.
    The application keeps its decision, and a re-run does not email the
    customer a second denial."""
    from celery.exceptions import SoftTimeLimitExceeded

    from apps.agents.tasks import orchestrate_pipeline_task

    _wire_denied(orch_mocks)
    orch_mocks["nbo"].return_value.generate.side_effect = SoftTimeLimitExceeded()

    orchestrate_pipeline_task.apply(args=(str(sample_application.pk),))

    sample_application.refresh_from_db()
    assert sample_application.status == "denied", "a follow-up failure undid the decision the customer was sent"
    assert orch_mocks["send"].call_count == 1

    orchestrate_pipeline_task.apply(args=(str(sample_application.pk),))
    assert orch_mocks["send"].call_count == 1, "the re-run sent a second decision email"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_policy_decline_of_a_model_approval_is_not_recorded_as_the_model_s(sample_application, orch_mocks):
    """The model approved; an enforce-mode credit-policy hard fail declined.
    The waterfall says so, with the rule's code, instead of MODEL_DENIED."""
    from apps.loans.models import LoanDecision

    _wire_denied(orch_mocks)
    orch_mocks["predictor"].return_value.predict.return_value = {
        **_prediction("denied", 0.82, orch_mocks["model_version_id"]),
        "policy_decision": {
            "mode": "enforce",
            "passed": False,
            "changed_model_decision": True,
            "hard_fails": ["P03"],
            "refers": [],
            "rationale_by_code": {"P03": "Undischarged bankrupt or within 7-year bankruptcy window"},
        },
    }

    from apps.agents.services.orchestrator import PipelineOrchestrator

    PipelineOrchestrator().orchestrate(sample_application.pk)

    waterfall = LoanDecision.objects.get(application=sample_application).decision_waterfall
    ml_entry = next(e for e in waterfall if e["step"] == "ml_prediction")
    assert ml_entry["reason_code"] != "MODEL_DENIED", "a policy decline was recorded as the model's decision"
    assert ml_entry["reason_code"] == "MODEL_APPROVED"
    policy = [e for e in waterfall if e["reason_code"] == "POLICY_DECLINE_P03"]
    assert policy and policy[0]["result"] == "fail"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_severe_bias_escalation(sample_application, orch_mocks):
    """Bias score > 80 -> immediate escalation to human review."""
    orch_mocks["predictor"].return_value.predict.return_value = _prediction(
        "approved", 0.85, orch_mocks["model_version_id"]
    )
    orch_mocks["email_gen"].return_value.generate.return_value = _email()

    orch_mocks["bias"].return_value.analyze.return_value = _bias(85, flagged=True)

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "escalated"
    sample_application.refresh_from_db()
    assert sample_application.status == "review"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_moderate_bias_reviewer_rejects(sample_application, orch_mocks):
    """Bias score above threshold -> direct escalation to human review (no AI reviewer)."""
    orch_mocks["predictor"].return_value.predict.return_value = _prediction(
        "approved", 0.85, orch_mocks["model_version_id"]
    )
    orch_mocks["email_gen"].return_value.generate.return_value = _email()

    orch_mocks["bias"].return_value.analyze.return_value = _bias(70, flagged=True)

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "escalated"
    sample_application.refresh_from_db()
    assert sample_application.status == "review"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_moderate_bias_reviewer_approves(sample_application, orch_mocks):
    """Bias score above threshold -> direct escalation (no AI reviewer step)."""
    orch_mocks["predictor"].return_value.predict.return_value = _prediction(
        "approved", 0.85, orch_mocks["model_version_id"]
    )
    orch_mocks["email_gen"].return_value.generate.return_value = _email()

    orch_mocks["bias"].return_value.analyze.return_value = _bias(65, flagged=True)

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "escalated"
    sample_application.refresh_from_db()
    assert sample_application.status == "review"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_stale_pipeline_resets(sample_application, orch_mocks):
    """Application stuck in processing >10 min gets reset and proceeds."""
    _wire_approved(orch_mocks)
    sample_application.status = "processing"
    sample_application.save()
    LoanApplication.objects.filter(pk=sample_application.pk).update(updated_at=timezone.now() - timedelta(minutes=15))

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == "completed"
    sample_application.refresh_from_db()
    assert sample_application.status == "approved"


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_concurrent_pipeline_rejected(sample_application, orch_mocks):
    """Application currently processing (recent updated_at) raises ValueError."""
    sample_application.status = "processing"
    sample_application.save()

    from apps.agents.services.orchestrator import PipelineOrchestrator

    with pytest.raises(ValueError, match="Pipeline already running"):
        PipelineOrchestrator().orchestrate(sample_application.pk)


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_no_profile_graceful_degradation(application_no_profile, orch_mocks):
    """Pipeline runs even with a default (empty) CustomerProfile.

    The auto-create signal creates a profile with zeroed balances, so
    profile_context is present but contains defaults. The pipeline must
    still complete without error.
    """
    _wire_approved(orch_mocks)

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(application_no_profile.pk)

    assert run.status == "completed"
    application_no_profile.refresh_from_db()
    assert application_no_profile.status == "approved"
    # profile_context is passed (auto-created profile) — pipeline should still work
    call_args = orch_mocks["email_gen"].return_value.generate.call_args
    assert "profile_context" in call_args.kwargs


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_llm_calls_run_inside_application_and_run_context(sample_application, orch_mocks):
    """I6: every LLM call made during a run is attributable to the application
    and the AgentRun in the APP 8 log (guarded_api_call reads this context)."""
    from apps.agents.services.api_budget import current_api_call_context

    _wire_approved(orch_mocks)
    seen = {}

    def _generate(*args, **kwargs):
        seen.update(current_api_call_context())
        return _email()

    orch_mocks["email_gen"].return_value.generate.side_effect = _generate

    from apps.agents.services.orchestrator import PipelineOrchestrator

    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert seen.get("application_id") == sample_application.pk
    assert seen.get("agent_run_id") == run.pk
    assert current_api_call_context() == {}, "context must not leak past the run"
