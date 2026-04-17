# Coverage Phase 2 — P2-1 Marketing Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push `apps.agents.services.marketing_agent` coverage from 11% to 80%+ by adding characterization tests for the six guardrail methods, template fallback, response parsing, offer formatting, and retry-on-guardrail-failure path — lifting project-wide coverage by 5-7 percentage points.

**Architecture:** New test module at `backend/apps/agents/tests/test_marketing_agent.py` + new per-app `backend/apps/agents/tests/conftest.py` providing a `mock_claude_response` fixture. Tests use pure mocks (`unittest.mock.MagicMock`) at the `anthropic` SDK boundary — no live API calls, deterministic, zero cost. Reuses existing `sample_application` fixture from `backend/tests/conftest.py` (no new factories).

**Tech Stack:** pytest, pytest-django, unittest.mock, Django 5.2, anthropic SDK mocking

---

## File Structure

**Create:**
- `backend/apps/agents/tests/conftest.py` — per-app fixture for building mocked Claude responses
- `backend/apps/agents/tests/test_marketing_agent.py` — characterization tests for `MarketingAgent`

**Modify:**
- `.github/workflows/test.yml:79` — bump `--cov-fail-under` after measuring the new baseline

**Read-only reference:**
- `backend/apps/agents/services/marketing_agent.py` — code under test
- `backend/tests/conftest.py` — existing `sample_application` fixture (reused, unchanged)

---

## Prerequisites

Before starting, verify the test environment:

```bash
cd backend
pytest apps/agents/tests/ -v --no-header -q
```

Expected: 1 test file collected (`test_orchestrator_cf_step.py`), plus however many tests it contains. If collection errors, stop and investigate — all tasks below assume a green starting point.

---

### Task 1: Per-app conftest with `mock_claude_response` fixture

**Files:**
- Create: `backend/apps/agents/tests/conftest.py`

- [ ] **Step 1: Write the fixture**

```python
"""Pytest fixtures for apps.agents test modules.

These fixtures are scoped to tests under ``backend/apps/agents/tests/``.
The root ``backend/tests/conftest.py`` provides broader fixtures like
``sample_application`` which these tests also rely on.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_claude_response():
    """Build a MagicMock that quacks like ``anthropic.Anthropic`` message responses.

    Usage::

        def test_foo(mock_claude_response):
            resp = mock_claude_response("Subject: Hi\\n\\nBody text")
            # resp.content[0].text == "Subject: Hi\\n\\nBody text"
    """

    def _build(text: str, *, stop_reason: str = "end_turn"):
        return MagicMock(
            content=[MagicMock(text=text)],
            stop_reason=stop_reason,
        )

    return _build
```

- [ ] **Step 2: Verify fixture is discoverable**

Run: `cd backend && pytest apps/agents/tests/ --collect-only -q 2>&1 | head -20`
Expected: No collection errors. Existing tests still visible.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/conftest.py
git commit -m "test(marketing): add per-app conftest with mock_claude_response fixture"
```

---

### Task 2: `_check_no_decline_language` guardrail tests

**Files:**
- Create (first use): `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Characterization tests for apps.agents.services.marketing_agent.MarketingAgent.

Covers six guardrail methods, template fallback, response parsing, offer formatting,
and the retry-on-guardrail-failure path in ``_generate_with_retries``.

All tests mock at the anthropic SDK boundary — no live API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from apps.agents.services.marketing_agent import MarketingAgent


