"""The next-best offer reaches the denial email at every integration point.

``build_denial_email_context`` puts the first RecommendationEngine offer into
``profile_context["nbo_offer"]``. These tests follow that value through the
places that issue a denial email without the LLM writing it:

* the pipeline's moderate band, when Agent 2 is disabled or hands over and the
  deterministic template replaces the flagged email;
* ``generate_decision_email``'s rate-limit fallback to the template;
* the staff-triggered ``generate_email_task``, which builds the denial
  context itself;
* the HTML render of a denial template that carries an offer.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.agents.models import AgentRun
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.exceptions import RateLimited

from .test_bias_moderate_band import CLEAN, MODERATE, _llm_email, processing_denied  # noqa: F401 - fixture reuse

__all__ = ["processing_denied"]

SENDER = "apps.email_engine.services.sender.send_decision_email"
AGENT2 = "apps.agents.services.bias_agent2"
PIPELINE = "apps.agents.services.email_pipeline"

# Keys copied from RecommendationEngine.recommend()'s offer dicts
# (apps/agents/services/recommendation_engine.py).
OFFER = {
    "type": "reduced_loan",
    "name": "Reduced Amount Loan",
    "amount": 15000,
    "term_months": 36,
    "estimated_rate": 9.99,
    "monthly_repayment": 484,
    "reason": "A smaller amount fits your current surplus",
}


def _run_moderate_pipeline(application, *, agent2_review=None):
    """Moderate band: the LLM email is flagged, the template replacement checks clean."""
    from apps.agents.services.email_pipeline import EmailPipelineService
    from apps.agents.services.step_tracker import StepTracker

    run = AgentRun.objects.create(application=application, status="running", steps=[])
    send = MagicMock(return_value={"sent": True})
    rewrite = {**_llm_email(), "body": "Dear Customer, Agent 2 rewritten body."}
    with (
        patch.object(EmailGenerator, "generate", side_effect=[_llm_email(), rewrite]),
        patch(f"{PIPELINE}.BiasDetector") as bias,
        patch(f"{AGENT2}.BiasDetector") as agent2_bias,
        patch(f"{AGENT2}.AIEmailReviewer") as agent2_reviewer,
        patch(f"{AGENT2}.ApiBudgetGuard"),
        patch(f"{PIPELINE}.RecommendationEngine") as nbo,
        patch(SENDER, send),
    ):
        bias.return_value.analyze.side_effect = [MODERATE, CLEAN]
        agent2_bias.return_value.analyze.return_value = CLEAN
        if agent2_review is not None:
            agent2_reviewer.return_value.review.return_value = agent2_review
        nbo.return_value.recommend.return_value = {"offers": [OFFER]}
        _, email_result, _, _, escalated = EmailPipelineService(StepTracker()).run(
            application, run, {}, {"probability": 0.2}, "denied", [], []
        )
    return email_result, escalated, send


@pytest.mark.django_db
@override_settings(BIAS_AGENT2_ENABLED=False)
def test_moderate_band_template_replacement_carries_the_offer_with_agent2_disabled(processing_denied):
    email_result, escalated, send = _run_moderate_pipeline(processing_denied)

    assert not escalated
    assert email_result["template_fallback"] is True
    assert send.call_count == 1
    sent_body = send.call_args.args[2]
    assert "$15,000" in sent_body
    assert "Reduced Amount Loan" in sent_body


@pytest.mark.django_db
def test_moderate_band_template_replacement_carries_the_offer_after_agent2_hands_over(processing_denied):
    email_result, escalated, send = _run_moderate_pipeline(
        processing_denied, agent2_review={"approved": False, "confidence": 0.95, "reasoning": "tone"}
    )

    assert not escalated
    assert email_result["template_fallback"] is True
    assert "$15,000" in send.call_args.args[2]


@pytest.mark.django_db
def test_rate_limit_fallback_template_carries_the_offer(processing_denied):
    from apps.email_engine.services.decision_email import generate_decision_email

    with patch.object(EmailGenerator, "generate", side_effect=RateLimited("429")):
        result, generated = generate_decision_email(
            processing_denied, "denied", confidence=0.2, profile_context={"nbo_offer": OFFER}
        )

    assert result["template_fallback"] is True
    assert "$15,000" in result["body"]
    assert "$15,000" in generated.body


@pytest.mark.django_db
def test_staff_triggered_denial_email_task_passes_the_offer_to_the_generator(processing_denied):
    from apps.email_engine.tasks import generate_email_task

    template = EmailGenerator().generate_template(processing_denied, "denied")
    with (
        patch.object(EmailGenerator, "generate", return_value=template) as generate,
        patch(f"{PIPELINE}.RecommendationEngine") as nbo,
        patch(SENDER, MagicMock(return_value={"sent": True})),
    ):
        nbo.return_value.recommend.return_value = {"offers": [OFFER]}
        result = generate_email_task.apply(args=(str(processing_denied.pk), "denied"))

    assert not isinstance(result.result, Exception), result.result
    generate.assert_called_once()
    assert (generate.call_args.kwargs.get("profile_context") or {}).get("nbo_offer") == OFFER


@pytest.mark.django_db
def test_staff_triggered_approval_email_task_builds_no_offer(sample_application):
    from apps.email_engine.tasks import generate_email_task
    from apps.loans.models import LoanDecision

    LoanDecision.objects.create(application=sample_application, decision="approved", confidence=0.9)
    template = EmailGenerator().generate_template(sample_application, "approved")
    with (
        patch.object(EmailGenerator, "generate", return_value=template) as generate,
        patch(f"{PIPELINE}.RecommendationEngine") as nbo,
        patch(SENDER, MagicMock(return_value={"sent": True})),
    ):
        generate_email_task.apply(args=(str(sample_application.pk), "approved"))

    nbo.assert_not_called()
    assert not (generate.call_args.kwargs.get("profile_context") or {}).get("nbo_offer")


def test_denial_html_render_shows_the_offer_name():
    from apps.email_engine.services.html_renderer import render_html
    from apps.email_engine.services.template_fallback import generate_denial_template

    body = generate_denial_template("Jane Doe", 20000.0, "Personal Loan", nbo_offer=OFFER)["body"]

    html = render_html(body, "denial")

    assert "Reduced Amount Loan" in html
    assert "$15,000" in html
