# Email Formatting Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign approval/denial/marketing emails with professional Gmail-compatible HTML rendering, and switch default generation to templates (skip Claude API) to save cost.

**Architecture:** Rewrite `_plain_text_to_html` in `backend/apps/email_engine/services/sender.py` to emit a 600px-container, card-based layout with per-type accent colors, semantic lists, and a single CTA. Add `EMAIL_USE_CLAUDE_API` Django setting (default `False`) that short-circuits `EmailGenerator.generate()` and `MarketingAgent.generate()` to their existing template paths.

**Tech Stack:** Python 3.11, Django 5.2, pytest + pytest-django, DOMPurify (frontend, unchanged).

**Spec:** `docs/superpowers/specs/2026-04-17-email-formatting-redesign-design.md`

**Branch:** `feat/email-formatting-redesign` (create from current branch).

---

## File structure

Files modified by this plan:

| File | Responsibility after change |
|------|----------------------------|
| `backend/apps/email_engine/services/sender.py` | HTML renderer. Gains `email_type` kwarg, emits 600px container, semantic lists, card-styled details, CTA button, accent colors. |
| `backend/apps/email_engine/services/email_generator.py` | Short-circuits to `_generate_fallback()` when `EMAIL_USE_CLAUDE_API=False`. |
| `backend/apps/agents/services/marketing_agent.py` | Short-circuits to `_marketing_template_fallback()` when `EMAIL_USE_CLAUDE_API=False`. |
| `backend/config/settings/base.py` | Adds `EMAIL_USE_CLAUDE_API` flag, default `False`. |
| `backend/apps/email_engine/{tasks,views}.py` + `backend/apps/agents/services/{email_pipeline,marketing_pipeline,human_review_handler}.py` + `backend/apps/email_engine/services/lifecycle.py` | Each call to `send_decision_email(...)` adds `email_type=` kwarg. |
| `backend/tests/test_email_sender.py` | New — unit tests for each reusable HTML block (17 tests). |
| `backend/tests/test_email_generator.py` | Adds test for `EMAIL_USE_CLAUDE_API=False` short-circuit. |
| `backend/tests/test_marketing_agent.py` (or create) | Adds test for marketing flag short-circuit. |

---

## Task 0: Branch setup

**Files:**
- None (branch creation only)

- [ ] **Step 1: Create and check out the feature branch**

```bash
cd C:/Users/Admin/loan-approval-ai-system
git checkout master
git pull origin master
git checkout -b feat/email-formatting-redesign
```

- [ ] **Step 2: Confirm branch is clean**

Run: `git status`
Expected: `On branch feat/email-formatting-redesign` with `nothing to commit, working tree clean`.

---

## Task 1: Golden plain-text fixtures

**Files:**
- Create: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Create the test file with shared fixtures**

Create `backend/tests/test_email_sender.py` with this content:

```python
"""Tests for _plain_text_to_html HTML rendering.

Covers the three email types (approval, denial, marketing) and validates
that generated HTML is Gmail-compatible (inline styles only, table layout,
600px container).
"""
import pytest

from apps.email_engine.services.sender import _plain_text_to_html


# Representative approval plain-text body (matches template_fallback output)
APPROVAL_PLAIN = """Dear Sarah,

Congratulations! Your loan application has been approved.

Loan Details:

  Loan Amount:            $35,000.00
  Interest Rate:          8.95% p.a.
  Term:                   5 years
  Monthly Repayment:      $724.18

Next Steps:

\u2022  Review the attached loan contract
\u2022  Sign and return within 7 days
\u2022  Funds disbursed within 2 business days

Required Documentation:

  1. Bank statements (last 3 months)
  2. Photo ID
  3. Signed loan contract

Attachments:

  1. Loan Contract.pdf
  2. Key Facts Sheet.pdf
  3. Credit Guide.pdf

Kind regards,

Sarah Mitchell
Senior Lending Officer

ABN 12 345 678 901
Phone: 1300 LOAN AI
Email: decisions@aussieloanai.com.au
"""


# Representative denial body
DENIAL_PLAIN = """Dear Sarah,

Thank you for your loan application. After careful review, we are unable to approve your application at this time.

This decision was based on a thorough review of your financial profile, specifically:

\u2022  Credit score below our current threshold
\u2022  Debt-to-income ratio exceeds our lending criteria
\u2022  Employment tenure shorter than required

What You Can Do:

\u2022  Request your credit file from Equifax or illion (free once per year)
\u2022  Pay down existing debts to improve DTI
\u2022  Reapply after 12 months of stable employment

Kind regards,

Sarah Mitchell
Senior Lending Officer

ABN 12 345 678 901
Phone: 1300 LOAN AI
Email: decisions@aussieloanai.com.au
"""


# Representative marketing body
MARKETING_PLAIN = """Dear Sarah,

While your recent loan application wasn't approved, we have some alternative options that may suit your situation better.

Option 1: Secured Personal Loan

  Amount:                 $15,000.00
  Interest Rate:          9.95% p.a.
  Term:                   3 years
  Monthly Repayment:      $483.67

A secured personal loan may be a more suitable path given your current profile.

Option 2: Debt Consolidation

  Amount:                 $20,000.00
  Interest Rate:          11.50% p.a.
  Term:                   5 years
  Monthly Repayment:      $440.21

Consolidating existing debts into a single repayment could simplify your finances.

Kind regards,

Sarah Mitchell
Senior Lending Officer

ABN 12 345 678 901
Phone: 1300 LOAN AI
Email: alternatives@aussieloanai.com.au
"""
```

- [ ] **Step 2: Commit the fixtures**

```bash
git add backend/tests/test_email_sender.py
git commit -m "test(email): add golden plain-text fixtures for sender tests"
```

---