class TestCheckNoDeclineLanguage:
    """``_check_no_decline_language`` must flag decline references."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_clean_text_passes(self, agent):
        result = agent._check_no_decline_language(
            "Dear Sam, we've put together some options that might suit."
        )
        assert result["check_name"] == "No Decline Language"
        assert result["passed"] is True
        assert result["details"] == "No decline language detected"

    def test_declined_word_fails(self, agent):
        result = agent._check_no_decline_language("Your application was declined.")
        assert result["passed"] is False
        assert "declined" in result["details"]

    @pytest.mark.parametrize(
        "phrase",
        [
            "your application was denied",
            "we rejected your application",
            "the application was unsuccessful",
            "we turned down your request",
            "did not meet our criteria",
            "does not meet our criteria",
            "failed to meet requirements",
            "we are unable to approve this",
            "cannot approve at this time",
            "could not approve the request",
            "Application was not successful",
            "We regret to inform",
        ],
    )
    def test_decline_phrases_fail(self, agent, phrase):
        result = agent._check_no_decline_language(phrase)
        assert result["passed"] is False

    def test_case_insensitive(self, agent):
        result = agent._check_no_decline_language("DECLINED")
        assert result["passed"] is False
```

- [ ] **Step 2: Run tests to verify they fail or pass as expected**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestCheckNoDeclineLanguage -v`
Expected: All tests **PASS** (this is a characterization test — the method already exists and should behave this way). If any test fails, read the failure and either (a) fix the test if it misreads the regex, or (b) flag the real behavior as a finding in the PR description.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _check_no_decline_language"
```

---

### Task 3: `_check_patronising_language` guardrail tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

Add below `TestCheckNoDeclineLanguage`:

```python
class TestCheckPatronisingLanguage:
    """``_check_patronising_language`` blocks condescending phrasing."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_clean_text_passes(self, agent):
        result = agent._check_patronising_language(
            "Here are three product options based on your profile."
        )
        assert result["check_name"] == "Patronising Language"
        assert result["passed"] is True

    @pytest.mark.parametrize(
        "phrase",
        [
            "we know this is hard",
            "we know you're disappointed",
            "don't worry",
            "it's okay",
            "cheer up",
            "keep your chin up",
            "this isn't the end",
            "we understand how you feel",
            "we can imagine how tough this is",
            "unfortunately for you",
            "you've proven yourself",
            "you've demonstrated reliability",
            "you've shown commitment",
            "your track record proves you",
            "you can reliably make payments",
        ],
    )
    def test_patronising_phrases_fail(self, agent, phrase):
        result = agent._check_patronising_language(phrase)
        assert result["passed"] is False
        assert "Patronising language found" in result["details"]

    def test_smart_quote_apostrophe_matched(self, agent):
        # The regex allows either curly (U+2019) or straight apostrophe
        result = agent._check_patronising_language("don\u2019t worry")
        assert result["passed"] is False
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestCheckPatronisingLanguage -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _check_patronising_language"
```

---

### Task 4: `_check_no_false_urgency` guardrail tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

```python
class TestCheckNoFalseUrgency:
    """``_check_no_false_urgency`` blocks pressure language."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_clean_text_passes(self, agent):
        result = agent._check_no_false_urgency(
            "Contact us when you are ready to discuss these options."
        )
        assert result["passed"] is True
        assert result["check_name"] == "False Urgency"

    @pytest.mark.parametrize(
        "phrase",
        [
            "limited time offer",
            "act now to secure this rate",
            "this offer expires soon",
            "don't miss out",
            "rates are rising fast",
            "lock in now before they change",
            "only available to select customers",
            "hurry, supplies are low",
            "last chance to apply",
            "before it's too late",
        ],
    )
    def test_urgency_phrases_fail(self, agent, phrase):
        result = agent._check_no_false_urgency(phrase)
        assert result["passed"] is False
        assert "False urgency language found" in result["details"]
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestCheckNoFalseUrgency -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _check_no_false_urgency"
```

---

### Task 5: `_check_no_guaranteed_approval` guardrail tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

```python
class TestCheckNoGuaranteedApproval:
    """``_check_no_guaranteed_approval`` blocks RG 234-violating guarantees.

    Exception: "guaranteed returns" for term deposits is legitimate
    (Financial Claims Scheme) and must NOT be flagged.
    """

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_clean_text_passes(self, agent):
        result = agent._check_no_guaranteed_approval(
            "Our lending team can assess whether these options suit you."
        )
        assert result["passed"] is True

    def test_guaranteed_returns_on_term_deposit_passes(self, agent):
        # Legitimate for term deposits under Financial Claims Scheme
        result = agent._check_no_guaranteed_approval(
            "Term deposits offer guaranteed returns backed by the government."
        )
        assert result["passed"] is True

    @pytest.mark.parametrize(
        "phrase",
        [
            "guaranteed approval on all products",
            "guaranteed to be approved",
            "100% approval rate",
            "100% chance of qualifying",
            "100% certain you will qualify",
            "you will definitely be approved",
            "you will certainly qualify",
            "pre-approved for this loan",
            "pre approved customer offer",
            "preapproved status",
            "instant approval waiting",
            "automatic approval for existing customers",
            "automatically approved account",
            "no credit check required",
            "no check needed",
            "no questions asked",
        ],
    )
    def test_guarantee_phrases_fail(self, agent, phrase):
        result = agent._check_no_guaranteed_approval(phrase)
        assert result["passed"] is False
        assert "Guaranteed approval language found" in result["details"]
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestCheckNoGuaranteedApproval -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _check_no_guaranteed_approval"
```

---

### Task 6: `_check_marketing_tone` guardrail tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

```python
class TestCheckMarketingTone:
    """``_check_marketing_tone`` flags AI-ish / over-formal phrasing.

    Does NOT flag "comprehensive" or "tailored" — those are legitimate
    in product descriptions for marketing emails.
    """

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_clean_text_passes(self, agent):
        result = agent._check_marketing_tone(
            "Our comprehensive insurance package covers the key risks for your business."
        )
        assert result["passed"] is True
        assert result["check_name"] == "Informal Tone"

    @pytest.mark.parametrize(
        "phrase",
        [
            "we are pleased to confirm this",
            "we are delighted to share these options",
            "we are thrilled to offer",
            "great news about your account",
            "these exciting new products",
            "we are happy to present",
            "navigate your financial journey",
            "leverage these savings",
            "empower your financial future",
            "rest assured these rates are competitive",
            "every step of the way",
            "we understand how important this is",
            "we understand this is disappointing",
            "not the outcome you were hoping for",
            "additionally, consider the savings account",
            "furthermore, the rate is competitive",
            "moreover, the fees are low",
            "in addition, there is no lock-in",
            "may potentially save money",
            "could potentially help",
            "moving forward with your application",
            "going forward we can help",
            "thank you for choosing us",
            "thank you for trusting us",
            "in order to qualify",
        ],
    )
    def test_informal_phrases_fail(self, agent, phrase):
        result = agent._check_marketing_tone(phrase)
        assert result["passed"] is False
        assert "Informal tone phrases detected" in result["details"]
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestCheckMarketingTone -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _check_marketing_tone"
```

---

### Task 7: `_check_marketing_format` + `_check_has_call_to_action` tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test classes**

```python
class TestCheckMarketingFormat:
    """``_check_marketing_format`` enforces plain-text-with-bullets format.

    Blocks markdown bold/headers, HTML tags, and em dashes.
    Allows Unicode bullets (U+2022), en dashes (U+2013), box-drawing, arrows.
    """

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_clean_plain_text_passes(self, agent):
        result = agent._check_marketing_format(
            "Option 1: Savings Account\n\n\u2022  Benefit: competitive rate"
        )
        assert result["passed"] is True
        assert result["check_name"] == "Plain Text Format"

    def test_en_dash_passes(self, agent):
        # U+2013 is allowed; U+2014 (em dash) is not
        result = agent._check_marketing_format("Mon\u2013Fri 8:30am \u2013 5:30pm AEST")
        assert result["passed"] is True

    def test_bold_markdown_fails(self, agent):
        result = agent._check_marketing_format("This is **bold** text.")
        assert result["passed"] is False
        assert "bold markdown" in result["details"]

    def test_markdown_header_fails(self, agent):
        result = agent._check_marketing_format("# Heading\n\nBody text.")
        assert result["passed"] is False
        assert "markdown headers" in result["details"]

    def test_html_tag_fails(self, agent):
        result = agent._check_marketing_format("Click <a href='x'>here</a>.")
        assert result["passed"] is False
        assert "HTML tags" in result["details"]

    def test_em_dash_fails(self, agent):
        result = agent._check_marketing_format("Mon\u2014Fri 9am\u20145pm")
        assert result["passed"] is False
        assert "em dashes" in result["details"]

    def test_multiple_issues_all_reported(self, agent):
        result = agent._check_marketing_format(
            "# Header\nThis is **bold** with <tag>html</tag> and \u2014 em dash"
        )
        assert result["passed"] is False
        details = result["details"]
        assert "bold markdown" in details
        assert "markdown headers" in details
        assert "HTML tags" in details
        assert "em dashes" in details


class TestCheckHasCallToAction:
    """``_check_has_call_to_action`` requires a contact pathway."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_phone_cta_passes(self, agent):
        result = agent._check_has_call_to_action("Give us a call to discuss options.")
        assert result["passed"] is True
        assert result["check_name"] == "Call to Action"

    def test_branch_cta_passes(self, agent):
        result = agent._check_has_call_to_action("Visit your nearest branch to chat.")
        assert result["passed"] is True

    def test_reply_cta_passes(self, agent):
        result = agent._check_has_call_to_action("Reply to this email when you're ready.")
        assert result["passed"] is True

    def test_phone_number_passes(self, agent):
        result = agent._check_has_call_to_action("You can reach us on 1300 000 000 any weekday.")
        assert result["passed"] is True

    def test_email_address_passes(self, agent):
        result = agent._check_has_call_to_action(
            "Contact us at aussieloanai@gmail.com for more info."
        )
        assert result["passed"] is True

    def test_signer_role_passes(self, agent):
        result = agent._check_has_call_to_action("Signed by Sarah Mitchell, Senior Lending Officer.")
        assert result["passed"] is True

    def test_no_cta_fails(self, agent):
        result = agent._check_has_call_to_action(
            "These are the products. Goodbye."
        )
        assert result["passed"] is False
        assert "Missing call to action" in result["details"]
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestCheckMarketingFormat apps/agents/tests/test_marketing_agent.py::TestCheckHasCallToAction -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _check_marketing_format and _check_has_call_to_action"
```

---

### Task 8: `_parse_response` + `_format_offers` tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test classes**

```python
class TestParseResponse:
    """``_parse_response`` splits Claude output into (subject, body)."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_explicit_subject_line(self, agent):
        subject, body = agent._parse_response(
            "Subject: Your new options\n\nDear Sam,\nBody here."
        )
        assert subject == "Your new options"
        assert body == "Dear Sam,\nBody here."

    def test_case_insensitive_subject_prefix(self, agent):
        subject, body = agent._parse_response(
            "subject: Lowercase\n\nBody."
        )
        assert subject == "Lowercase"

    def test_missing_subject_uses_default(self, agent):
        subject, body = agent._parse_response("Dear Sam,\nNo subject line.")
        assert subject == "Next steps for your AussieLoanAI loan application"
        assert body == "Dear Sam,\nNo subject line."

    def test_multiple_blank_lines_after_subject_stripped(self, agent):
        subject, body = agent._parse_response(
            "Subject: Hi\n\n\n\nActual body"
        )
        assert body == "Actual body"

    def test_whitespace_trimmed(self, agent):
        subject, body = agent._parse_response(
            "   Subject: Padded   \n\n  Body text  \n"
        )
        assert subject == "Padded"
        assert body == "Body text"


class TestFormatOffers:
    """``_format_offers`` renders NBO offers as prompt-ready text."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    def test_empty_offers_returns_placeholder(self, agent):
        assert agent._format_offers([]) == "No specific offers generated."

    def test_minimal_offer(self, agent):
        offers = [{"type": "savings"}]
        result = agent._format_offers(offers)
        assert result.startswith("Offer 1: savings")

    def test_offer_uses_name_over_type(self, agent):
        offers = [{"type": "td", "name": "Term Deposit"}]
        result = agent._format_offers(offers)
        assert "Offer 1: Term Deposit" in result
        assert "Offer 1: td" not in result

    def test_full_offer_renders_all_fields(self, agent):
        offers = [
            {
                "name": "Secured Loan",
                "amount": 15000.0,
                "term_months": 36,
                "estimated_rate": 7.5,
                "benefit": "Lower rate than unsecured",
                "reasoning": "Customer has property equity",
            }
        ]
        result = agent._format_offers(offers)
        assert "Offer 1: Secured Loan" in result
        assert "Amount: $15,000.00" in result
        assert "Term: 36 months" in result
        assert "Est. Rate: 7.5%" in result
        assert "Benefit: Lower rate than unsecured" in result
        assert "Why this suits them: Customer has property equity" in result

    def test_multiple_offers_numbered_separated(self, agent):
        offers = [
            {"name": "First", "amount": 1000},
            {"name": "Second", "amount": 2000},
        ]
        result = agent._format_offers(offers)
        assert "Offer 1: First" in result
        assert "Offer 2: Second" in result
        # Blocks separated by blank line
        assert "\n\n" in result
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestParseResponse apps/agents/tests/test_marketing_agent.py::TestFormatOffers -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _parse_response and _format_offers"
```

---

### Task 9: `_marketing_template_fallback` tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

```python
class TestMarketingTemplateFallback:
    """``_marketing_template_fallback`` returns a valid email dict when Claude is unavailable."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return MarketingAgent()

    @pytest.mark.django_db
    def test_with_offers_builds_option_blocks(self, agent, sample_application):
        nbo_result = {
            "offers": [
                {
                    "type": "secured_loan",
                    "name": "Secured Personal Loan",
                    "amount": 15000,
                    "estimated_rate": 8.5,
                    "term_months": 36,
                    "monthly_repayment": 475.00,
                    "benefit": "Lower rate because secured by property",
                    "reasoning": "You have property equity available",
                }
            ]
        }
        result = agent._marketing_template_fallback(
            sample_application, nbo_amounts=[15000.0, 475.0], start_time=0.0, nbo_result=nbo_result
        )
        assert result["template_fallback"] is True
        assert result["prompt_used"] == "[TEMPLATE FALLBACK \u2014 Claude API unavailable]"
        assert result["attempt_number"] == 1
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert "Option 1: Secured Personal Loan" in result["body"]
        assert "Amount: $15,000.00" in result["body"]
        assert "Rate: 8.50% p.a." in result["body"]
        assert "Term: 36 months" in result["body"]
        assert "Estimated repayment: $475.00/month" in result["body"]
        assert result["subject"] == "Next steps for your AussieLoanAI loan application"

    @pytest.mark.django_db
    def test_no_offers_uses_generic_body(self, agent, sample_application):
        result = agent._marketing_template_fallback(
            sample_application, nbo_amounts=[], start_time=0.0, nbo_result={"offers": []}
        )
        assert result["template_fallback"] is True
        assert result["subject"] == "Next Steps for Your Banking Needs"
        assert "1300 000 000" in result["body"]

    @pytest.mark.django_db
    def test_term_deposit_adds_financial_claims_scheme_footer(self, agent, sample_application):
        nbo_result = {
            "offers": [
                {"type": "term_deposit", "name": "12-Month Term Deposit", "amount": 10000}
            ]
        }
        result = agent._marketing_template_fallback(
            sample_application, nbo_amounts=[10000.0], start_time=0.0, nbo_result=nbo_result
        )
        assert "Financial Claims Scheme" in result["body"]

    @pytest.mark.django_db
    def test_nbo_result_none_treated_as_empty(self, agent, sample_application):
        result = agent._marketing_template_fallback(
            sample_application, nbo_amounts=[], start_time=0.0, nbo_result=None
        )
        assert result["template_fallback"] is True
        assert result["subject"] == "Next Steps for Your Banking Needs"

    @pytest.mark.django_db
    def test_fortnightly_repayment_rendered(self, agent, sample_application):
        nbo_result = {
            "offers": [
                {
                    "name": "Savings Account",
                    "amount": 5000,
                    "fortnightly_repayment": 120.50,
                }
            ]
        }
        result = agent._marketing_template_fallback(
            sample_application, nbo_amounts=[5000.0, 120.5], start_time=0.0, nbo_result=nbo_result
        )
        assert "Estimated repayment: $120.50/fortnight" in result["body"]

    @pytest.mark.django_db
    def test_guardrails_are_run_and_results_attached(self, agent, sample_application):
        nbo_result = {"offers": [{"name": "Prod", "amount": 1000}]}
        result = agent._marketing_template_fallback(
            sample_application, nbo_amounts=[1000.0], start_time=0.0, nbo_result=nbo_result
        )
        assert "guardrail_results" in result
        assert isinstance(result["guardrail_results"], list)
        assert "passed_guardrails" in result
        assert "quality_score" in result
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestMarketingTemplateFallback -v`
Expected: All PASS. If guardrails in the template body actually fail (e.g. unknown format issue), read the details from one run and adjust the template test expectations — but the template is production code generating emails that are supposed to pass, so failures should be investigated not suppressed.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _marketing_template_fallback"
```

---

### Task 10: `_generate_with_retries` — retry on guardrail failure

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

The strategy here: mock `guarded_api_call` to return a sequence of crafted MagicMock responses; the first response triggers a guardrail failure (e.g. contains "declined"), the second is clean. Assert `attempt_number == 2` and that `guarded_api_call` was called twice.

```python
class TestGenerateWithRetries:
    """``_generate_with_retries`` retries on guardrail failure up to MAX_RETRIES."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            a = MarketingAgent()
            a.client = MagicMock()  # never called directly — guarded_api_call is patched
            return a

    @pytest.mark.django_db
    def test_first_attempt_clean_returns_attempt_1(
        self, agent, sample_application, mock_claude_response
    ):
        clean_body = (
            "Subject: Your options\n\n"
            "Dear Test,\n\n"
            "Option 1: Savings\n\n"
            "\u2022  Competitive rate: 4.5% p.a. variable.\n\n"
            "Give us a call on 1300 000 000 to discuss.\n\n"
            "Kind regards,\nSarah Mitchell\nSenior Lending Officer"
        )
        with patch(
            "apps.agents.services.marketing_agent.guarded_api_call",
            return_value=mock_claude_response(clean_body),
        ) as mock_call:
            result = agent._generate_with_retries(
                sample_application,
                prompt="test prompt",
                start_time=0.0,
                nbo_amounts=[],
                nbo_result={"offers": []},
            )
        assert result["attempt_number"] == 1
        assert mock_call.call_count == 1
        assert result["subject"] == "Your options"

    @pytest.mark.django_db
    def test_retries_on_guardrail_failure(
        self, agent, sample_application, mock_claude_response
    ):
        # First attempt contains "declined" -> fails No Decline Language guardrail.
        # Second attempt is clean.
        bad_body = (
            "Subject: Declined\n\n"
            "Your application was declined but here are options. "
            "Call 1300 000 000."
        )
        clean_body = (
            "Subject: Options\n\n"
            "Dear Test,\n\n"
            "Option 1: Savings\n\n"
            "\u2022  Competitive rate.\n\n"
            "Give us a call on 1300 000 000."
        )
        with patch(
            "apps.agents.services.marketing_agent.guarded_api_call",
            side_effect=[
                mock_claude_response(bad_body),
                mock_claude_response(clean_body),
            ],
        ) as mock_call:
            result = agent._generate_with_retries(
                sample_application,
                prompt="test prompt",
                start_time=0.0,
                nbo_amounts=[],
                nbo_result={"offers": []},
            )
        assert mock_call.call_count == 2
        assert result["attempt_number"] == 2

    @pytest.mark.django_db
    def test_budget_exhausted_falls_back_to_template(
        self, agent, sample_application
    ):
        from apps.agents.services.api_budget import BudgetExhausted

        with patch(
            "apps.agents.services.marketing_agent.guarded_api_call",
            side_effect=BudgetExhausted("daily cap hit"),
        ):
            result = agent._generate_with_retries(
                sample_application,
                prompt="test prompt",
                start_time=0.0,
                nbo_amounts=[],
                nbo_result={"offers": [{"name": "Prod", "amount": 1000}]},
            )
        assert result["template_fallback"] is True
        assert result["prompt_used"] == "[TEMPLATE FALLBACK \u2014 Claude API unavailable]"
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestGenerateWithRetries -v`
Expected: All PASS.

If `test_retries_on_guardrail_failure` shows `attempt_number == 3` instead of 2, inspect: either (a) the "clean" body in fixture #2 still trips a different guardrail — adjust until it passes the full suite, or (b) there's a bug worth flagging in the PR description.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize _generate_with_retries retry path"
```

