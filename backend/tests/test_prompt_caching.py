"""Prompt caching wiring — denial path + helper.

The helper (``utils.api_helpers.build_cached_call_kwargs``) wraps the
static instruction block in Anthropic prompt caching's ``cache_control:
ephemeral`` form. The denial email path uses it so the ~4.5k-token
DENIAL_EMAIL_INSTRUCTIONS get cached server-side for 5 min — bringing
input cost on cache hits down to 10% of the normal rate.

Coverage:
- helper produces the expected shape
- denial path API call carries cache_control on the system block
- denial path API call sends the dynamic application data as the user
  message (not in the cached system block)
- approval path is untouched — still single user-message format
- the cached instructions are large enough to actually trigger
  caching (Sonnet minimum is 1024 tokens)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from utils.api_helpers import build_cached_call_kwargs

# ---------------------------------------------------------------------------
# Helper shape
# ---------------------------------------------------------------------------


def test_helper_returns_system_and_messages():
    kw = build_cached_call_kwargs(
        system_text="Static instructions here.",
        user_text="Dynamic user data here.",
    )
    assert "system" in kw and "messages" in kw
    assert isinstance(kw["system"], list)
    assert len(kw["system"]) == 1


def test_helper_system_block_has_cache_control():
    kw = build_cached_call_kwargs(
        system_text="Some instructions.",
        user_text="Data.",
    )
    block = kw["system"][0]
    assert block["type"] == "text"
    assert block["text"] == "Some instructions."
    assert block["cache_control"] == {"type": "ephemeral"}


def test_helper_user_message_carries_dynamic_text():
    kw = build_cached_call_kwargs(
        system_text="Instructions",
        user_text="Applicant: Jane Doe, Loan: $50k",
    )
    assert kw["messages"] == [
        {"role": "user", "content": "Applicant: Jane Doe, Loan: $50k"}
    ]


def test_helper_passes_through_extra_kwargs():
    kw = build_cached_call_kwargs(
        system_text="x",
        user_text="y",
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0.0,
        tools=[{"name": "submit_email"}],
        tool_choice={"type": "tool", "name": "submit_email"},
    )
    assert kw["model"] == "claude-sonnet-4-6"
    assert kw["max_tokens"] == 2048
    assert kw["temperature"] == 0.0
    assert kw["tools"] == [{"name": "submit_email"}]
    assert kw["tool_choice"] == {"type": "tool", "name": "submit_email"}


# ---------------------------------------------------------------------------
# DENIAL_EMAIL_INSTRUCTIONS — large enough to actually cache
# ---------------------------------------------------------------------------


# Anthropic prompt-caching minimums by model family (in tokens). The
# cache_control directive is silently a no-op below these thresholds, so
# the prompt must clear the floor for the active model.
# Docs: https://docs.claude.com/en/docs/build-with-claude/prompt-caching
_CACHE_MIN_TOKENS_BY_MODEL = {
    "claude-opus-4-7": 1024,
    "claude-opus-4-6": 1024,
    "claude-sonnet-4-6": 1024,
    "claude-sonnet-4-20250514": 1024,
    "claude-haiku-4-5-20251001": 2048,  # Haiku family needs 2× the tokens
    "claude-haiku-4-20250514": 2048,
}

# The email generator currently hardcodes this model at
# email_generator.py:_model (inside .generate). If you swap it, update
# this constant — the floor changes by family, and the test below catches
# the case where someone moves to Haiku but the prompt stays the same
# length and caching silently no-ops.
_ACTIVE_EMAIL_MODEL = "claude-sonnet-4-6"


def test_denial_instructions_meets_active_model_cache_minimum():
    """The cache_control directive on DENIAL_EMAIL_INSTRUCTIONS only
    actually caches if the block clears the active model's token floor.
    We use a conservative 4-char/token heuristic — real English averages
    closer to 3.5, so this floor is on the safe side. The real template
    is ~17k chars; this guards against (a) future shrinking that drops
    below the Sonnet floor, and (b) a model swap to Haiku that silently
    raises the floor without anyone noticing the regression."""
    from apps.email_engine.services.prompts import DENIAL_EMAIL_INSTRUCTIONS

    min_tokens = _CACHE_MIN_TOKENS_BY_MODEL[_ACTIVE_EMAIL_MODEL]
    floor_chars = min_tokens * 4  # 4 chars/token conservative heuristic

    assert len(DENIAL_EMAIL_INSTRUCTIONS) >= floor_chars, (
        f"DENIAL_EMAIL_INSTRUCTIONS is {len(DENIAL_EMAIL_INSTRUCTIONS)} chars "
        f"(~{len(DENIAL_EMAIL_INSTRUCTIONS) // 4} tokens) — below the "
        f"{_ACTIVE_EMAIL_MODEL} cache-eligibility minimum of ~{min_tokens} "
        f"tokens ({floor_chars} chars at 4 char/token). cache_control will be "
        "a silent no-op until the prompt grows back above the floor."
    )


def test_denial_instructions_has_no_format_placeholders():
    """The instructions block becomes the cached system prompt. If it
    contains ``{}`` placeholders, ``.format()`` calls in callers
    accidentally hitting the wrong constant would either KeyError or
    silently substitute, and the cache key would shift per call.
    The dynamic data lives in DENIAL_DATA_TEMPLATE instead."""
    # No bare {placeholder} patterns. We allow {{ }} literal braces
    # (none present today, but defensive in case future edits add them).
    import re

    from apps.email_engine.services.prompts import DENIAL_EMAIL_INSTRUCTIONS

    placeholders = re.findall(r"(?<!\{)\{[a-z_]+[^{}]*\}(?!\})", DENIAL_EMAIL_INSTRUCTIONS)
    assert placeholders == [], (
        f"DENIAL_EMAIL_INSTRUCTIONS still contains placeholders: {placeholders}. "
        "Move dynamic values to DENIAL_DATA_TEMPLATE so the instructions stay "
        "byte-identical across calls (required for prompt caching)."
    )


def test_denial_data_template_has_all_required_placeholders():
    """The data template is what gets .format()ed at call time. The
    full set is fixed by the caller in email_generator; missing one
    would crash on send."""
    from apps.email_engine.services.prompts import DENIAL_DATA_TEMPLATE

    for placeholder in (
        "{applicant_name}",
        "{loan_amount:,.2f}",
        "{purpose}",
        "{reasons}",
        "{banking_context}",
    ):
        assert placeholder in DENIAL_DATA_TEMPLATE, f"missing {placeholder}"


# ---------------------------------------------------------------------------
# email_generator denial path — actual API kwargs carry cache_control
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_api_call():
    """Patch guarded_api_call so we can inspect the kwargs the generator
    sends to Anthropic without making a real API call."""
    with patch(
        "apps.agents.services.api_budget.guarded_api_call"
    ) as mock_call:
        # Return a response shaped like a successful tool_use call so
        # the generator's downstream parsing doesn't crash.
        fake_response = MagicMock()
        fake_response.content = [
            MagicMock(
                type="tool_use",
                input={
                    "subject": "Update on Your Personal Loan Application",
                    "body": "Dear Test,\n\nThank you for applying...",
                },
            )
        ]
        fake_response.usage = MagicMock(input_tokens=4000, output_tokens=800, cache_read_input_tokens=0)
        fake_response.stop_reason = "tool_use"
        mock_call.return_value = fake_response
        yield mock_call


@pytest.fixture
def mock_email_application():
    """Build a minimal application-like mock that the generator can
    walk without needing a full ORM round-trip."""
    app = MagicMock()
    app.applicant.first_name = "Test"
    app.applicant.last_name = "Applicant"
    app.applicant.username = "testuser"
    app.loan_amount = 50000
    app.credit_score = 720  # needed by approval-path pricing engine
    app.loan_term_months = 60
    app.annual_income = 95000
    app.debt_to_income = 2.0
    app.employment_length = 5
    app.purpose = "personal"
    app.get_purpose_display.return_value = "Personal"
    app.get_employment_type_display.return_value = "PAYG Permanent"
    app.get_applicant_type_display.return_value = "Single"
    app.has_cosigner = False
    app.has_hecs = False
    # Profile + decision setups
    app.applicant.profile = None
    app.decision = None
    return app


@patch("apps.agents.services.api_budget.ApiBudgetGuard")
@patch("apps.email_engine.services.email_generator.anthropic.Anthropic")
def test_denial_path_uses_cached_system_block(
    mock_anthropic_cls,
    mock_budget_cls,
    captured_api_call,
    mock_email_application,
    monkeypatch,
):
    """End-to-end on the denial branch: the kwargs handed to
    guarded_api_call must contain a ``system`` list with cache_control
    on a block that holds the DENIAL_EMAIL_INSTRUCTIONS text."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Budget check passes
    mock_budget = MagicMock()
    mock_budget.check_budget.return_value = None
    mock_budget_cls.return_value = mock_budget
    mock_anthropic_cls.return_value = MagicMock()

    from apps.email_engine.services.email_generator import EmailGenerator
    from apps.email_engine.services.prompts import DENIAL_EMAIL_INSTRUCTIONS

    gen = EmailGenerator()
    # Make sure the generator believes the API is available
    gen._api_available = lambda: True

    gen.generate(
        application=mock_email_application,
        decision="denied",
        confidence=0.45,
    )

    # The captured fixture patches the api_budget module path; the
    # generator imports it lazily inside .generate so the patch hits.
    assert captured_api_call.called, "guarded_api_call was not invoked"
    kwargs = captured_api_call.call_args.kwargs

    # cache_control must be set on the system block
    assert "system" in kwargs, f"no system block in kwargs: {list(kwargs.keys())}"
    system_block = kwargs["system"][0]
    assert system_block["cache_control"] == {"type": "ephemeral"}, (
        f"cache_control wrong or missing: {system_block.get('cache_control')!r}"
    )
    # The cached text must actually be the denial instructions
    assert system_block["text"] == DENIAL_EMAIL_INSTRUCTIONS

    # The dynamic data (applicant name etc.) must be in the user message,
    # NOT in the cached system block (else cache key shifts per call).
    user_msg = kwargs["messages"][0]
    assert user_msg["role"] == "user"
    assert "Test Applicant" in user_msg["content"], (
        "applicant name should be in dynamic user message"
    )
    assert "Test Applicant" not in system_block["text"], (
        "applicant name leaked into cached system block — would break caching"
    )


