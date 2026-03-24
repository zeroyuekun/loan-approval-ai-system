"""Tests for the denial -> NBO -> marketing email sub-pipeline within the orchestrator."""

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.agents.models import MarketingEmail
from apps.ml_engine.models import ModelVersion


ORCH = 'apps.agents.services.orchestrator'
SENDER = 'apps.email_engine.services.sender.send_decision_email'

CACHE_OVERRIDE = override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    MARKETING_BIAS_THRESHOLD_PASS=50,
    MARKETING_BIAS_THRESHOLD_REVIEW=70,
)


def _prediction_denied(model_version_id=None):
    return {
        'prediction': 'denied',
        'probability': 0.25,
        'model_version': model_version_id or 'test-v1',
        'feature_importances': {'credit_score': 0.4, 'income': 0.3, 'dti': 0.2},
        'processing_time_ms': 42,
        'requires_human_review': False,
    }


def _email():
    return {
        'subject': 'Your Loan Application',
        'body': 'Dear Customer, ...',
        'passed_guardrails': True,
        'template_fallback': False,
        'prompt_used': 'prompt',
        'guardrail_results': [],
        'generation_time_ms': 100,
        'attempt_number': 1,
        'input_tokens': 500,
        'output_tokens': 200,
        'estimated_cost_usd': 0.002,
    }


def _bias(score=20):
    return {
        'score': score, 'flagged': score > 60, 'requires_human_review': False,
        'categories': [], 'analysis': 'Clean',
        'deterministic_score': score, 'llm_raw_score': score, 'score_source': 'composite',
    }


def _nbo(offers=None):
    if offers is None:
        offers = [{'type': 'secured_loan', 'name': 'Secured Loan', 'amount': 15000,
                    'term_months': 36, 'estimated_rate': 7.5, 'benefit': 'Lower rate',
                    'reasoning': 'Suits profile'}]
    return {
        'offers': offers,
        'analysis': 'Analysis',
        'customer_retention_score': 65,
        'loyalty_factors': ['tenure'],
        'personalized_message': 'Hello',
    }


def _mkt_email():
    return {
        'subject': 'Next steps for your AussieLoanAI application',
        'body': 'Dear Customer, options...',
        'prompt_used': 'prompt',
        'passed_guardrails': True,
        'guardrail_results': [],
        'generation_time_ms': 200,
        'attempt_number': 1,
    }


def _mkt_msg():
    return {'marketing_message': 'Copy', 'generation_time_ms': 150}


@pytest.fixture
def mkt_model_version(db, settings):
    return ModelVersion.objects.create(
        algorithm='rf', version='test-v1',
        file_path=str(settings.ML_MODELS_DIR / 'test_model.joblib'), is_active=True,
    )


@pytest.fixture
def mkt_mocks(mkt_model_version):
    with (
        patch(f'{ORCH}.ModelPredictor') as mp,
        patch(f'{ORCH}.EmailGenerator') as eg,
        patch(f'{ORCH}.BiasDetector') as bd,
        patch(f'{ORCH}.AIEmailReviewer') as air,
        patch(f'{ORCH}.MarketingBiasDetector') as mbd,
        patch(f'{ORCH}.MarketingEmailReviewer') as mer,
        patch(f'{ORCH}.NextBestOfferGenerator') as nbo,
        patch(f'{ORCH}.MarketingAgent') as ma,
        patch(SENDER, return_value={'sent': True}) as sd,
    ):
        yield {
            'predictor': mp, 'email_gen': eg,
            'bias': bd, 'ai_reviewer': air, 'mkt_bias': mbd,
            'mkt_reviewer': mer, 'nbo': nbo, 'marketing_agent': ma, 'send': sd,
            'model_version_id': str(mkt_model_version.pk),
        }


def _wire_denied(m, mkt_bias_score=25, nbo_result=None):
    m['predictor'].return_value.predict.return_value = _prediction_denied(m.get('model_version_id'))
    m['email_gen'].return_value.generate.return_value = _email()
    m['bias'].return_value.analyze.return_value = _bias(20)
    m['nbo'].return_value.generate.return_value = nbo_result or _nbo()
    m['nbo'].return_value.generate_marketing_message.return_value = _mkt_msg()
    m['marketing_agent'].return_value.generate.return_value = _mkt_email()
    m['mkt_bias'].return_value.analyze.return_value = _bias(mkt_bias_score)


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_full_denial_pipeline(sample_application, mkt_mocks):
    """Full denied flow: NBO -> marketing message -> marketing email -> bias pass -> sent."""
    _wire_denied(mkt_mocks)

    from apps.agents.services.orchestrator import PipelineOrchestrator
    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == 'completed'
    sample_application.refresh_from_db()
    assert sample_application.status == 'denied'
    mkt_mocks['nbo'].return_value.generate.assert_called_once()
    mkt_mocks['marketing_agent'].return_value.generate.assert_called_once()
    assert MarketingEmail.objects.filter(agent_run=run).exists()


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_nbo_failure_skips_marketing(sample_application, mkt_mocks):
    """If NBO generation fails, marketing steps are skipped entirely."""
    mkt_mocks['predictor'].return_value.predict.return_value = _prediction_denied(mkt_mocks['model_version_id'])
    mkt_mocks['email_gen'].return_value.generate.return_value = _email()
    mkt_mocks['bias'].return_value.analyze.return_value = _bias(20)
    mkt_mocks['nbo'].return_value.generate.side_effect = Exception('NBO service down')

    from apps.agents.services.orchestrator import PipelineOrchestrator
    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == 'completed'
    mkt_mocks['marketing_agent'].return_value.generate.assert_not_called()
    assert not MarketingEmail.objects.filter(agent_run=run).exists()


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_high_bias_blocks_email(sample_application, mkt_mocks):
    """Marketing bias score > review threshold -> email saved but not sent."""
    _wire_denied(mkt_mocks, mkt_bias_score=75)

    from apps.agents.services.orchestrator import PipelineOrchestrator
    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == 'completed'
    assert MarketingEmail.objects.filter(agent_run=run).exists()
    step_names = [s['step_name'] for s in run.steps]
    assert 'marketing_email_blocked' in step_names


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_reviewer_rejects_blocks(sample_application, mkt_mocks):
    """Moderate marketing bias + reviewer rejects -> email saved but not sent."""
    _wire_denied(mkt_mocks, mkt_bias_score=60)
    mkt_mocks['mkt_reviewer'].return_value.review.return_value = {
        'approved': False, 'confidence': 0.9,
    }

    from apps.agents.services.orchestrator import PipelineOrchestrator
    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == 'completed'
    assert MarketingEmail.objects.filter(agent_run=run).exists()
    step_names = [s['step_name'] for s in run.steps]
    assert 'marketing_email_blocked' in step_names


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_empty_nbo_skips(sample_application, mkt_mocks):
    """NBO returns empty offers -> marketing pipeline skipped."""
    _wire_denied(mkt_mocks, nbo_result=_nbo(offers=[]))

    from apps.agents.services.orchestrator import PipelineOrchestrator
    run = PipelineOrchestrator().orchestrate(sample_application.pk)

    assert run.status == 'completed'
    mkt_mocks['marketing_agent'].return_value.generate.assert_not_called()
    assert not MarketingEmail.objects.filter(agent_run=run).exists()