---

### Task 11: `generate` entry point — smoke tests

**Files:**
- Modify: `backend/apps/agents/tests/test_marketing_agent.py`

- [ ] **Step 1: Append the test class**

```python
class TestGenerate:
    """``generate`` is the public entry point — wires everything together."""

    @pytest.fixture
    def agent(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            a = MarketingAgent()
            a.client = MagicMock()
            return a

    @pytest.mark.django_db
    def test_happy_path_returns_email_dict(
        self, agent, sample_application, mock_claude_response
    ):
        clean_body = (
            "Subject: Your options\n\n"
            "Dear Customer,\n\n"
            "Option 1: Savings Account\n\n"
            "\u2022  Competitive interest rate.\n\n"
            "Give us a call on 1300 000 000."
        )
        nbo_result = {
            "offers": [
                {
                    "type": "savings",
                    "name": "Savings Account",
                    "amount": 5000.0,
                    "estimated_rate": 4.5,
                }
            ],
            "customer_retention_score": 75,
            "loyalty_factors": ["tenure"],
            "analysis": "Customer has strong banking relationship.",
        }
        with patch(
            "apps.agents.services.marketing_agent.guarded_api_call",
            return_value=mock_claude_response(clean_body),
        ):
            result = agent.generate(
                sample_application, nbo_result, denial_reasons="Insufficient income"
            )
        assert "subject" in result
        assert "body" in result
        assert "passed_guardrails" in result
        assert "guardrail_results" in result
        assert result["attempt_number"] == 1

    @pytest.mark.django_db
    def test_applicant_without_profile_handled(
        self, agent, application_no_profile, mock_claude_response
    ):
        # application_no_profile has no CustomerProfile — code should not crash
        clean_body = (
            "Subject: Options\n\n"
            "Dear Customer,\n\n"
            "Reply to this email to chat about alternatives."
        )
        with patch(
            "apps.agents.services.marketing_agent.guarded_api_call",
            return_value=mock_claude_response(clean_body),
        ):
            result = agent.generate(
                application_no_profile, {"offers": []}, denial_reasons=""
            )
        assert "subject" in result
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py::TestGenerate -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add backend/apps/agents/tests/test_marketing_agent.py
git commit -m "test(marketing): characterize generate entry point"
```

