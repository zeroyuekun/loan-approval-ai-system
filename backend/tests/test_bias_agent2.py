"""Agent 2: a bias-flagged decision email gets rewritten with reviewer feedback.

``EmailGenerator.generate`` accepts ``bias_feedback`` and appends it to the
prompt as a compliance-review note. ``regenerate_decision_email`` wraps the
rewrite and persists it — unless the generator degraded to the template,
which is never persisted here because the template-replacement path (see
``test_bias_moderate_band.py``) persists its own template.
"""

from unittest.mock import MagicMock, patch

import pytest

from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.email_generator import EmailGenerator

from .test_bias_moderate_band import _llm_email, processing_denied  # noqa: F401 - fixture + helper reuse

__all__ = ["processing_denied"]


@pytest.mark.django_db
def test_bias_feedback_reaches_the_prompt(processing_denied):
    gen = EmailGenerator()
    gen.client = object()  # pretend an LLM backend is configured
    captured = {}

    def _fake_call(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        raise RuntimeError("stop after prompt build")

    with (
        patch("apps.agents.services.api_budget.ApiBudgetGuard.check_budget"),
        patch("apps.agents.services.api_budget.guarded_api_call", _fake_call),
    ):
        try:
            gen.generate(processing_denied, "denied", bias_feedback="tone_check: labels the person")
        except Exception:
            pass

    assert "COMPLIANCE REVIEW FEEDBACK" in captured["prompt"]
    assert "tone_check: labels the person" in captured["prompt"]


@pytest.mark.django_db
def test_regenerate_does_not_persist_a_template_result(processing_denied):
    from apps.email_engine.services.decision_email import regenerate_decision_email

    gen = MagicMock()
    gen.generate.return_value = {**_llm_email(), "template_fallback": True}
    result, generated = regenerate_decision_email(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x", generator=gen
    )
    assert generated is None
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()


@pytest.mark.django_db
def test_regenerate_persists_a_non_template_result(processing_denied):
    from apps.email_engine.services.decision_email import regenerate_decision_email

    gen = MagicMock()
    gen.generate.return_value = _llm_email()
    result, generated = regenerate_decision_email(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x", generator=gen
    )
    assert generated is not None
    assert GeneratedEmail.objects.filter(application=processing_denied).exists()
    gen.generate.assert_called_once_with(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x"
    )