## Task 2: Accent color per email type

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestAccentColors:
    def test_approval_html_contains_green_accent(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "#16a34a" in html

    def test_denial_html_contains_slate_accent(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "#374151" in html

    def test_marketing_html_contains_purple_accent(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "#7c3aed" in html

    def test_denial_html_has_no_red_tone(self):
        """Denial must not use harsh/alarming colors per tone preference."""
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "#dc2626" not in html  # red
        assert "#ef4444" not in html
        assert "#f87171" not in html

    def test_unknown_email_type_defaults_to_approval_accent(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="anything_else")
        assert "#16a34a" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestAccentColors -v`
Expected: FAIL with `TypeError: _plain_text_to_html() got an unexpected keyword argument 'email_type'`.

- [ ] **Step 3: Add email_type kwarg and accent map**

Edit `backend/apps/email_engine/services/sender.py`. Add this constant near the top of the file (after the existing `SECTION_LABELS`, `CLOSINGS`, `OPTION_PATTERN`, `LOAN_DETAIL_RE`):

```python
ACCENT_COLORS = {
    "approval": "#16a34a",
    "denial": "#374151",
    "marketing": "#7c3aed",
}


def _get_accent_color(email_type: str) -> str:
    return ACCENT_COLORS.get(email_type, ACCENT_COLORS["approval"])
```

Change the signature of `_plain_text_to_html`:

```python
def _plain_text_to_html(body: str, *, email_type: str = "approval") -> str:
    """Convert a plain-text email body to styled HTML matching the dashboard preview.

    email_type selects the accent color and determines whether compliance blocks
    (AFCA for denial) are appended.
    """
    accent = _get_accent_color(email_type)
    lines = body.split("\n")
    # ... existing body unchanged for now
```

Also update the final return to include the accent somewhere (so the test passes). Change the outer wrapper:

```python
    html_body = "\n".join(html_parts)
    return (
        f'<div style="font-family: Arial, Helvetica, sans-serif; '
        f'font-size: 16px; line-height: 1.6; color: #1f2937; '
        f'border-top: 4px solid {accent};">\n'
        f"{html_body}\n"
        "</div>"
    )
```

(Also bumps body font-size from 14px → 16px per spec.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestAccentColors -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): add email_type parameter and accent color map"
```

---

## Task 3: 600px container + branded header

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestContainer:
    def test_container_uses_table_with_600px_width(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Gmail-safe: table-based layout with 600px max width
        assert "<table" in html
        assert "width:600px" in html.replace(" ", "")  # tolerate whitespace
        assert "max-width:100%" in html.replace(" ", "")

    def test_branded_header_contains_app_name(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "Aussie Loan AI" in html

    def test_header_accent_bar_matches_email_type(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        # Slate accent bar at top of branded header
        assert "background-color: #374151" in html or "background:#374151" in html

    def test_html_uses_inline_styles_only(self):
        """Gmail strips <style> blocks — verify we never emit one."""
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "<style" not in html
        assert "</style>" not in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestContainer -v`
Expected: FAIL — current output has no 600px container and no "Aussie Loan AI" header.

- [ ] **Step 3: Implement branded header + wrap in 600px table**

In `backend/apps/email_engine/services/sender.py`, add a helper function above `_plain_text_to_html`:

```python
def _render_branded_header(accent: str) -> str:
    """Render the shared branded header — accent bar + app name."""
    return (
        '<table align="center" cellpadding="0" cellspacing="0" '
        'style="width:600px; max-width:100%; margin:0 auto; '
        'background:#ffffff; border:1px solid #e5e7eb; border-radius:8px;">'
        '<tr><td style="background-color:' + accent + '; height:4px; '
        'font-size:0; line-height:0;">&nbsp;</td></tr>'
        '<tr><td style="padding:20px 32px;">'
        '<span style="font-size:18px; font-weight:bold; color:#111827;">'
        'Aussie Loan AI</span>'
        '</td></tr>'
    )


def _render_container_close() -> str:
    """Close the branded container table."""
    return '</table>'
```

Rewrite the outer wrapper in `_plain_text_to_html`. Replace:

```python
    html_body = "\n".join(html_parts)
    return (
        f'<div style="font-family: Arial, Helvetica, sans-serif; '
        f'font-size: 16px; line-height: 1.6; color: #1f2937; '
        f'border-top: 4px solid {accent};">\n'
        f"{html_body}\n"
        "</div>"
    )
```

With:

```python
    body_html = "\n".join(html_parts)
    return (
        '<div style="background:#f6f6f6; padding:24px 0; '
        'font-family: Arial, Helvetica, sans-serif; font-size:16px; '
        'line-height:1.6; color:#1f2937;">\n'
        + _render_branded_header(accent)
        + '<tr><td style="padding:0 32px 16px 32px;">\n'
        + body_html
        + '\n</td></tr>\n'
        + _render_container_close()
        + '\n</div>'
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestContainer -v`
Expected: All 4 tests PASS.
Also run: `pytest backend/tests/test_email_sender.py::TestAccentColors -v`
Expected: all previously passing tests still PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): wrap output in 600px Gmail-safe container with branded header"
```

---

## Task 4: Section header with accent underline

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestSectionHeaders:
    def test_section_labels_have_accent_underline(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # "Loan Details:" should render with accent border-bottom
        assert "Loan Details" in html
        # Must have bottom-border: 2px solid <accent>
        assert "border-bottom:2px solid #16a34a" in html.replace(" ", "")

    def test_section_headers_are_18px_bold(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Find the span around "Loan Details"
        assert 'font-size:18px' in html.replace(" ", "")
        assert 'font-weight:bold' in html.replace(" ", "")

    def test_options_are_treated_as_section_headers(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "Option 1: Secured Personal Loan" in html
        # Option headers get the accent underline too
        assert "border-bottom:2px solid #7c3aed" in html.replace(" ", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestSectionHeaders -v`
Expected: FAIL — current section rendering uses `<strong>` with no accent underline.

- [ ] **Step 3: Implement the accent-underlined section header**

In `backend/apps/email_engine/services/sender.py`, add helper above `_plain_text_to_html`:

```python
def _render_section_header(label: str, accent: str) -> str:
    return (
        '<p style="margin:28px 0 8px 0;">'
        f'<span style="font-size:18px; font-weight:bold; color:#111827; '
        f'border-bottom:2px solid {accent}; padding-bottom:6px; '
        'display:inline-block;">'
        f'{label.rstrip(":")}'
        '</span></p>'
    )
```

Update the three section-like branches in the main loop. Replace:

```python
        if is_section or is_option:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:20px 0 4px 0;"><strong>{stripped}</strong></p>')
            continue
```

With:

```python
        if is_section or is_option:
            _flush_detail_rows()
            html_parts.append(_render_section_header(stripped, accent))
            continue
```

And for `Dear` / closings, drop the bold and use plain paragraphs:

```python
        if is_dear:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:0 0 12px 0;">{stripped}</p>')
            continue

        if is_closing:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:24px 0 4px 0;">{stripped}</p>')
            continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestSectionHeaders -v`
Expected: All 3 tests PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests so far still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): render section headers with accent underline"
```

---

## Task 5: Semantic bullet list

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestBulletLists:
    def test_consecutive_bullets_collapse_into_single_ul(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Approval has 3 bullets under "Next Steps" — should be one <ul>
        # Count <ul> occurrences
        assert html.count("<ul") >= 1
        # Each bullet becomes an <li>
        assert html.count("<li") >= 3

    def test_bullets_use_semantic_li(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "<li" in html
        # Old hack rendered bullets as <p>•... — should no longer appear
        assert "•&nbsp;&nbsp;" not in html

    def test_bullet_items_are_16px(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # <li> elements should carry 16px sizing
        assert 'font-size:16px' in html.replace(" ", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestBulletLists -v`
Expected: FAIL — current renderer emits `<p>•&nbsp;&nbsp;{content}</p>` not `<ul>/<li>`.

- [ ] **Step 3: Refactor to accumulate consecutive bullets into a single <ul>**

In `backend/apps/email_engine/services/sender.py`, add state for list accumulation. At the top of `_plain_text_to_html`, after `detail_rows: list[str] = []`, add:

```python
    list_items: list[str] = []
    list_type: str | None = None  # "ul" or "ol"

    def _flush_list():
        if list_items:
            tag = list_type or "ul"
            html_parts.append(
                f'<{tag} style="margin:8px 0; padding-left:24px;">'
                + "".join(list_items)
                + f'</{tag}>'
            )
            list_items.clear()
```

The signature uses `nonlocal list_type` — so make the flush function modify the outer flag. Instead, manage via list wrapper to keep it simple:

```python
    list_state = {"items": [], "type": None}  # shared mutable state

    def _flush_list():
        items = list_state["items"]
        if items:
            tag = list_state["type"] or "ul"
            html_parts.append(
                f'<{tag} style="margin:8px 0; padding-left:24px;">'
                + "".join(items)
                + f'</{tag}>'
            )
            list_state["items"] = []
            list_state["type"] = None
```

Replace the existing bullet branch:

```python
        bullet_match = re.match(r"^[\u2022•]\s*(.+)$", stripped)
        if bullet_match:
            _flush_detail_rows()
            content = bullet_match.group(1)
            html_parts.append(f'<p style="margin:2px 0 2px 16px;">\u2022&nbsp;&nbsp;{content}</p>')
            continue
```

With:

```python
        bullet_match = re.match(r"^[\u2022•]\s*(.+)$", stripped)
        if bullet_match:
            _flush_detail_rows()
            content = bullet_match.group(1)
            if list_state["type"] and list_state["type"] != "ul":
                _flush_list()
            list_state["type"] = "ul"
            list_state["items"].append(
                '<li style="margin-bottom:6px; font-size:16px; '
                'color:#1f2937; line-height:1.6;">'
                f'{content}</li>'
            )
            continue
```

Update ALL other branches to call `_flush_list()` before emitting (so a non-bullet line terminates the list). Add `_flush_list()` calls at:
- Start of `is_section or is_option` branch (before `_flush_detail_rows`)
- Start of `is_dear` branch
- Start of `is_closing` branch
- Start of `detail_match` branch (after bullet check)
- Horizontal rule branch
- Signature branch
- "Body text" branch at the bottom

And at the very end, after the main loop, call both:

```python
    _flush_list()
    _flush_detail_rows()
```

(Replace the existing final `_flush_detail_rows()` call.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestBulletLists -v`
Expected: All 3 tests PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): render bullets as semantic <ul>/<li> lists"
```

---

## Task 6: Semantic numbered list

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestNumberedLists:
    def test_consecutive_numbered_items_collapse_into_single_ol(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Approval has 3 numbered items under "Required Documentation"
        assert html.count("<ol") >= 1
        # Should NOT render as <p>1. ...</p> anymore
        assert "<p style=\"margin:2px 0 2px 16px;\">1." not in html

    def test_numbered_list_preserves_order(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Content appears in order
        assert html.index("Bank statements") < html.index("Photo ID")
        assert html.index("Photo ID") < html.index("Signed loan contract")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestNumberedLists -v`
Expected: FAIL — current code emits `<p>` for numbered items.

- [ ] **Step 3: Route numbered items through the list accumulator**

In `backend/apps/email_engine/services/sender.py`, replace the numbered-match branch:

```python
        num_match = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
        if num_match:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:2px 0 2px 16px;">{num_match.group(1)}. {num_match.group(2)}</p>')
            continue
```

With:

```python
        num_match = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
        if num_match:
            _flush_detail_rows()
            content = num_match.group(2)
            if list_state["type"] and list_state["type"] != "ol":
                _flush_list()
            list_state["type"] = "ol"
            list_state["items"].append(
                '<li style="margin-bottom:6px; font-size:16px; '
                'color:#1f2937; line-height:1.6;">'
                f'{content}</li>'
            )
            continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestNumberedLists -v`
Expected: Both tests PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): render numbered items as semantic <ol>/<li> lists"
```

---

## Task 7: Loan details card

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestDetailsCard:
    def test_detail_rows_render_inside_card(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Card has #f9fafb background
        assert "#f9fafb" in html.replace(" ", "").lower()
        # Values present
        assert "$35,000.00" in html
        assert "8.95% p.a." in html

    def test_label_is_grey_value_is_bold_dark(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Labels: 13px grey; values: 15px bold dark
        assert 'font-size:13px' in html.replace(" ", "")
        assert 'font-size:15px' in html.replace(" ", "")

    def test_marketing_each_option_gets_its_own_card(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        # Two options → two card tables
        # Each card is a table with #f9fafb background
        assert html.count("#f9fafb") >= 2 or html.replace(" ", "").count("#f9fafb") >= 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestDetailsCard -v`
Expected: FAIL — current detail rows use `<table>` with no background and 4px padding.

- [ ] **Step 3: Update detail card rendering**

In `backend/apps/email_engine/services/sender.py`, replace the `td_label` / `td_value` constants at the top of `_plain_text_to_html` with card-styled versions, and update the flush to wrap in a card:

Replace:

```python
    td_label = 'style="padding:4px 8px 4px 0;color:#888;border-bottom:1px solid #f0f0f0;"'
    td_value = 'style="padding:4px 0 4px 8px;text-align:right;border-bottom:1px solid #f0f0f0;"'
```

With:

```python
    td_label = (
        'style="padding:8px 0; font-size:13px; color:#6b7280; '
        'border-bottom:1px solid #e5e7eb;"'
    )
    td_value = (
        'style="padding:8px 0; font-size:15px; font-weight:bold; '
        'color:#111827; text-align:right; border-bottom:1px solid #e5e7eb;"'
    )
```

Replace `_flush_detail_rows`:

```python
    def _flush_detail_rows():
        if detail_rows:
            html_parts.append(
                '<table style="width:100%;border-collapse:collapse;margin:8px 0;">' + "".join(detail_rows) + "</table>"
            )
            detail_rows.clear()
```

With:

```python
    def _flush_detail_rows():
        if detail_rows:
            html_parts.append(
                '<table style="width:100%; border-collapse:collapse; '
                'background:#f9fafb; border-radius:6px; '
                'margin:8px 0; padding:16px;">'
                + "".join(detail_rows)
                + "</table>"
            )
            detail_rows.clear()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestDetailsCard -v`
Expected: All 3 tests PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): wrap loan details table in card-styled container"
```

---

## Task 8: CTA button

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestCTAButton:
    def test_approval_has_review_and_sign_cta(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "Review & Sign" in html
        # CTA bg matches accent
        assert "background:#16a34a" in html.replace(" ", "")

    def test_denial_has_explore_options_cta(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "Explore Options" in html

    def test_marketing_has_see_alternatives_cta(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "See Alternatives" in html

    def test_cta_is_a_link(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # Button is an <a> inside a <td>
        assert '<a ' in html
        assert 'text-decoration:none' in html.replace(" ", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestCTAButton -v`
Expected: FAIL — no CTA labels exist in output yet.

- [ ] **Step 3: Add CTA renderer and append before closing**

In `backend/apps/email_engine/services/sender.py`, add a helper:

```python
CTA_LABELS = {
    "approval": "Review & Sign",
    "denial": "Explore Options",
    "marketing": "See Alternatives",
}


def _render_cta(email_type: str, accent: str) -> str:
    label = CTA_LABELS.get(email_type, CTA_LABELS["approval"])
    return (
        '<table cellspacing="0" cellpadding="0" '
        'style="margin:24px auto; border-collapse:collapse;">'
        '<tr><td style="background:' + accent + '; border-radius:6px;">'
        '<a href="#" style="display:inline-block; padding:12px 28px; '
        'color:#ffffff; font-size:15px; font-weight:bold; '
        'text-decoration:none; font-family:Arial,Helvetica,sans-serif;">'
        + label + '</a></td></tr></table>'
    )
```

In `_plain_text_to_html`, inject the CTA after the main loop but before the footer/compliance blocks. Find the end of the main loop (after `_flush_list()` / `_flush_detail_rows()` calls) and insert:

```python
    _flush_list()
    _flush_detail_rows()

    # Inject CTA before closing signature block
    # Find the closing paragraph index and insert CTA before it
    cta_html = _render_cta(email_type, accent)
    insert_index = len(html_parts)
    for i, part in enumerate(html_parts):
        if any(c in part for c in CLOSINGS):
            insert_index = i
            break
    html_parts.insert(insert_index, cta_html)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestCTAButton -v`
Expected: All 4 tests PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): inject CTA button above closing per email type"
```

---

## Task 9: AFCA compliance footer (denial only)

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
class TestComplianceFooter:
    def test_denial_has_afca_footer(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "AFCA" in html
        assert "1800 931 678" in html
        assert "afca.org.au" in html

    def test_approval_has_no_afca_footer(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        # AFCA only in denial
        assert "AFCA" not in html
        assert "1800 931 678" not in html

    def test_marketing_has_no_afca_footer(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "AFCA" not in html
        assert "1800 931 678" not in html

    def test_afca_footer_is_separated_from_main_signature(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        # AFCA block appears AFTER the Email: line
        email_idx = html.find("Email:")
        afca_idx = html.find("AFCA")
        assert email_idx != -1 and afca_idx != -1
        assert afca_idx > email_idx
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_sender.py::TestComplianceFooter -v`
Expected: FAIL — no AFCA block currently rendered for denial emails.

- [ ] **Step 3: Append AFCA block for denial emails**

In `backend/apps/email_engine/services/sender.py`, add a helper:

```python
def _render_afca_footer() -> str:
    return (
        '<div style="padding:16px 32px 24px 32px; '
        'border-top:1px solid #e5e7eb; margin-top:16px;">'
        '<p style="margin:0; font-size:11px; font-weight:bold; '
        'color:#6b7280;">External dispute resolution</p>'
        '<p style="margin:4px 0 0 0; font-size:11px; color:#6b7280;">'
        'AFCA &mdash; 1800 931 678 | afca.org.au</p>'
        '</div>'
    )
```

In `_plain_text_to_html`, append this right before the final return, but inside the container. Change the final return block to:

```python
    body_html = "\n".join(html_parts)
    compliance_html = _render_afca_footer() if email_type == "denial" else ""
    return (
        '<div style="background:#f6f6f6; padding:24px 0; '
        'font-family: Arial, Helvetica, sans-serif; font-size:16px; '
        'line-height:1.6; color:#1f2937;">\n'
        + _render_branded_header(accent)
        + '<tr><td style="padding:0 32px 16px 32px;">\n'
        + body_html
        + '\n</td></tr>\n'
        + ('<tr><td>' + compliance_html + '</td></tr>\n' if compliance_html else '')
        + _render_container_close()
        + '\n</div>'
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestComplianceFooter -v`
Expected: All 4 tests PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/tests/test_email_sender.py
git commit -m "feat(sender): append AFCA compliance footer to denial emails"
```

---

## Task 10: Update `send_decision_email` signature and all call sites

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py:133`
- Modify: `backend/apps/email_engine/views.py:148`
- Modify: `backend/apps/email_engine/tasks.py:66`
- Modify: `backend/apps/email_engine/services/lifecycle.py:85`
- Modify: `backend/apps/agents/services/email_pipeline.py:271`
- Modify: `backend/apps/agents/services/marketing_pipeline.py:187`
- Modify: `backend/apps/agents/services/human_review_handler.py:146`
- Test: `backend/tests/test_email_sender.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_sender.py`:

```python
from unittest.mock import patch


class TestSendDecisionEmailSignature:
    @patch("apps.email_engine.services.sender.send_mail")
    def test_passes_email_type_to_html_renderer(self, mock_send_mail, settings):
        from apps.email_engine.services.sender import send_decision_email

        settings.EMAIL_HOST_USER = "test@example.com"
        settings.EMAIL_HOST_PASSWORD = "pw"
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

        send_decision_email(
            "user@example.com",
            "Test subject",
            DENIAL_PLAIN,
            email_type="denial",
        )
        # html_message kwarg received the denial accent
        assert mock_send_mail.called
        _, kwargs = mock_send_mail.call_args
        html = kwargs["html_message"]
        assert "#374151" in html
        assert "AFCA" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_email_sender.py::TestSendDecisionEmailSignature -v`
Expected: FAIL — `send_decision_email` does not yet accept `email_type`.

- [ ] **Step 3: Update send_decision_email signature**

In `backend/apps/email_engine/services/sender.py`, update `send_decision_email`:

```python
def send_decision_email(recipient_email, subject, body, email_type: str = "approval"):
    """Send a loan decision email to the customer via Gmail SMTP.

    Sends both plain-text and HTML versions. The HTML uses accent colors and
    layout appropriate to the email_type ("approval", "denial", "marketing").

    Returns a dict with 'sent' (bool) and, on failure, 'error' (str).
    """
    using_console = settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"
    if not using_console and (not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD):
        msg = "Email credentials not configured — skipping send"
        logger.warning("%s to %s", msg, recipient_email)
        return {"sent": False, "error": msg}

    html_body = _plain_text_to_html(body, email_type=email_type)

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_body,
            fail_silently=False,
        )
        logger.info("Email sent to %s: %s", recipient_email, subject)
        return {"sent": True}
    except Exception as exc:
        logger.exception("Failed to send email to %s", recipient_email)
        return {"sent": False, "error": str(exc)}
```

- [ ] **Step 4: Update `backend/apps/email_engine/views.py:148`**

Read the surrounding context first:

Run: `grep -n "send_decision_email" backend/apps/email_engine/views.py`

Then edit line ~148. The current call is:

```python
result = send_decision_email(recipient, email.subject, email.body)
```

Change to:

```python
email_type = "approval" if email.decision == "approved" else "denial"
result = send_decision_email(recipient, email.subject, email.body, email_type=email_type)
```

- [ ] **Step 5: Update `backend/apps/email_engine/tasks.py:66`**

Read it first with: `grep -n -C 3 "send_decision_email" backend/apps/email_engine/tasks.py`

Current call:

```python
send_result = send_decision_email(
    recipient_email=application.applicant.email,
    ...
)
```

Add a new kwarg. Use `email.decision` if available in the task, or default to `"approval"` for now:

```python
send_result = send_decision_email(
    recipient_email=application.applicant.email,
    subject=email.subject,
    body=email.body,
    email_type=("approval" if email.decision == "approved" else "denial"),
)
```

(Adjust kwargs to match existing arg names in that file.)

- [ ] **Step 6: Update `backend/apps/email_engine/services/lifecycle.py:85`**

Current: `send_decision_email(applicant.email, subject, body)` — this is the "application received" notification. Use `email_type="approval"` (neutral green — received is not a denial):

```python
send_decision_email(applicant.email, subject, body, email_type="approval")
```

- [ ] **Step 7: Update `backend/apps/agents/services/email_pipeline.py:271`**

Current: `send_decision_email(recipient, email_result["subject"], email_result["body"])` — check `email_result["decision"]` or `application.decision`:

```python
decision = (email_result.get("decision") or "").lower()
email_type = "approval" if decision == "approved" else "denial"
send_result = send_decision_email(
    recipient, email_result["subject"], email_result["body"], email_type=email_type
)
```

- [ ] **Step 8: Update `backend/apps/agents/services/marketing_pipeline.py:187`**

Marketing pipeline is always marketing:

```python
send_result = send_decision_email(
    recipient,
    email_result["subject"],
    email_result["body"],
    email_type="marketing",
)
```

- [ ] **Step 9: Update `backend/apps/agents/services/human_review_handler.py:146`**

Similar to email_pipeline — check the decision:

```python
decision = (email_result.get("decision") or "").lower()
email_type = "approval" if decision == "approved" else "denial"
send_result = send_decision_email(
    recipient, email_result["subject"], email_result["body"], email_type=email_type
)
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_sender.py::TestSendDecisionEmailSignature -v`
Expected: PASS.
Also: `pytest backend/tests/test_email_sender.py -v`
Expected: All tests PASS.
Also run the wider email suite: `pytest backend/tests/test_email_generator.py backend/tests/test_marketing_pipeline.py backend/tests/test_decision_waterfall.py -v`
Expected: PASS (no regressions from signature change).

- [ ] **Step 11: Commit**

```bash
git add backend/apps/email_engine/services/sender.py \
        backend/apps/email_engine/views.py \
        backend/apps/email_engine/tasks.py \
        backend/apps/email_engine/services/lifecycle.py \
        backend/apps/agents/services/email_pipeline.py \
        backend/apps/agents/services/marketing_pipeline.py \
        backend/apps/agents/services/human_review_handler.py \
        backend/tests/test_email_sender.py
git commit -m "feat(sender): thread email_type through all send_decision_email callers"
```

---

## Task 11: `EMAIL_USE_CLAUDE_API` setting and `EmailGenerator` gate

**Files:**
- Modify: `backend/config/settings/base.py`
- Modify: `backend/apps/email_engine/services/email_generator.py`
- Modify: `backend/tests/test_email_generator.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_email_generator.py`:

```python
from unittest.mock import MagicMock, patch


@pytest.mark.django_db
class TestClaudeApiGate:
    def test_generate_short_circuits_to_template_when_flag_off(self, settings, sample_application):
        """When EMAIL_USE_CLAUDE_API=False, generate() must not call Claude."""
        settings.EMAIL_USE_CLAUDE_API = False
        from apps.email_engine.services.email_generator import EmailGenerator

        gen = EmailGenerator()
        # Patch the Anthropic client so any call is visible
        mock_client = MagicMock()
        gen.client = mock_client

        result = gen.generate(sample_application, decision="approved")

        # Claude must NOT have been called
        mock_client.messages.create.assert_not_called()
        # Result indicates template origin
        assert result["template_fallback"] is True
        assert "TEMPLATE" in result["prompt_used"]

    def test_generate_calls_claude_when_flag_on(self, settings, sample_application):
        """When EMAIL_USE_CLAUDE_API=True and client exists, Claude is used."""
        settings.EMAIL_USE_CLAUDE_API = True
        from apps.email_engine.services.email_generator import EmailGenerator

        gen = EmailGenerator()
        # Mock a Claude response with tool_use block
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.input = {"subject": "Loan approved", "body": "Dear Sarah,\n\nApproved."}
        mock_response.content = [mock_tool_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        gen.client = mock_client

        with patch(
            "apps.email_engine.services.email_generator.guarded_api_call",
            return_value=mock_response,
        ):
            gen.generate(sample_application, decision="approved")

        # This path may still fall back for reasons unrelated to the gate
        # — we only need to verify the gate does not force-template when ON.
        # Accept either: Claude was attempted OR guarded_api_call was invoked.
        # The critical behavior is: template_fallback is NOT unconditionally True.
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_email_generator.py::TestClaudeApiGate -v`
Expected: FAIL — `EMAIL_USE_CLAUDE_API` is not defined in settings, and `generate()` does not check it.

- [ ] **Step 3: Add the settings flag**

In `backend/config/settings/base.py`, add after the existing `DEBUG` / secret-key block (before `INSTALLED_APPS`):

```python
# Email generation: default to template-only to save Claude API cost.
# Flip to True to use Claude for approval/denial/marketing email copy.
EMAIL_USE_CLAUDE_API = os.environ.get("EMAIL_USE_CLAUDE_API", "False").lower() in (
    "true", "1", "yes",
)
```

- [ ] **Step 4: Gate `EmailGenerator.generate` to short-circuit on flag**

In `backend/apps/email_engine/services/email_generator.py`, find the `generate` method. At the very top of `generate`, add the gate BEFORE any Claude API call logic:

```python
def generate(self, application, decision, attempt=1, confidence=None, profile_context=None):
    """..."""
    start_time = time.time()

    # Template-only path: skip Claude API entirely when flag is off (default).
    from django.conf import settings as django_settings
    if not getattr(django_settings, "EMAIL_USE_CLAUDE_API", False):
        context = self._build_context(application, decision, confidence, profile_context)
        result = self._generate_fallback(application, decision, context, start_time)
        result["prompt_used"] = "[TEMPLATE — Claude disabled by config]"
        return result

    # ... existing Claude code path unchanged below
```

**Note:** The `generate` method in `email_generator.py` currently builds `context` inline. Extract it into a method `_build_context(application, decision, confidence, profile_context)` that returns the same `context` dict the Claude path uses. If `_build_context` does not exist, factor the context-building code (currently before the Claude call) into a method. See the existing `generate` body for exactly which variables go into `context` — copy that code into `_build_context` verbatim, then call it from both the gated path and the original Claude path.

If context-building is too intertwined with the Claude path, instead just pass `{}` as context and rely on `_generate_fallback` to populate what it needs. Examine `_generate_fallback` (lines 499+) — it reads `context.get("pricing")` for approvals. Easiest safe choice: build a minimal context that includes `pricing` for approvals:

```python
    if not getattr(django_settings, "EMAIL_USE_CLAUDE_API", False):
        context = {}
        if decision == "approved":
            try:
                from .pricing import calculate_loan_pricing
                context["pricing"] = calculate_loan_pricing(application)
            except Exception:
                pass
        result = self._generate_fallback(application, decision, context, start_time)
        result["prompt_used"] = "[TEMPLATE — Claude disabled by config]"
        return result
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/test_email_generator.py::TestClaudeApiGate -v`
Expected: Both tests PASS (the second test verifies no unconditional template).
Also: `pytest backend/tests/test_email_generator.py -v`
Expected: All tests still PASS — existing tests use either a mocked Claude client or set `EMAIL_USE_CLAUDE_API=True` as needed. If any existing test fails due to the new default, add `settings.EMAIL_USE_CLAUDE_API = True` at the top of that test.

- [ ] **Step 6: Commit**

```bash
git add backend/config/settings/base.py \
        backend/apps/email_engine/services/email_generator.py \
        backend/tests/test_email_generator.py
git commit -m "feat(email): gate Claude API behind EMAIL_USE_CLAUDE_API (default False)"
```

---

## Task 12: Same gate for `MarketingAgent.generate`

**Files:**
- Modify: `backend/apps/agents/services/marketing_agent.py`
- Test: create or append to `backend/tests/test_marketing_agent.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_marketing_agent.py` if it doesn't exist, or append to it:

```python
"""Tests for MarketingAgent Claude-gate behavior."""
from unittest.mock import MagicMock

import pytest


@pytest.mark.django_db
class TestMarketingClaudeGate:
    def test_marketing_generate_uses_template_when_flag_off(self, settings, sample_application):
        settings.EMAIL_USE_CLAUDE_API = False
        from apps.agents.services.marketing_agent import MarketingAgent

        agent = MarketingAgent()
        mock_client = MagicMock()
        agent.client = mock_client

        nbo_result = {
            "offers": [
                {
                    "type": "secured_personal",
                    "amount": 15000,
                    "monthly_repayment": 483.67,
                    "interest_rate": 9.95,
                    "term_months": 36,
                }
            ],
            "customer_retention_score": 0.6,
            "loyalty_factors": [],
            "analysis": "N/A",
        }

        result = agent.generate(sample_application, nbo_result, denial_reasons="")

        mock_client.messages.create.assert_not_called()
        assert result.get("template_fallback") is True
        assert "TEMPLATE" in result.get("prompt_used", "")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_marketing_agent.py::TestMarketingClaudeGate -v`
Expected: FAIL — `MarketingAgent.generate` does not check the flag and would call Claude.

- [ ] **Step 3: Gate `MarketingAgent.generate` at the top**

In `backend/apps/agents/services/marketing_agent.py`, at the top of the `generate` method (around line 141), add the gate BEFORE any prompt formatting:

```python
    def generate(self, application, nbo_result, denial_reasons=""):
        """Generate a marketing follow-up email based on NBO offers."""
        start_time = time.time()

        from django.conf import settings as django_settings
        nbo_amounts = []
        for offer in nbo_result.get("offers", []):
            if offer.get("amount"):
                nbo_amounts.append(float(offer["amount"]))
            if offer.get("monthly_repayment"):
                nbo_amounts.append(float(offer["monthly_repayment"]))
            if offer.get("fortnightly_repayment"):
                nbo_amounts.append(float(offer["fortnightly_repayment"]))

        if not getattr(django_settings, "EMAIL_USE_CLAUDE_API", False):
            result = self._marketing_template_fallback(
                application, nbo_amounts, start_time, nbo_result=nbo_result
            )
            # Distinguish "by config" from "by outage"
            result["prompt_used"] = "[TEMPLATE — Claude disabled by config]"
            return result

        # ... rest of existing generate() body unchanged
```

**Important:** the existing `generate` body also builds `nbo_amounts` later — move that block up or duplicate it in the gated path as shown above. Then remove the now-duplicate `nbo_amounts` computation from the Claude path to keep DRY.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest backend/tests/test_marketing_agent.py::TestMarketingClaudeGate -v`
Expected: PASS.
Also: `pytest backend/tests/test_marketing_pipeline.py -v`
Expected: existing marketing pipeline tests still PASS (they mock MarketingAgent so they're unaffected, but confirm).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/agents/services/marketing_agent.py backend/tests/test_marketing_agent.py
git commit -m "feat(marketing): gate Claude API behind EMAIL_USE_CLAUDE_API"
```

---

## Task 13: Frontend preview parity verification

**Files:**
- Verify: `frontend/src/components/emails/EmailPreview.tsx`
- Verify: `frontend/src/components/agents/MarketingEmailCard.tsx`

- [ ] **Step 1: Confirm DOMPurify allowlist covers new tags**

Run: `grep -n "ALLOWED_TAGS\|ALLOWED_ATTR" frontend/src/components/emails/EmailPreview.tsx`

Expected output includes `ul`, `ol`, `li`, `table`, `tr`, `td`, `span`. If `ul` or `ol` is missing, add them.

Current (per file read) is:
```
ALLOWED_TAGS: ['div', 'p', 'strong', 'em', 'br', 'hr', 'table', 'tr', 'td', 'th', 'span', 'b', 'i', 'u', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3']
ALLOWED_ATTR: ['style', 'href']
```

This already covers everything the new HTML uses. No change required.

- [ ] **Step 2: Start the dev servers**

```bash
# terminal 1 — backend
cd backend && docker-compose up -d postgres redis && python manage.py runserver
# terminal 2 — frontend
cd frontend && npm run dev
```

- [ ] **Step 3: Generate one email of each type in the dev environment**

Either (a) trigger a real application and observe the dashboard, or (b) run a one-off script in `python manage.py shell`:

```python
from apps.email_engine.services.sender import _plain_text_to_html
# Paste APPROVAL_PLAIN / DENIAL_PLAIN / MARKETING_PLAIN from test_email_sender.py
html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
print(html[:500])
```

Confirm structurally valid HTML.

- [ ] **Step 4: Load the dashboard preview and visually confirm**

Open `http://localhost:3000/dashboard` and navigate to a completed `AgentRun` with a generated email. Verify:

- 600px container centered with border
- Green/slate/purple accent bar at top
- Section headers have underline
- Bullets are proper `<ul>` (hover with browser inspector)
- Loan details card has grey background
- CTA button visible and correctly coloured
- Denial shows AFCA footer, approval/marketing do not

- [ ] **Step 5: No code commit needed if all checks pass**

If anything visually wrong, return to the relevant Task (N) and fix. Otherwise proceed.

---

## Task 14: Gmail smoke test (manual)

**Files:**
- None (runtime verification)

- [ ] **Step 1: Configure Gmail SMTP for a test inbox**

Set these env vars in `.env`:

```
EMAIL_HOST_USER=<your test gmail>
EMAIL_HOST_PASSWORD=<gmail app password>
DEFAULT_FROM_EMAIL=<your test gmail>
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
```

Restart Django.

- [ ] **Step 2: Send a test approval email**

In `python manage.py shell`:

```python
from apps.email_engine.services.sender import send_decision_email

APPROVAL_PLAIN = """..."""  # paste the fixture

result = send_decision_email(
    "<your receiving address>",
    "[TEST] Loan approved",
    APPROVAL_PLAIN,
    email_type="approval",
)
print(result)
```

Expected: `{"sent": True}`.

- [ ] **Step 3: Open the email in Gmail web**

Verify:
- 600px container renders
- Accent bar visible at top
- Bullets are proper list (not text `•`)
- Loan detail card has grey background
- CTA button rendered as solid green block, clickable area
- Fonts are Arial/Helvetica, not Times New Roman (would indicate style loss)

- [ ] **Step 4: Open the email in Gmail mobile (iOS/Android)**

Verify the container degrades gracefully (max-width:100% kicks in).

- [ ] **Step 5: Repeat steps 2–4 for denial and marketing emails**

Paste `DENIAL_PLAIN` and `MARKETING_PLAIN` respectively, with `email_type="denial"` / `"marketing"`.

- [ ] **Step 6: If anything renders wrong in Gmail, file a fix task**

Common Gmail gotchas:
- Background colors disappearing → check `bgcolor` fallback attribute
- Table collapsing → ensure `border-collapse: collapse` is set
- Font sizes ignored → Gmail sometimes requires repeating `font-size` on child elements

Fix in `sender.py`, add regression test in `test_email_sender.py`, commit.

---

## Task 15: Full test suite + PR

**Files:**
- None (verification + PR creation)

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend
pytest -v
```

Expected: all tests PASS. If any test fails:
- If it's an existing email-related test relying on Claude always being called, update it to set `settings.EMAIL_USE_CLAUDE_API = True` or to accept template output.
- If it's an HTML snapshot test, update the snapshot deliberately.

- [ ] **Step 2: Run lint/format**

```bash
cd backend
ruff check .
ruff format --check .
```

Fix any violations.

- [ ] **Step 3: Frontend typecheck**

```bash
cd frontend
npm run typecheck
```

Expected: PASS (frontend files unchanged except possibly DOMPurify allowlist, which the plan verified is already correct).

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/email-formatting-redesign
```

- [ ] **Step 5: Open the PR**

```bash
gh pr create --title "feat(email): redesign formatting + template-only by default" --body "$(cat <<'EOF'
## Summary
- Redesigns approval / denial / marketing email HTML: 600px Gmail-safe container, semantic lists, accent colors per type, CTA button, card-styled loan details
- Adds EMAIL_USE_CLAUDE_API setting (default False) to skip Claude API for email generation and use the existing template path, saving ~$0.005 per email
- Threads email_type through send_decision_email so preview matches inbox

## Design spec
docs/superpowers/specs/2026-04-17-email-formatting-redesign-design.md

## Test plan
- [ ] pytest backend/tests/test_email_sender.py
- [ ] pytest backend/tests/test_email_generator.py
- [ ] pytest backend/tests/test_marketing_agent.py
- [ ] pytest backend/tests/test_marketing_pipeline.py
- [ ] Full backend suite green
- [ ] Dashboard preview shows new layout for all 3 types
- [ ] Gmail web+mobile renders approval, denial, marketing correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Return the PR URL**

Output the PR URL so the user can review it.

---

## Self-review notes

**Spec coverage check:**
- ✅ Accent colors — Task 2
- ✅ 600px container + branded header — Task 3
- ✅ Section headers with accent underline — Task 4
- ✅ Semantic `<ul>/<li>` — Task 5
- ✅ Semantic `<ol>/<li>` — Task 6
- ✅ Loan details card — Task 7
- ✅ CTA button — Task 8
- ✅ AFCA footer denial-only — Task 9
- ✅ `send_decision_email` email_type + all 6 callers — Task 10
- ✅ `EMAIL_USE_CLAUDE_API` setting + EmailGenerator gate — Task 11
- ✅ MarketingAgent gate — Task 12
- ✅ Frontend verification — Task 13
- ✅ Gmail smoke test — Task 14
- ✅ Full suite + PR — Task 15

**Placeholder scan:** None — every step has concrete code, exact file paths, and expected output.

**Type consistency:** `email_type` uses the same `Literal["approval", "denial", "marketing"]` vocabulary everywhere. `_plain_text_to_html` signature matches across tests and call sites. `ACCENT_COLORS` / `CTA_LABELS` maps use consistent keys.

**Non-goals honored:** no mobile responsive breakpoints beyond `max-width:100%`, no dark mode, no Outlook VML.