---

### Task 12: Measure total coverage and bump CI gate

**Files:**
- Modify: `.github/workflows/test.yml:79`

- [ ] **Step 1: Measure marketing_agent coverage**

Run: `cd backend && pytest apps/agents/tests/test_marketing_agent.py --cov=apps.agents.services.marketing_agent --cov-report=term-missing -q 2>&1 | tail -20`

Expected output: a coverage percentage for `apps/agents/services/marketing_agent.py`. Target is 80%+. Note the exact percentage — include in the PR description.

- [ ] **Step 2: Measure project-wide coverage**

Run: `cd backend && pytest --cov=apps --cov-report=term -q 2>&1 | tail -5`

Expected: "TOTAL" line at the bottom with a percentage. Record the integer floor. Examples:
- If it says 68.42% → new gate is `67`
- If it says 69.95% → new gate is `69`
- Formula: `floor(measured) - 0.5` rounded down to an integer (i.e. subtract ~0.5 then floor). Practically: **pick the next integer below the measured value** so normal flakiness doesn't break CI.

- [ ] **Step 3: Update CI gate**

Edit `.github/workflows/test.yml` line 79 — change `--cov-fail-under=63` to the new integer. Example (replace `68` with your measured floor):

```yaml
        run: pytest -v --tb=short --cov=apps --cov-report=term-missing --cov-fail-under=68
```

