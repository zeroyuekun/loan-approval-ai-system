"""The bias second check, run end to end through the real Groq client.

The other bias tests replace ``_call_with_fallback`` with a fake, so they never
prove the Groq path works: the request shape Groq receives, the forced tool
call it returns, and how that reply becomes a verdict. Here only the HTTP layer
is faked. Everything from ``BiasDetector.analyze`` down to the
``OpenAICompatibleLLMClient`` payload and response parsing is the real code.

The scenario that needs a second check: a denial cites the applicant's
pregnancy. The regex pre-screen flags "pregnant" as a moderate finding, and the
first check (the junior analyst) wrongly calls it a false positive. Without the
second check that verdict alone would clear the email and it would be sent.
The second check reads the whole email, finds pregnancy used as a reason, and
holds the email for a human.
"""

import json
from unittest.mock import MagicMock

import httpx
import pytest

from apps.agents.services import api_budget
from apps.agents.services.bias.core import BiasDetector

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DENIED = {"loan_amount": 25000, "purpose": "personal", "decision": "denied"}


def _email(middle):
    return (
        "Dear Alex,\n\nThank you for applying for a $25,000 personal loan with AussieLoanAI. "
        f"{middle}\n\nIf you have questions, contact us on 1300 000 000.\n\nKind regards,\nAussieLoanAI Lending Team"
    )


PREGNANT = _email("We are unable to approve it. You mentioned you are pregnant and may stop working soon.")
STAGE_OF_LIFE = _email("We are unable to approve it. People at your stage of life rarely keep up repayments.")
CLEAN = _email("We are unable to approve it. The requested amount exceeded our serviceability thresholds.")


def _tool_reply(score, categories, analysis):
    """A Groq chat completion carrying a forced record_bias_analysis tool call."""
    args = json.dumps({"analysis": analysis, "categories": categories, "score": score})
    return httpx.Response(
        200,
        request=httpx.Request("POST", GROQ_URL),
        json={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [{"function": {"name": "record_bias_analysis", "arguments": args}}],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 900, "completion_tokens": 60},
        },
    )


@pytest.fixture
def groq(settings, monkeypatch):
    """Groq configured as the bias backend, with its HTTP layer faked.

    Returns ``(sent, replies)``: ``sent`` collects every request body posted to
    Groq; ``replies`` is a list of responses handed out in call order.
    """
    settings.BIAS_LLM_BACKEND = "groq"
    settings.GROQ_API_KEY = "test-groq-key"
    settings.GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    settings.BIAS_GROQ_MODEL = "openai/gpt-oss-20b"
    settings.BIAS_SCREEN_EVERY_DENIAL = True
    settings.BIAS_THRESHOLD_PASS = 30
    settings.BIAS_THRESHOLD_REVIEW = 60

    # Budget guard and APP 8 audit log need Redis and the database; they are not
    # what this test is about. Record the audit rows so the provider can be checked.
    guard = MagicMock()
    guard.reserve_budget.return_value = 0
    monkeypatch.setattr(api_budget, "ApiBudgetGuard", lambda: guard)
    audit = []
    monkeypatch.setattr(api_budget, "_log_api_call", lambda kwargs, **fields: audit.append(fields))

    # The bias client is cached per worker process; the root conftest clears
    # that cache around every test, so this client is fresh.
    sent = []
    replies = []

    def fake_post(url, headers=None, json=None):
        sent.append({"url": url, "headers": headers, "body": json})
        return replies.pop(0)

    detector = BiasDetector()
    assert detector.client is not None, "groq backend with a key must build a client"
    detector.client._http = MagicMock(post=MagicMock(side_effect=fake_post))
    return detector, sent, replies, audit


def test_second_check_catches_bias_the_first_check_cleared(groq):
    detector, sent, replies, audit = groq
    replies.extend(
        [
            # First check: the junior analyst wrongly calls the flag a false positive.
            _tool_reply(5, [], "Flag 1 is a false positive."),
            # Second check: the full-email screen sees pregnancy cited as a reason.
            _tool_reply(90, ["gender"], "'you are pregnant and may stop working soon' is cited as a reason."),
        ]
    )

    result = detector.analyze(PREGNANT, DENIED)

    # Two calls reached Groq: the first check, then the second.
    assert len(sent) == 2
    assert [row["service"] for row in audit] == ["bias_detection", "bias_full_screen"]
    assert {row["provider"] for row in audit} == {"groq"}

    # The email is held for a human, and the verdict comes from the second check.
    assert result["llm_raw_score"] == 5
    assert result["full_screen_score"] == 90
    assert result["score"] == 90
    assert result["score_source"] == "llm_full_screen"
    assert result["flagged"] is True
    assert result["requires_human_review"] is True
    assert "pregnant" in result["analysis"]


def test_requests_reach_groq_in_the_shape_groq_accepts(groq):
    detector, sent, replies, _ = groq
    replies.extend([_tool_reply(5, [], "False positive."), _tool_reply(90, ["gender"], "Pregnancy cited.")])

    detector.analyze(PREGNANT, DENIED)

    for request in sent:
        body = request["body"]
        assert request["url"] == GROQ_URL
        assert request["headers"]["Authorization"] == "Bearer test-groq-key"
        assert body["model"] == "openai/gpt-oss-20b"
        assert body["temperature"] == 0.0
        # Groq gets OpenAI function calling, forced to the bias tool; never the
        # json_schema response_format used for Ollama.
        assert body["tool_choice"] == {"type": "function", "function": {"name": "record_bias_analysis"}}
        assert [t["function"]["name"] for t in body["tools"]] == ["record_bias_analysis"]
        assert "response_format" not in body
    # The second check reads the whole email, not just the flagged phrase.
    second_prompt = sent[1]["body"]["messages"][0]["content"]
    assert "Read the whole email" in second_prompt
    assert "you are pregnant and may stop working soon" in second_prompt


def test_second_check_alone_catches_coded_wording_no_regex_matches(groq):
    """No regex flag, so the first check never runs; only the second check reads the email."""
    detector, sent, replies, audit = groq
    replies.append(_tool_reply(85, ["age"], "'People at your stage of life' uses age as a reason."))

    result = detector.analyze(STAGE_OF_LIFE, DENIED)

    assert [row["service"] for row in audit] == ["bias_full_screen"]
    assert result["flagged"] is True
    assert result["requires_human_review"] is True
    assert result["score"] == 85
    assert result["categories"] == ["age"]


def test_clean_denial_passes_the_second_check_and_is_sent(groq):
    detector, sent, replies, audit = groq
    replies.append(_tool_reply(5, [], "No protected attribute; the application is described, not the person."))

    result = detector.analyze(CLEAN, DENIED)

    assert [row["service"] for row in audit] == ["bias_full_screen"]
    assert result["full_screen_score"] == 5
    assert result["flagged"] is False
    assert result["requires_human_review"] is False


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(429, request=httpx.Request("POST", GROQ_URL), headers={"retry-after": "7"}),
        httpx.Response(500, request=httpx.Request("POST", GROQ_URL), text="upstream error"),
    ],
    ids=["rate-limited", "server-error"],
)
def test_groq_failure_on_the_second_check_holds_the_email(groq, failure):
    """If Groq cannot answer the second check, the email waits for a human, never sent unread."""
    detector, sent, replies, _ = groq
    replies.extend([_tool_reply(5, [], "False positive."), failure])

    result = detector.analyze(PREGNANT, DENIED)

    assert len(sent) == 2
    assert result["flagged"] is True
    assert result["requires_human_review"] is True
    assert "full_screen_unavailable" in result["categories"]
    assert 30 < result["score"] < 60
