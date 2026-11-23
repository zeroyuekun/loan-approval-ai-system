"""Every denial email gets an LLM screen for protected attributes, not only regex-flagged ones.

Before this, the LLM only saw emails whose regex score fell in the moderate band,
so an email the regex scored 0 ("As a young applicant you lack maturity") shipped
unread, and a junior "false positive" verdict on a flagged protected term
("pregnant") cleared the email on its own.
"""

import pytest

from apps.agents.services.bias.core import BiasDetector
from apps.agents.services.deterministic_prescreen import DeterministicBiasPreScreen

CORE_CALL = "apps.agents.services.bias.core._call_with_fallback"
DENIED = {"loan_amount": 25000, "purpose": "personal", "decision": "denied"}
APPROVED = {"loan_amount": 25000, "purpose": "personal", "decision": "approved"}


def _email(middle):
    return (
        "Dear Alex,\n\nThank you for applying for a $25,000 personal loan with AussieLoanAI. "
        f"{middle}\n\nIf you have questions, contact us on 1300 000 000.\n\nKind regards,\nAussieLoanAI Lending Team"
    )


CLEAN = _email("We are unable to approve it. The requested amount exceeded our serviceability thresholds.")
PREGNANT = _email("We are unable to approve it. You mentioned you are pregnant and may stop working soon.")


@pytest.fixture
def ollama(settings):
    settings.BIAS_LLM_BACKEND = "ollama"
    settings.BIAS_OLLAMA_MODEL = "llama3.1:8b"
    settings.BIAS_SCREEN_EVERY_DENIAL = True
    return settings


@pytest.fixture
def llm(monkeypatch):
    """Fake LLM calls keyed by service: {"bias_detection": {...}, "bias_full_screen": {...}}."""
    calls = []
    replies = {}

    def fake(client, fallback, *args, **kwargs):
        calls.append(kwargs)
        return replies.get(kwargs["_service"], fallback)

    monkeypatch.setattr(CORE_CALL, fake)
    return calls, replies


def _services(calls):
    return [c["_service"] for c in calls]


def test_clean_denial_is_screened_by_the_llm_and_sent_when_screen_is_clean(ollama, llm):
    calls, replies = llm
    replies["bias_full_screen"] = {"score": 5, "categories": [], "analysis": "No protected attribute."}

    result = BiasDetector().analyze(CLEAN, DENIED)

    assert _services(calls) == ["bias_full_screen"]
    assert result["flagged"] is False
    assert result["requires_human_review"] is False


def test_clean_denial_is_flagged_when_the_screen_finds_a_protected_attribute(ollama, llm):
    calls, replies = llm
    replies["bias_full_screen"] = {"score": 85, "categories": ["age"], "analysis": "Age used as a reason."}
    # Coded age wording that no regex pattern matches: only the LLM can catch it.
    email = _email("We are unable to approve it. People at your stage of life rarely keep up repayments.")

    result = BiasDetector().analyze(email, DENIED)

    assert _services(calls) == ["bias_full_screen"]
    assert result["flagged"] is True
    assert result["requires_human_review"] is True
    assert result["score"] == 85
    assert result["score_source"] == "llm_full_screen"
    assert result["categories"] == ["age"]


def test_junior_false_positive_on_a_protected_term_does_not_clear_the_email_alone(ollama, llm):
    calls, replies = llm
    replies["bias_detection"] = {"score": 0, "categories": [], "analysis": "False positive."}
    replies["bias_full_screen"] = {"score": 90, "categories": ["pregnancy"], "analysis": "Pregnancy cited."}

    result = BiasDetector().analyze(PREGNANT, DENIED)

    assert _services(calls) == ["bias_detection", "bias_full_screen"]
    assert result["flagged"] is True
    assert result["score"] == 90


def test_screen_failure_holds_the_email_instead_of_sending_it(ollama, llm):
    """No reply (outage) falls back to a moderate score, so the email is never sent unread."""
    calls, _ = llm

    result = BiasDetector().analyze(CLEAN, DENIED)

    assert _services(calls) == ["bias_full_screen"]
    assert result["flagged"] is True
    assert 30 < result["score"] < 60


def test_approval_emails_are_not_screened(ollama, llm):
    calls, _ = llm
    result = BiasDetector().analyze(CLEAN, APPROVED)
    assert calls == []
    assert result["flagged"] is False


def test_screen_can_be_switched_off(ollama, llm):
    ollama.BIAS_SCREEN_EVERY_DENIAL = False
    calls, _ = llm
    BiasDetector().analyze(CLEAN, DENIED)
    assert calls == []


def test_severe_regex_violation_is_blocked_without_the_screen(ollama, llm):
    calls, _ = llm
    email = _email("Your loan was denied because of your ethnic background and gender. You are an idiot.")
    result = BiasDetector().analyze(email, DENIED)
    assert calls == []
    assert result["flagged"] is True


def test_no_llm_backend_configured_keeps_the_deterministic_result(settings, llm):
    settings.BIAS_LLM_BACKEND = "anthropic"
    settings.ANTHROPIC_API_KEY = ""
    calls, _ = llm
    detector = BiasDetector()
    detector.client = None
    result = detector.analyze(CLEAN, DENIED)
    assert calls == []
    assert result["flagged"] is False


def test_both_prompts_say_protected_attributes_as_reasons_are_never_false_positives(ollama, llm):
    calls, replies = llm
    replies["bias_detection"] = {"score": 0, "categories": [], "analysis": "False positive."}
    replies["bias_full_screen"] = {"score": 0, "categories": [], "analysis": "ok"}

    BiasDetector().analyze(PREGNANT, DENIED)

    for call in calls:
        prompt = call["messages"][0]["content"]
        assert "pregnancy" in prompt.lower()
        assert "never a false positive" in prompt.lower()


# --- Deterministic pre-screen: wording the regex used to miss ---------------------------


@pytest.mark.parametrize(
    "middle",
    [
        "As a young applicant you lack the maturity we look for.",
        "You are too old for a loan term of this length.",
        "You are unemployed, so we cannot proceed.",
        "You cannot afford this loan.",
        "You're a high risk borrower.",
    ],
)
def test_prescreen_flags_age_wording_and_labelling_the_person(middle):
    result = DeterministicBiasPreScreen().prescreen_decision_email(_email(middle), DENIED)
    assert not result["all_clean"]
    assert "Age Or Labelling Language" in [f["check_name"] for f in result["findings"]]
    assert 30 < result["deterministic_score"] < 60


@pytest.mark.parametrize(
    "middle",
    [
        "The loan maturity date would fall after your fixed-rate period ends.",
        "Your employment status at the time of application was a factor.",
        "The requested amount exceeded our serviceability thresholds.",
        "Customers with a young family can apply for our Family Saver account.",
    ],
)
def test_prescreen_leaves_ordinary_lending_language_alone(middle):
    result = DeterministicBiasPreScreen().prescreen_decision_email(_email(middle), DENIED)
    assert "Age Or Labelling Language" not in [f["check_name"] for f in result["findings"]]