@patch("apps.agents.services.api_budget.ApiBudgetGuard")
@patch("apps.email_engine.services.email_generator.anthropic.Anthropic")
def test_approval_path_unchanged_no_system_block(
    mock_anthropic_cls,
    mock_budget_cls,
    captured_api_call,
    mock_email_application,
    monkeypatch,
):
    """Until the approval template is also split, the approval path
    keeps the legacy single user-message format — no system block,
    no cache_control. Guards against the denial refactor accidentally
    bleeding into approvals."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_budget = MagicMock()
    mock_budget.check_budget.return_value = None
    mock_budget_cls.return_value = mock_budget
    mock_anthropic_cls.return_value = MagicMock()

    from apps.email_engine.services.email_generator import EmailGenerator

    gen = EmailGenerator()
    gen._api_available = lambda: True

    gen.generate(
        application=mock_email_application,
        decision="approved",
        confidence=0.91,
    )

    if not captured_api_call.called:
        # Approval may have short-circuited to template fallback for
        # other reasons (missing fields) — skip if so.
        pytest.skip("approval path took template fallback in this fixture")

    kwargs = captured_api_call.call_args.kwargs
    assert "system" not in kwargs, (
        "approval path leaked a system block — should remain on the legacy "
        "single user-message format until its template is split"
    )
    assert "messages" in kwargs


# ---------------------------------------------------------------------------
# Cache stability — system block must be byte-identical across calls
# ---------------------------------------------------------------------------


def _make_mock_application(**overrides):
    """Build a denial-path-friendly mock application with overridable fields."""
    app = MagicMock()
    app.applicant.first_name = overrides.get("first_name", "Test")
    app.applicant.last_name = overrides.get("last_name", "Applicant")
    app.applicant.username = overrides.get("username", "testuser")
    app.loan_amount = overrides.get("loan_amount", 50000)
    app.credit_score = overrides.get("credit_score", 720)
    app.loan_term_months = overrides.get("loan_term_months", 60)
    app.annual_income = overrides.get("annual_income", 95000)
    app.debt_to_income = overrides.get("debt_to_income", 2.0)
    app.employment_length = overrides.get("employment_length", 5)
    app.purpose = overrides.get("purpose", "personal")
    app.get_purpose_display.return_value = overrides.get("purpose_display", "Personal")
    app.get_employment_type_display.return_value = overrides.get(
        "employment_type_display", "PAYG Permanent"
    )
    app.get_applicant_type_display.return_value = overrides.get(
        "applicant_type_display", "Single"
    )
    app.has_cosigner = overrides.get("has_cosigner", False)
    app.has_hecs = overrides.get("has_hecs", False)
    app.applicant.profile = None
    app.decision = None
    return app


@patch("apps.agents.services.api_budget.ApiBudgetGuard")
@patch("apps.email_engine.services.email_generator.anthropic.Anthropic")
def test_denial_system_block_byte_identical_across_calls(
    mock_anthropic_cls,
    mock_budget_cls,
    captured_api_call,
    monkeypatch,
):
    """Prompt caching only hits if the cached prefix is byte-identical
    across calls. This test makes two denial-path calls with completely
    different applicant data and asserts the ``system`` block text is
    the same both times — while the ``user`` message (where the dynamic
    data lives) differs. A failure here means something is leaking
    per-call state (timestamp, applicant data, env var, app version)
    into the cached block, which silently defeats the cache."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_budget = MagicMock()
    mock_budget.check_budget.return_value = None
    mock_budget_cls.return_value = mock_budget
    mock_anthropic_cls.return_value = MagicMock()

    from apps.email_engine.services.email_generator import EmailGenerator

    gen = EmailGenerator()
    gen._api_available = lambda: True

    # First call — applicant A
    app_a = _make_mock_application(
        first_name="Alice",
        last_name="Anderson",
        loan_amount=50000,
        purpose_display="Personal",
    )
    gen.generate(application=app_a, decision="denied", confidence=0.45)
    first_kwargs = captured_api_call.call_args.kwargs
    first_system_text = first_kwargs["system"][0]["text"]
    first_user_content = first_kwargs["messages"][0]["content"]

    # Second call — applicant B (completely different data)
    captured_api_call.reset_mock()
    app_b = _make_mock_application(
        first_name="Bob",
        last_name="Brown",
        loan_amount=125000,
        purpose_display="Vehicle",
        employment_type_display="Contract",
        applicant_type_display="Joint",
        has_cosigner=True,
        has_hecs=True,
    )
    gen.generate(application=app_b, decision="denied", confidence=0.30)
    second_kwargs = captured_api_call.call_args.kwargs
    second_system_text = second_kwargs["system"][0]["text"]
    second_user_content = second_kwargs["messages"][0]["content"]

    # The whole point of caching: system block IDENTICAL → cache hits
    assert first_system_text == second_system_text, (
        "system block drifted between calls — would defeat prompt caching. "
        "Check for per-call state (timestamps, applicant data, version "
        "stamps) leaking into DENIAL_EMAIL_INSTRUCTIONS."
    )
    # Positive control — confirm the test isn't trivially passing because
    # both calls hit the same fixture. The user messages MUST differ since
    # they carry the per-applicant data.
    assert first_user_content != second_user_content, (
        "user message content was identical for two different applicants — "
        "the dynamic data isn't actually flowing through, so the byte-identical "
        "system check above tells us nothing"
    )
    assert "Alice" in first_user_content
    assert "Bob" in second_user_content
