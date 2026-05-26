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


def test_denial_instructions_meets_sonnet_cache_minimum():
    """Anthropic prompt caching needs ≥1024 tokens for Sonnet to
    actually cache; below that the cache_control directive is a no-op.
    Rough char heuristic: 4 chars/token for English. We check 4096 chars
    as a conservative floor (1024 tokens). The real template is ~17k
    chars; this guards against future shrinking that would silently
    disable caching."""
    from apps.email_engine.services.prompts import DENIAL_EMAIL_INSTRUCTIONS

    assert len(DENIAL_EMAIL_INSTRUCTIONS) >= 4096, (
        f"DENIAL_EMAIL_INSTRUCTIONS is {len(DENIAL_EMAIL_INSTRUCTIONS)} chars "
        f"(~{len(DENIAL_EMAIL_INSTRUCTIONS) // 4} tokens) — below the Sonnet "
        "cache-eligibility minimum of ~1024 tokens. Cache_control will be a no-op."
    )


def test_denial_instructions_has_no_format_placeholders():
    """The instructions block becomes the cached system prompt. If it
    contains ``{}`` placeholders, ``.format()`` calls in callers
    accidentally hitting the wrong constant would either KeyError or
    silently substitute, and the cache key would shift per call.
    The dynamic data lives in DENIAL_DATA_TEMPLATE instead."""
    from apps.email_engine.services.prompts import DENIAL_EMAIL_INSTRUCTIONS

    # No bare {placeholder} patterns. We allow {{ }} literal braces
    # (none present today, but defensive in case future edits add them).
    import re

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