- [ ] **Step 4: Verify gate still passes locally**

Run: `cd backend && pytest --cov=apps --cov-fail-under=<NEW_GATE> -q 2>&1 | tail -5`
Expected: exit code 0, "Required test coverage of <NEW_GATE>% reached".

- [ ] **Step 5: Commit**

```bash
cd /c/Users/Admin/loan-approval-ai-system
git add .github/workflows/test.yml
git commit -m "ci(coverage): bump --cov-fail-under to <NEW_GATE> after marketing_agent tests

Measured coverage: <MEASURED>% total, <MARKETING_PCT>% on marketing_agent
(was 11%). Gate set one integer below measured to tolerate flakiness."
```

---

### Task 13: Open pull request

**Files:** (no file changes)

- [ ] **Step 1: Push branch**

Decide the branch name — suggest `test/coverage-phase-2-marketing-agent`. If you haven't already branched:

```bash
cd /c/Users/Admin/loan-approval-ai-system
git checkout -b test/coverage-phase-2-marketing-agent
git push -u origin test/coverage-phase-2-marketing-agent
```

If you *were* already on a feature branch, just push:

```bash
git push -u origin HEAD
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "test(marketing_agent): characterization suite + coverage gate bump (P2-1)" --body "$(cat <<'EOF'
## Summary

Coverage phase 2, first of three atomic PRs tracked in `docs/superpowers/specs/2026-04-17-coverage-phase-2-design.md`.

Adds characterization tests for `apps.agents.services.marketing_agent.MarketingAgent`:
- Six guardrail methods (`_check_no_decline_language`, `_check_patronising_language`, `_check_no_false_urgency`, `_check_no_guaranteed_approval`, `_check_marketing_tone`, `_check_marketing_format`, `_check_has_call_to_action`)
- `_parse_response`, `_format_offers`
- `_marketing_template_fallback` (including term deposit FCS footer branch)
- `_generate_with_retries` retry-on-guardrail-failure path + `BudgetExhausted` fallback
- `generate` public entry point

All tests mock at the `anthropic` SDK boundary — deterministic, zero cost.

## Coverage movement

- `apps/agents/services/marketing_agent.py`: 11% → **<MEASURED_PCT>%**
- Project-wide: 63.98% → **<NEW_TOTAL>%**
- CI `--cov-fail-under` bumped `63` → **<NEW_GATE>** (floor(measured) - 0.5 pattern)

## Test plan

- [ ] `pytest apps/agents/tests/test_marketing_agent.py -v` all green
- [ ] `pytest --cov=apps --cov-fail-under=<NEW_GATE>` passes
- [ ] CI green on all required checks

## Follow-ups

- P2-2: `counterfactual_engine` (11%) — plan TBD after this lands
- P2-3: `next_best_offer` (13%) — plan TBD after P2-2 lands

\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Fill in the `<MEASURED_PCT>`, `<NEW_TOTAL>`, `<NEW_GATE>` placeholders using the actual numbers from Task 12. Do not leave placeholders in the PR body.

- [ ] **Step 3: Report the PR URL back**

Capture the URL returned by `gh pr create` — paste into the final status message.

---

## Self-Review

After the plan is in place, verify:

1. **Spec coverage** — every component listed in `docs/superpowers/specs/2026-04-17-coverage-phase-2-design.md` for the marketing agent is covered: ✅ six guardrail methods, ✅ template fallback, ✅ parse/format helpers, ✅ retry logic, ✅ gate bump, ✅ PR.
2. **No placeholders** — no TBDs in the code blocks. `<MEASURED_PCT>`/`<NEW_TOTAL>`/`<NEW_GATE>` in Task 12/13 are explicit measure-then-fill placeholders (not forgotten work) — the engineer must run the command and substitute.
3. **Type consistency** — every test uses `MarketingAgent()` (the actual class name); every fixture import path is real (`apps.agents.services.marketing_agent`, `apps.agents.services.api_budget`).
4. **No factory references** — the original design spec mentioned a non-existent `LoanApplicationFactory`; this plan uses the real `sample_application` / `application_no_profile` fixtures from `backend/tests/conftest.py` (already visible to these tests through pytest's conftest inheritance).

---

## Scope

This plan covers **P2-1 only** (marketing_agent). P2-2 (counterfactual_engine) and P2-3 (next_best_offer) will get their own plans after P2-1 lands with measured CI coverage — so each subsequent plan can set its starting gate accurately.
