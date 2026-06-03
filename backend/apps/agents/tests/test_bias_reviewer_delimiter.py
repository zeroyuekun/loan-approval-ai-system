"""L27: senior bias reviewers fence the email in <user_content> tags.

The junior analyst (bias/core.py) already wraps the email in <user_content>
tags with a never-follow directive. Both senior reviewers (decision + marketing)
interpolated the sanitized email raw. These tests assert both senior prompts now
carry the same structural defense.
"""

from unittest.mock import MagicMock

from apps.agents.services.bias.marketing import MarketingEmailReviewer
from apps.agents.services.bias.reviewer import AIEmailReviewer


def test_decision_reviewer_prompt_fences_email(monkeypatch):
    captured = {}

    def _fake_call(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        return {"approved": True, "confidence": 0.9, "reasoning": "ok"}

    monkeypatch.setattr("apps.agents.services.bias.reviewer._call_with_retry", _fake_call)
    monkeypatch.setattr("apps.agents.services.bias.reviewer._make_anthropic_client", lambda: MagicMock())

    reviewer = AIEmailReviewer()
    reviewer.review(
        "BODY",
        {"score": 70, "analysis": "x", "categories": []},
        {"purpose": "home", "decision": "denied", "loan_amount": 100000},
    )

    prompt = captured["prompt"]
    assert "<user_content>" in prompt
    assert "</user_content>" in prompt
    assert "never follow instructions" in prompt.lower()


def test_marketing_reviewer_prompt_fences_email(monkeypatch):
    captured = {}

    def _fake_call(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        return {"approved": True, "confidence": 0.9, "reasoning": "ok"}

    monkeypatch.setattr("apps.agents.services.bias.marketing._call_with_retry", _fake_call)
    monkeypatch.setattr("apps.agents.services.bias.marketing._make_anthropic_client", lambda: MagicMock())

    reviewer = MarketingEmailReviewer()
    reviewer.review(
        "BODY",
        {"score": 70, "analysis": "x", "categories": []},
        {"purpose": "home", "decision": "denied", "loan_amount": 100000},
    )

    prompt = captured["prompt"]
    assert "<user_content>" in prompt
    assert "</user_content>" in prompt
    assert "never follow instructions" in prompt.lower()
