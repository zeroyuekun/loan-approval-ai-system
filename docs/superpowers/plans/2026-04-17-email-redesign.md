# Email Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify backend + frontend email HTML rendering through a single token-driven renderer that produces visually professional approval, denial, and marketing emails — with dashboard preview byte-identical to Gmail recipient view.

**Architecture:** One Python renderer `backend/apps/email_engine/services/html_renderer.py` is the source of truth for plain-text → HTML conversion. A TypeScript mirror `frontend/src/lib/emailHtmlRenderer.ts` is kept in lockstep via a CI snapshot parity test. Design tokens (colors, type scale, spacing) live at module top in both. Per-type blocks (approval/denial/marketing) render from shared skeleton with type-specific hero icon + accent color + CTA patterns. All markup is Gmail-safe: inline CSS, `<table role="presentation">` layout, no flexbox/grid, ≤102 KB per email.

**Tech Stack:** Python 3.13 + Django + pytest. TypeScript + Next.js + React + vitest. DOMPurify (existing) for frontend sanitization. Playwright (to be added) for visual regression.

**Spec:** `docs/superpowers/specs/2026-04-17-email-redesign-design.md` — read this alongside the plan. Design tokens table, per-type block HTML, and rationale all live there.

---

## File Map

**Created:**
- `backend/apps/email_engine/services/html_renderer.py` — TOKENS dict, `render_html()`, skeleton + per-type block functions
- `backend/tests/test_html_renderer.py` — Python unit tests + fixtures + Gmail-safe lint
- `backend/tests/fixtures/email_bodies/` — 15 `.txt` plain-text fixtures (5 approval / 5 denial / 5 marketing)
- `backend/tests/fixtures/email_snapshots/` — 15 golden `.html` snapshots (written on first run)
- `frontend/src/lib/emailHtmlRenderer.ts` — TS mirror of Python renderer
- `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts` — vitest snapshot tests matching the same 15 fixtures
- `frontend/tests/e2e/email-preview.spec.ts` — Playwright visual regression across approval/denial/marketing preview pages
- `frontend/playwright.config.ts` — Playwright config (if not already present)
- `.github/workflows/email-parity.yml` — CI job diffing Python ↔ TS snapshots

**Modified:**
- `backend/apps/email_engine/services/sender.py` — delete local `_plain_text_to_html()`, import from `html_renderer`
- `frontend/src/components/emails/EmailPreview.tsx` — delete local `plainTextToHtml`, import from `emailHtmlRenderer`
- `frontend/src/components/agents/MarketingEmailCard.tsx` — same swap
- `frontend/package.json` — add `@playwright/test` (only if not already present)

**Kept:**
- Email content generation (`email_generator.py`, `prompts.py`, `template_fallback.py`) — unchanged
- Guardrail pipeline — unchanged
- DOMPurify sanitization in `HtmlEmailBody` — kept as defense-in-depth

---

## PR Boundaries

Six PRs, each merges to master green before the next branches from it.

| PR | Scope |
|---|---|
| 1 | Backend renderer foundation: TOKENS, skeleton, legacy-body port, sender rewire |
| 2 | TS renderer port + dashboard swap + parity CI gate |
| 3 | Approval-specific blocks (hero, loan-card, CTA, signature, attachments) |
| 4 | Denial-specific blocks (hero, factor cards, bureau card, dual CTA) |
| 5 | Marketing-specific blocks (hero, offer cards, unsubscribe footer) |
| 6 | Playwright visual regression + Gmail-safe lint hardening |

Each PR starts from `master`. After merge, rebase `master` locally before branching the next.

---

## PR 1 — Backend Renderer Foundation

**Branch:** `feat/email-renderer-foundation`

**Goal:** Move existing `_plain_text_to_html` behaviour into a new `html_renderer` module, add design TOKENS, wrap output in the shared skeleton with brand header + signature divider + footer. No per-type hero / cards yet — that comes in PR 3-5.

### Task 1.1: Create renderer module with TOKENS and stub

**Files:**
- Create: `backend/apps/email_engine/services/html_renderer.py`
- Test: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_html_renderer.py`:
```python
"""Unit tests for email html_renderer."""
from backend.apps.email_engine.services.html_renderer import TOKENS, render_html


def test_tokens_has_required_keys():
    required = {
        "BRAND_PRIMARY", "BRAND_ACCENT", "SUCCESS", "CAUTION", "MARKETING",
        "TEXT", "MUTED", "FINE", "CARD_BG", "BORDER", "PAGE_BG",
        "FONT_STACK", "BODY_SIZE", "HEAD_SIZE", "LABEL_SIZE", "FINE_SIZE",
        "LINE_HEIGHT", "MAX_WIDTH",
    }
    assert required <= set(TOKENS.keys())


def test_tokens_brand_colors_match_spec():
    assert TOKENS["BRAND_PRIMARY"] == "#1e40af"
    assert TOKENS["BRAND_ACCENT"] == "#3b82f6"
    assert TOKENS["SUCCESS"] == "#16a34a"
    assert TOKENS["CAUTION"] == "#d97706"
    assert TOKENS["MARKETING"] == "#7c3aed"


def test_render_html_returns_string():
    result = render_html("Dear John,\n\nHello.", email_type="approval")
    assert isinstance(result, str)
    assert result.startswith("<!DOCTYPE") or result.startswith("<table") or result.startswith("<html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: FAIL — `ImportError: cannot import name 'TOKENS' from ...html_renderer` (module does not exist yet).

- [ ] **Step 3: Create the module with minimal TOKENS and stub**

Create `backend/apps/email_engine/services/html_renderer.py`:
```python
"""Unified plain-text → Gmail-safe HTML renderer for decision + marketing emails.

Single source of truth for all three email types. Design tokens (colors, type
scale, spacing) live here and mirror verbatim in frontend/src/lib/emailHtmlRenderer.ts.
A CI snapshot parity test fails if the two drift.

See: docs/superpowers/specs/2026-04-17-email-redesign-design.md
"""
from typing import Literal

EmailType = Literal["approval", "denial", "marketing"]

TOKENS: dict[str, str] = {
    "BRAND_PRIMARY": "#1e40af",
    "BRAND_ACCENT": "#3b82f6",
    "SUCCESS": "#16a34a",
    "CAUTION": "#d97706",
    "MARKETING": "#7c3aed",
    "TEXT": "#111827",
    "MUTED": "#6b7280",
    "FINE": "#9ca3af",
    "CARD_BG": "#f8fafc",
    "BORDER": "#e5e7eb",
    "PAGE_BG": "#f3f4f6",
    "FONT_STACK": "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
    "BODY_SIZE": "15px",
    "HEAD_SIZE": "22px",
    "LABEL_SIZE": "13px",
    "FINE_SIZE": "12px",
    "LINE_HEIGHT": "1.6",
    "MAX_WIDTH": "600px",
}


def render_html(plain_body: str, email_type: EmailType) -> str:
    """Convert plain-text email body into Gmail-safe HTML.

    Args:
        plain_body: Raw plain-text email as produced by Claude/template fallback.
        email_type: One of "approval", "denial", "marketing".

    Returns:
        Gmail-safe HTML string with inline styles. Ready to pass to
        Django's send_mail(html_message=...).
    """
    # PR 1 stub — real implementation in later steps.
    return f'<table role="presentation"><tr><td>{plain_body}</td></tr></table>'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py backend/tests/test_html_renderer.py
git commit -m "feat(emails): scaffold html_renderer module with design tokens"
```

---

### Task 1.2: Port legacy body parser into the module

**Why:** PR 1 keeps the existing per-line body parsing behaviour. Only the outer wrapper changes in this PR. PRs 3-5 replace the per-line parser with per-type structured blocks.

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Write failing test for body parser**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_legacy_body_parser_detects_section_labels():
    from backend.apps.email_engine.services.html_renderer import _render_legacy_body
    body = "Dear John,\n\nLoan Details:\n\n  Loan Amount:   $50,000.00"
    out = _render_legacy_body(body)
    assert "<strong>Loan Details:</strong>" in out
    assert "$50,000.00" in out


def test_legacy_body_parser_detects_loan_detail_rows():
    from backend.apps.email_engine.services.html_renderer import _render_legacy_body
    body = "  Loan Amount:             $25,000.00\n  Interest Rate:           6.50% p.a."
    out = _render_legacy_body(body)
    assert "<table" in out
    assert "$25,000.00" in out
    assert "6.50% p.a." in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_html_renderer.py::test_legacy_body_parser_detects_section_labels -v`
Expected: FAIL — `_render_legacy_body` not defined.

- [ ] **Step 3: Port the parser from sender.py into html_renderer.py**

Open `backend/apps/email_engine/services/sender.py`, copy the entire `_plain_text_to_html` body plus its constants `SECTION_LABELS`, `CLOSINGS`, `OPTION_PATTERN`, `LOAN_DETAIL_RE` into `backend/apps/email_engine/services/html_renderer.py`. Rename the function to `_render_legacy_body` and have it return only the inner HTML (no outer `<div style="font-family: Arial…">` wrapper).

Add to the top of `html_renderer.py` (after the TOKENS dict):
```python
import re

SECTION_LABELS = [
    "Loan Details:",
    "Next Steps:",
    "Required Documentation:",
    "Before You Sign:",
    "We're Here For You:",
    "What You Can Do:",
    "We'd Still Like to Help:",
    "Attachments:",
    "Conditions of Approval:",
    "This decision was based on a thorough review of your financial profile, specifically:",
]

CLOSINGS = ["Kind regards,", "Warm regards,"]

OPTION_PATTERN = re.compile(r"^Option\s+\d+[\s:.\-\u2013\u2014]")
LOAN_DETAIL_RE = re.compile(r"^(\s{2,})(\S[^:]+:)\s+(.+)$")


def _render_legacy_body(body: str) -> str:
    """Convert plain-text body lines to inline HTML (legacy per-line parser).

    This matches the historical sender._plain_text_to_html output. Per-type
    block replacements land in PRs 3-5; this function is the fallback for
    any line that does not match a structured block.
    """
    lines = body.split("\n")
    html_parts: list[str] = []
    detail_rows: list[str] = []

    def _flush_detail_rows():
        if detail_rows:
            html_parts.append(
                '<table style="width:100%;border-collapse:collapse;margin:8px 0;">'
                + "".join(detail_rows) + "</table>"
            )
            detail_rows.clear()

    td_label = 'style="padding:4px 8px 4px 0;color:#888;border-bottom:1px solid #f0f0f0;"'
    td_value = 'style="padding:4px 0 4px 8px;text-align:right;border-bottom:1px solid #f0f0f0;"'

    for line in lines:
        stripped = line.strip()
        is_section = stripped in SECTION_LABELS
        is_option = bool(OPTION_PATTERN.match(stripped))
        is_dear = stripped.startswith("Dear ")
        is_closing = stripped in CLOSINGS

        if is_section or is_option:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:20px 0 4px 0;"><strong>{stripped}</strong></p>')
            continue
        if is_dear:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:0 0 4px 0;"><strong>{stripped}</strong></p>')
            continue
        if is_closing:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:20px 0 4px 0;"><strong>{stripped}</strong></p>')
            continue

        bullet_match = re.match(r"^[\u2022•]\s*(.+)$", stripped)
        if bullet_match:
            _flush_detail_rows()
            html_parts.append(
                f'<p style="margin:2px 0 2px 16px;">\u2022&nbsp;&nbsp;{bullet_match.group(1)}</p>'
            )
            continue

        num_match = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
        if num_match:
            _flush_detail_rows()
            html_parts.append(
                f'<p style="margin:2px 0 2px 16px;">{num_match.group(1)}. {num_match.group(2)}</p>'
            )
            continue

        detail_match = LOAN_DETAIL_RE.match(line)
        if detail_match:
            label = detail_match.group(2)
            value = detail_match.group(3)
            if len(label) < 35 and len(value) < 50:
                detail_rows.append(
                    f"<tr><td {td_label}>{label}</td><td {td_value}>{value}</td></tr>"
                )
                continue

        _flush_detail_rows()

        if re.match(r"^[\u2500\u2501\-]{5,}$", stripped):
            html_parts.append(
                '<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">'
            )
            continue

        if (
            stripped.startswith("ABN ")
            or stripped.startswith("Ph:")
            or stripped.startswith("Phone:")
            or stripped.startswith("Email:")
            or stripped.startswith("Website:")
        ):
            html_parts.append(
                f'<p style="margin:0;font-size:12px;color:#888;">{stripped}</p>'
            )
            continue

        if stripped == "":
            html_parts.append('<div style="height:12px;"></div>')
            continue

        margin = "16px" if stripped.endswith(".") else "4px"
        top_margin = "16px" if stripped.startswith("Congratulations") else "0"
        html_parts.append(f'<p style="margin:{top_margin} 0 {margin} 0;">{stripped}</p>')

    _flush_detail_rows()
    return "\n".join(html_parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: PASS — 5 tests now.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py backend/tests/test_html_renderer.py
git commit -m "feat(emails): port legacy body parser into html_renderer"
```

---

### Task 1.3: Build shared skeleton wrapper

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Write failing test for skeleton**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_skeleton_wraps_body_with_brand_header():
    result = render_html("Dear John,\n\nHello.", email_type="approval")
    assert TOKENS["BRAND_PRIMARY"] in result
    assert "AussieLoanAI" in result
    assert "Australian Credit Licence No. 012345" in result


def test_skeleton_uses_600px_max_width():
    result = render_html("Dear John,", email_type="approval")
    assert "max-width:600px" in result


def test_skeleton_wraps_in_outer_page_bg():
    result = render_html("Dear John,", email_type="approval")
    assert TOKENS["PAGE_BG"] in result


def test_skeleton_has_role_presentation_tables():
    result = render_html("Dear John,", email_type="approval")
    assert 'role="presentation"' in result


def test_render_html_includes_legacy_body():
    result = render_html("Dear John,\n\nHello.", email_type="approval")
    assert "Dear John," in result
    assert "Hello." in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: FAIL — 5 new assertions fail; stub returns plain table.

- [ ] **Step 3: Implement skeleton + rewire render_html**

Replace the stub `render_html` at the bottom of `backend/apps/email_engine/services/html_renderer.py` with:
```python
def _render_header() -> str:
    return (
        f'<tr><td style="background-color:{TOKENS["BRAND_PRIMARY"]}; '
        f'padding:16px 24px; border-radius:8px 8px 0 0;">'
        f'<span style="color:#ffffff; font-size:16px; font-weight:600; '
        f'letter-spacing:0.3px;">AussieLoanAI</span>'
        f'<span style="color:#bfdbfe; font-size:12px; margin-left:8px;">'
        f'Australian Credit Licence No. 012345</span>'
        f'</td></tr>'
    )


def _render_footer_shell() -> str:
    return (
        f'<tr><td style="padding:24px; background-color:{TOKENS["CARD_BG"]}; '
        f'border-radius:0 0 8px 8px; font-size:{TOKENS["FINE_SIZE"]}; '
        f'color:{TOKENS["FINE"]};">'
        f'&nbsp;'
        f'</td></tr>'
    )


def render_html(plain_body: str, email_type: EmailType) -> str:
    body_html = _render_legacy_body(plain_body)
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%; background-color:{TOKENS["PAGE_BG"]}; margin:0; padding:0;">'
        f'<tr><td style="padding:32px 16px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%; max-width:{TOKENS["MAX_WIDTH"]}; margin:0 auto; '
        f'background-color:#ffffff; border-radius:8px; '
        f'box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
        f'{_render_header()}'
        f'<tr><td style="padding:24px; font-family:{TOKENS["FONT_STACK"]}; '
        f'font-size:{TOKENS["BODY_SIZE"]}; line-height:{TOKENS["LINE_HEIGHT"]}; '
        f'color:{TOKENS["TEXT"]};">'
        f'{body_html}'
        f'</td></tr>'
        f'{_render_footer_shell()}'
        f'</table>'
        f'</td></tr>'
        f'</table>'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: PASS — all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py backend/tests/test_html_renderer.py
git commit -m "feat(emails): wrap rendered body in brand skeleton (header + page bg)"
```

---

### Task 1.4: Rewire sender.py to use new renderer

**Files:**
- Modify: `backend/apps/email_engine/services/sender.py`
- Modify: `backend/tests/test_html_renderer.py` (add integration assertion)

- [ ] **Step 1: Write failing integration test**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_sender_uses_new_renderer():
    """sender.py must import render_html from html_renderer, not define its own."""
    import backend.apps.email_engine.services.sender as sender_mod
    assert not hasattr(sender_mod, "_plain_text_to_html"), (
        "sender.py should no longer define _plain_text_to_html — "
        "must import render_html from html_renderer instead."
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_html_renderer.py::test_sender_uses_new_renderer -v`
Expected: FAIL — `sender._plain_text_to_html` still exists.

- [ ] **Step 3: Rewrite sender.py**

Replace the entire contents of `backend/apps/email_engine/services/sender.py` with:
```python
import logging

from django.conf import settings
from django.core.mail import send_mail

from backend.apps.email_engine.services.html_renderer import render_html

logger = logging.getLogger(__name__)


def send_decision_email(recipient_email, subject, body, email_type="approval"):
    """Send a loan decision email to the customer via Gmail SMTP.

    Sends both plain-text and HTML versions. The HTML is rendered via the
    unified html_renderer so the dashboard preview and Gmail recipient view
    are identical.

    Args:
        recipient_email: Customer email address.
        subject: Email subject line.
        body: Plain-text email body.
        email_type: One of "approval", "denial", "marketing". Defaults to
            "approval" for backwards compatibility with existing callers.

    Returns:
        dict with 'sent' (bool) and, on failure, 'error' (str).
    """
    using_console = settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"
    if not using_console and (not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD):
        msg = "Email credentials not configured — skipping send"
        logger.warning("%s to %s", msg, recipient_email)
        return {"sent": False, "error": msg}

    html_body = render_html(body, email_type=email_type)

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

- [ ] **Step 4: Find and update existing callers**

Run: `grep -rn "send_decision_email\|_plain_text_to_html" backend/ --include="*.py"`

For any caller that passes only `(recipient_email, subject, body)`, leave as-is — the new `email_type="approval"` default preserves behaviour.

For any caller that also wants denial or marketing rendering, update the call-site to pass `email_type="denial"` or `email_type="marketing"`. Expect these call-sites in `backend/apps/email_engine/tasks.py` (decision email task — pass the decision type) and `backend/apps/agents/services/marketing_agent.py` (pass `"marketing"`).

Example: open `backend/apps/email_engine/tasks.py` and locate the `send_decision_email` call. If the surrounding code has access to the decision outcome, add an `email_type` kwarg:
```python
# Before
send_decision_email(
    recipient_email=app.email,
    subject=subject,
    body=body,
)
# After
send_decision_email(
    recipient_email=app.email,
    subject=subject,
    body=body,
    email_type="approval" if app.outcome == "approved" else "denial",
)
```

- [ ] **Step 5: Run full email test suite**

Run: `cd backend && python -m pytest tests/ -v -k email`
Expected: PASS — no regressions in existing email tests. The dashboard is still exercised via `html_message` kwarg.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/email_engine/services/sender.py backend/apps/email_engine/tasks.py backend/apps/agents/services/marketing_agent.py backend/tests/test_html_renderer.py
git commit -m "refactor(emails): sender + tasks use shared html_renderer"
```

(Only stage `tasks.py` / `marketing_agent.py` if they changed.)

---

### Task 1.5: Add fixture-driven snapshot baseline

**Files:**
- Create: `backend/tests/fixtures/email_bodies/approval_01_personal.txt`
- Create: `backend/tests/fixtures/email_bodies/denial_01_serviceability.txt`
- Create: `backend/tests/fixtures/email_bodies/marketing_01_three_options.txt`
- Modify: `backend/tests/test_html_renderer.py`

**Why:** Baseline snapshots prove PR 1 produces a stable output. PRs 3-5 will see snapshot diffs as the structured blocks replace the legacy parser. The snapshots are the parity contract with the TS port (PR 2).

- [ ] **Step 1: Create three starter fixture files**

Create `backend/tests/fixtures/email_bodies/approval_01_personal.txt` — paste the existing `GOOD_APPROVAL_BODY` from `backend/tests/test_email_generator.py` lines 7-40, plus the closing signature block from that file (read the full fixture for the complete text).

Create `backend/tests/fixtures/email_bodies/denial_01_serviceability.txt` with a representative denial body:
```
Dear Sarah,

Thank you for giving us the opportunity to review your home loan application.

We have carefully reviewed your application and are unable to approve the loan on this occasion.

This decision was based on a thorough review of your financial profile, specifically:

Debt-to-income ratio: Your current debts represent 48% of your monthly income. Our responsible lending assessment looks for this ratio to sit at or below 40%.

Serviceability buffer: After assessing living expenses at the HEM benchmark, the repayments for the requested loan would leave a smaller surplus than we are comfortable lending against.

We have a responsibility under Australian lending rules to only approve loans we believe you can repay without financial strain.

What You Can Do:

Here are some ways to strengthen a future application:

• Reduce outstanding debts by consolidating or paying down balances
• Review your monthly expenses and identify areas to trim
• Consider a smaller loan amount or longer term to reduce repayments

Free Credit Report:

You are entitled to a free credit report from each of the three bureaus once per year:

Equifax: equifax.com.au
Experian: experian.com.au
Illion: illion.com.au

We'd Still Like to Help:

If you would like to discuss other options or review your situation, please call Sarah on 1300 000 000 or reply to this email.

Thanks for coming to us, Sarah.

Kind regards,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd

ABN 12 345 678 901 · ACL 012345
Ph: 1300 000 000
Email: aussieloanai@gmail.com
```

Create `backend/tests/fixtures/email_bodies/marketing_01_three_options.txt`:
```
Dear John,

Thank you for considering AussieLoanAI. While your recent loan application wasn't approved, here are a few options that may suit your current situation.

Option 1: Smaller Personal Loan

• Lower monthly repayments: A $15,000 loan at 6.50% p.a. over 36 months is approximately $460 per month.
• Shorter path to approval: A smaller loan amount reduces serviceability concerns.

With $12,000 in savings, this smaller amount sits comfortably within your current financial profile.

Option 2: Secured Car Loan

• Lower interest rate: Secured loans typically attract a lower rate than unsecured personal loans.
• Fixed repayments: Predictable budgeting over the loan term.

Using a vehicle as security may help serviceability.

Option 3: Rebuild and Reapply in 6 Months

• Free credit check: Review your credit report at equifax.com.au.
• Reduce credit card balances: Lower utilisation improves your credit profile.
• Re-apply with updated finances: We will give your application a fresh review.

Call Sarah on 1300 000 000 to discuss any of these options.

Kind regards,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd

ABN 12 345 678 901 · ACL 012345
Ph: 1300 000 000
Email: aussieloanai@gmail.com

Unsubscribe: https://aussieloanai.com.au/unsubscribe?token=EXAMPLE
```

- [ ] **Step 2: Write snapshot test for the three fixtures**

Add to `backend/tests/test_html_renderer.py`:
```python
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "email_bodies"
SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "email_snapshots"


def _type_for_fixture(name: str) -> str:
    if name.startswith("approval"):
        return "approval"
    if name.startswith("denial"):
        return "denial"
    return "marketing"


def _load_fixture(stem: str) -> str:
    return (FIXTURE_DIR / f"{stem}.txt").read_text(encoding="utf-8")


def _snapshot_path(stem: str) -> Path:
    return SNAPSHOT_DIR / f"{stem}.html"


@pytest.mark.parametrize("stem", [
    "approval_01_personal",
    "denial_01_serviceability",
    "marketing_01_three_options",
])
def test_snapshot_matches(stem):
    import pytest  # noqa
    body = _load_fixture(stem)
    actual = render_html(body, email_type=_type_for_fixture(stem))
    snapshot = _snapshot_path(stem)
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(actual, encoding="utf-8")
        pytest.skip(f"Wrote new snapshot {snapshot.name} — re-run to assert.")
    expected = snapshot.read_text(encoding="utf-8")
    assert actual == expected, (
        f"Snapshot drift in {stem}. "
        f"Delete {snapshot} and re-run to accept the new output."
    )
```

Also add at the top of the file: `import pytest`.

- [ ] **Step 3: Run to write initial snapshots**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: 3 snapshot tests SKIP with "Wrote new snapshot" messages on first run.

- [ ] **Step 4: Re-run to assert snapshots are stable**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: All tests PASS — snapshots match.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/ backend/tests/test_html_renderer.py
git commit -m "test(emails): add 3 snapshot fixtures covering all types"
```

---

### Task 1.6: Add Gmail-safe lint

**Files:**
- Modify: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Write failing test for Gmail-safe invariants**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_no_flexbox_or_grid():
    for stem in ["approval_01_personal", "denial_01_serviceability", "marketing_01_three_options"]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        for forbidden in ["display:flex", "display: flex", "display:grid",
                          "display: grid", "display:inline-flex"]:
            assert forbidden not in html, f"{stem}: forbidden `{forbidden}` in output"


def test_no_style_tag():
    for stem in ["approval_01_personal", "denial_01_serviceability", "marketing_01_three_options"]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert "<style" not in html.lower(), f"{stem}: found <style> tag (Gmail strips these)"


def test_size_under_102kb():
    for stem in ["approval_01_personal", "denial_01_serviceability", "marketing_01_three_options"]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        size_kb = len(html.encode("utf-8")) / 1024
        assert size_kb < 102, f"{stem}: {size_kb:.1f} KB — Gmail clips at 102 KB"


def test_inner_max_width_600():
    html = render_html("Dear John,", email_type="approval")
    assert "max-width:600px" in html
```

- [ ] **Step 2: Run test**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: All tests PASS (current output is already Gmail-safe).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_html_renderer.py
git commit -m "test(emails): Gmail-safe invariants (no flex/grid, <102KB, max-width 600)"
```

---

### Task 1.7: Manual Gmail smoke + open PR 1

- [ ] **Step 1: Run full email test suite**

Run: `cd backend && python -m pytest tests/ -v -k email`
Expected: PASS across all email-related tests.

- [ ] **Step 2: Send a local smoke email (optional if Gmail SMTP creds are present)**

Run from `backend/`:
```bash
python manage.py shell -c "
from backend.apps.email_engine.services.sender import send_decision_email
from pathlib import Path
body = Path('tests/fixtures/email_bodies/approval_01_personal.txt').read_text(encoding='utf-8')
print(send_decision_email('eddie.zeng95@gmail.com', '[Smoke] PR1 approval render', body, email_type='approval'))
"
```
Expected: Gmail inbox shows branded header, page background, rounded container. Body structure still uses legacy formatting (PRs 3-5 will layer on hero + cards).

If `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` are not set, skip this step — CI coverage is sufficient.

- [ ] **Step 3: Push branch + open PR**

```bash
git push -u origin feat/email-renderer-foundation
gh pr create --title "feat(emails): shared html_renderer + design tokens" --body "$(cat <<'EOF'
## Summary
- New `backend/apps/email_engine/services/html_renderer.py` with design TOKENS and `render_html(body, email_type)` function
- Brand-color header bar, page-background wrapper, 600px max-width container
- Ported legacy body parser in as an intermediate step — PRs 3-5 replace it with per-type structured blocks
- `sender.py` rewired to import from `html_renderer`; backwards-compatible with existing callers via `email_type="approval"` default
- 3 snapshot fixtures + Gmail-safe lint (no flex/grid, <102 KB, max-width 600)

## Test plan
- [x] `pytest backend/tests/test_html_renderer.py` — 14 tests pass
- [x] `pytest backend/tests/ -k email` — no regressions
- [ ] Manual: Gmail SMTP smoke email (requires credentials)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Wait for CI green, merge, rebase master**

After CI green and merge:
```bash
git checkout master
git pull origin master
```

---

## PR 2 — TypeScript Renderer Port + Dashboard Swap

**Branch:** `feat/email-renderer-ts-port` (branch from fresh master after PR 1 merge)

**Goal:** Mirror the Python renderer in TypeScript so dashboard preview is byte-identical to Gmail HTML. Swap `EmailPreview.tsx` and `MarketingEmailCard.tsx` to use the new TS renderer. Add CI parity gate diffing Python vs TS snapshots.

### Task 2.1: Create TS renderer with tokens

**Files:**
- Create: `frontend/src/lib/emailHtmlRenderer.ts`
- Create: `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts`

- [ ] **Step 1: Write failing test**

Create `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts`:
```typescript
import { describe, it, expect } from 'vitest'
import { TOKENS, renderEmailHtml } from '@/lib/emailHtmlRenderer'

describe('TOKENS', () => {
  it('has required keys', () => {
    const required = [
      'BRAND_PRIMARY', 'BRAND_ACCENT', 'SUCCESS', 'CAUTION', 'MARKETING',
      'TEXT', 'MUTED', 'FINE', 'CARD_BG', 'BORDER', 'PAGE_BG',
      'FONT_STACK', 'BODY_SIZE', 'HEAD_SIZE', 'LABEL_SIZE', 'FINE_SIZE',
      'LINE_HEIGHT', 'MAX_WIDTH',
    ]
    for (const key of required) {
      expect(TOKENS).toHaveProperty(key)
    }
  })

  it('brand colors match spec', () => {
    expect(TOKENS.BRAND_PRIMARY).toBe('#1e40af')
    expect(TOKENS.BRAND_ACCENT).toBe('#3b82f6')
    expect(TOKENS.SUCCESS).toBe('#16a34a')
    expect(TOKENS.CAUTION).toBe('#d97706')
    expect(TOKENS.MARKETING).toBe('#7c3aed')
  })
})

describe('renderEmailHtml', () => {
  it('returns a string', () => {
    const result = renderEmailHtml('Dear John,\n\nHello.', 'approval')
    expect(typeof result).toBe('string')
  })

  it('includes the body text', () => {
    const result = renderEmailHtml('Dear John,\n\nHello.', 'approval')
    expect(result).toContain('Dear John,')
    expect(result).toContain('Hello.')
  })

  it('includes brand header', () => {
    const result = renderEmailHtml('Dear John,', 'approval')
    expect(result).toContain('AussieLoanAI')
    expect(result).toContain(TOKENS.BRAND_PRIMARY)
  })

  it('uses 600px max-width', () => {
    const result = renderEmailHtml('Dear John,', 'approval')
    expect(result).toContain('max-width:600px')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create `frontend/src/lib/emailHtmlRenderer.ts`**

```typescript
/**
 * TypeScript mirror of backend/apps/email_engine/services/html_renderer.py.
 * CI parity test diffs Python vs TS snapshots — any drift fails the build.
 *
 * See: docs/superpowers/specs/2026-04-17-email-redesign-design.md
 */

export type EmailType = 'approval' | 'denial' | 'marketing'

export const TOKENS = {
  BRAND_PRIMARY: '#1e40af',
  BRAND_ACCENT: '#3b82f6',
  SUCCESS: '#16a34a',
  CAUTION: '#d97706',
  MARKETING: '#7c3aed',
  TEXT: '#111827',
  MUTED: '#6b7280',
  FINE: '#9ca3af',
  CARD_BG: '#f8fafc',
  BORDER: '#e5e7eb',
  PAGE_BG: '#f3f4f6',
  FONT_STACK: "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
  BODY_SIZE: '15px',
  HEAD_SIZE: '22px',
  LABEL_SIZE: '13px',
  FINE_SIZE: '12px',
  LINE_HEIGHT: '1.6',
  MAX_WIDTH: '600px',
} as const

const SECTION_LABELS = [
  'Loan Details:',
  'Next Steps:',
  'Required Documentation:',
  'Before You Sign:',
  "We're Here For You:",
  'What You Can Do:',
  "We'd Still Like to Help:",
  'Attachments:',
  'Conditions of Approval:',
  'This decision was based on a thorough review of your financial profile, specifically:',
]
const CLOSINGS = ['Kind regards,', 'Warm regards,']
const OPTION_RE = /^Option\s+\d+[\s:.\-\u2013\u2014]/
const LOAN_DETAIL_RE = /^(\s{2,})(\S[^:]+:)\s+(.+)$/
const HR_RE = /^[\u2500\u2501\-]{5,}$/
const BULLET_RE = /^[\u2022•]\s*(.+)$/
const NUM_RE = /^\s+(\d+)\.\s+(.+)$/

function renderLegacyBody(body: string): string {
  const lines = body.split('\n')
  const parts: string[] = []
  let detailRows: string[] = []
  const tdLabel = 'style="padding:4px 8px 4px 0;color:#888;border-bottom:1px solid #f0f0f0;"'
  const tdValue = 'style="padding:4px 0 4px 8px;text-align:right;border-bottom:1px solid #f0f0f0;"'

  const flushRows = () => {
    if (detailRows.length) {
      parts.push(`<table style="width:100%;border-collapse:collapse;margin:8px 0;">${detailRows.join('')}</table>`)
      detailRows = []
    }
  }

  for (const line of lines) {
    const stripped = line.trim()
    const isSection = SECTION_LABELS.includes(stripped)
    const isOption = OPTION_RE.test(stripped)
    const isDear = stripped.startsWith('Dear ')
    const isClosing = CLOSINGS.includes(stripped)

    if (isSection || isOption) {
      flushRows()
      parts.push(`<p style="margin:20px 0 4px 0;"><strong>${stripped}</strong></p>`)
      continue
    }
    if (isDear) {
      flushRows()
      parts.push(`<p style="margin:0 0 4px 0;"><strong>${stripped}</strong></p>`)
      continue
    }
    if (isClosing) {
      flushRows()
      parts.push(`<p style="margin:20px 0 4px 0;"><strong>${stripped}</strong></p>`)
      continue
    }

    const bulletMatch = stripped.match(BULLET_RE)
    if (bulletMatch) {
      flushRows()
      parts.push(`<p style="margin:2px 0 2px 16px;">\u2022&nbsp;&nbsp;${bulletMatch[1]}</p>`)
      continue
    }

    const numMatch = line.match(NUM_RE)
    if (numMatch) {
      flushRows()
      parts.push(`<p style="margin:2px 0 2px 16px;">${numMatch[1]}. ${numMatch[2]}</p>`)
      continue
    }

    const detailMatch = line.match(LOAN_DETAIL_RE)
    if (detailMatch) {
      const label = detailMatch[2]
      const value = detailMatch[3]
      if (label.length < 35 && value.length < 50) {
        detailRows.push(`<tr><td ${tdLabel}>${label}</td><td ${tdValue}>${value}</td></tr>`)
        continue
      }
    }

    flushRows()

    if (HR_RE.test(stripped)) {
      parts.push('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">')
      continue
    }

    if (
      stripped.startsWith('ABN ') ||
      stripped.startsWith('Ph:') ||
      stripped.startsWith('Phone:') ||
      stripped.startsWith('Email:') ||
      stripped.startsWith('Website:')
    ) {
      parts.push(`<p style="margin:0;font-size:12px;color:#888;">${stripped}</p>`)
      continue
    }

    if (stripped === '') {
      parts.push('<div style="height:12px;"></div>')
      continue
    }

    const margin = stripped.endsWith('.') ? '16px' : '4px'
    const topMargin = stripped.startsWith('Congratulations') ? '16px' : '0'
    parts.push(`<p style="margin:${topMargin} 0 ${margin} 0;">${stripped}</p>`)
  }

  flushRows()
  return parts.join('\n')
}

function renderHeader(): string {
  return (
    `<tr><td style="background-color:${TOKENS.BRAND_PRIMARY}; ` +
    `padding:16px 24px; border-radius:8px 8px 0 0;">` +
    `<span style="color:#ffffff; font-size:16px; font-weight:600; ` +
    `letter-spacing:0.3px;">AussieLoanAI</span>` +
    `<span style="color:#bfdbfe; font-size:12px; margin-left:8px;">` +
    `Australian Credit Licence No. 012345</span>` +
    `</td></tr>`
  )
}

function renderFooterShell(): string {
  return (
    `<tr><td style="padding:24px; background-color:${TOKENS.CARD_BG}; ` +
    `border-radius:0 0 8px 8px; font-size:${TOKENS.FINE_SIZE}; ` +
    `color:${TOKENS.FINE};">&nbsp;</td></tr>`
  )
}

export function renderEmailHtml(plainBody: string, emailType: EmailType): string {
  const bodyHtml = renderLegacyBody(plainBody)
  return (
    `<table role="presentation" cellpadding="0" cellspacing="0" border="0" ` +
    `style="width:100%; background-color:${TOKENS.PAGE_BG}; margin:0; padding:0;">` +
    `<tr><td style="padding:32px 16px;">` +
    `<table role="presentation" cellpadding="0" cellspacing="0" border="0" ` +
    `style="width:100%; max-width:${TOKENS.MAX_WIDTH}; margin:0 auto; ` +
    `background-color:#ffffff; border-radius:8px; ` +
    `box-shadow:0 1px 3px rgba(0,0,0,0.06);">` +
    `${renderHeader()}` +
    `<tr><td style="padding:24px; font-family:${TOKENS.FONT_STACK}; ` +
    `font-size:${TOKENS.BODY_SIZE}; line-height:${TOKENS.LINE_HEIGHT}; ` +
    `color:${TOKENS.TEXT};">` +
    `${bodyHtml}` +
    `</td></tr>` +
    `${renderFooterShell()}` +
    `</table>` +
    `</td></tr>` +
    `</table>`
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts`
Expected: PASS — all TS tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/emailHtmlRenderer.ts frontend/src/__tests__/lib/emailHtmlRenderer.test.ts
git commit -m "feat(emails): TypeScript port of html_renderer with TOKENS"
```

---

### Task 2.2: TS snapshot parity with Python

**Files:**
- Create: `frontend/src/__tests__/fixtures/email_bodies/` (symlink or copy from `backend/tests/fixtures/email_bodies/`)
- Modify: `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts`

- [ ] **Step 1: Copy fixtures**

Run:
```bash
mkdir -p frontend/src/__tests__/fixtures/email_bodies frontend/src/__tests__/fixtures/email_snapshots
cp backend/tests/fixtures/email_bodies/*.txt frontend/src/__tests__/fixtures/email_bodies/
cp backend/tests/fixtures/email_snapshots/*.html frontend/src/__tests__/fixtures/email_snapshots/
```

- [ ] **Step 2: Write failing parity test**

Add to `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts`:
```typescript
import fs from 'node:fs'
import path from 'node:path'

const FIXTURE_DIR = path.resolve(__dirname, '../fixtures/email_bodies')
const SNAPSHOT_DIR = path.resolve(__dirname, '../fixtures/email_snapshots')

function typeForFixture(name: string): EmailType {
  if (name.startsWith('approval')) return 'approval'
  if (name.startsWith('denial')) return 'denial'
  return 'marketing'
}

describe('snapshot parity with Python renderer', () => {
  const stems = ['approval_01_personal', 'denial_01_serviceability', 'marketing_01_three_options']
  for (const stem of stems) {
    it(`${stem} matches Python snapshot byte-for-byte`, () => {
      const body = fs.readFileSync(path.join(FIXTURE_DIR, `${stem}.txt`), 'utf-8')
      const actual = renderEmailHtml(body, typeForFixture(stem))
      const expected = fs.readFileSync(path.join(SNAPSHOT_DIR, `${stem}.html`), 'utf-8')
      expect(actual).toBe(expected)
    })
  }
})
```

- [ ] **Step 3: Run test**

Run: `cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts`
Expected: Either PASS (if ports match exactly) or FAIL (diff output pinpointing the divergence).

- [ ] **Step 4: If diverge, reconcile the two ports line-by-line**

Walk through the diff — likely culprits: string-concatenation whitespace, regex escaping, unicode sequence handling. Fix the TS port to match Python output exactly, not the other way round (Python is the reference).

Re-run until green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/__tests__/fixtures/ frontend/src/__tests__/lib/emailHtmlRenderer.test.ts
git commit -m "test(emails): TS ↔ Python snapshot parity (3 fixtures)"
```

---

### Task 2.3: Swap EmailPreview to shared renderer

**Files:**
- Modify: `frontend/src/components/emails/EmailPreview.tsx`

- [ ] **Step 1: Write failing test asserting the import swap**

Create `frontend/src/__tests__/components/EmailPreview.renderer.test.tsx`:
```typescript
import { describe, it, expect } from 'vitest'
import * as EmailPreviewModule from '@/components/emails/EmailPreview'

describe('EmailPreview uses shared renderer', () => {
  it('does not define local plainTextToHtml', () => {
    const source = (EmailPreviewModule as unknown as Record<string, unknown>).__source__ ??
      require('node:fs').readFileSync(require.resolve('@/components/emails/EmailPreview'), 'utf-8')
    expect(typeof source === 'string').toBe(true)
    if (typeof source === 'string') {
      expect(source).not.toContain('function plainTextToHtml')
    }
  })
})
```

- [ ] **Step 2: Run test**

Run: `cd frontend && npx vitest run src/__tests__/components/EmailPreview.renderer.test.tsx`
Expected: FAIL — `plainTextToHtml` still defined locally.

- [ ] **Step 3: Swap EmailPreview.tsx to use shared renderer**

In `frontend/src/components/emails/EmailPreview.tsx`:

1. Add import near the top (after existing imports):
   ```typescript
   import { renderEmailHtml } from '@/lib/emailHtmlRenderer'
   ```

2. Delete the entire local `plainTextToHtml` function (lines 27-34 in current file).

3. Replace the line:
   ```typescript
   const htmlContent = useMemo(() => email.html_body || plainTextToHtml(email.body), [email.html_body, email.body])
   ```
   with:
   ```typescript
   const htmlContent = useMemo(
     () => email.html_body || renderEmailHtml(email.body, email.decision === 'approved' ? 'approval' : 'denial'),
     [email.html_body, email.body, email.decision]
   )
   ```

4. **Important — DOMPurify allowlist expansion:** the new renderer emits `<table>`, `<tr>`, `<td>`, `<h1>` already in the allowlist, but also emits `role`, `cellpadding`, `cellspacing`, `border`, `align`, `target` attributes. Update the DOMPurify config in the `HtmlEmailBody` component:
   ```typescript
   const sanitized = DOMPurify.sanitize(html, {
     ALLOWED_TAGS: ['div', 'p', 'strong', 'em', 'br', 'hr', 'table', 'tr', 'td', 'th', 'span', 'b', 'i', 'u', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3'],
     ALLOWED_ATTR: ['style', 'href', 'role', 'cellpadding', 'cellspacing', 'border', 'align', 'target'],
   })
   ```

- [ ] **Step 4: Run full EmailPreview test suite**

Run: `cd frontend && npx vitest run src/__tests__/components/EmailPreview`
Expected: All existing + new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/emails/EmailPreview.tsx frontend/src/__tests__/components/EmailPreview.renderer.test.tsx
git commit -m "refactor(emails): EmailPreview uses shared renderer, drops local plainTextToHtml"
```

---

### Task 2.4: Swap MarketingEmailCard to shared renderer

**Files:**
- Modify: `frontend/src/components/agents/MarketingEmailCard.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/__tests__/components/MarketingEmailCard.renderer.test.tsx`:
```typescript
import { describe, it, expect } from 'vitest'

describe('MarketingEmailCard uses shared renderer', () => {
  it('does not define local plainTextToHtml', () => {
    const source = require('node:fs').readFileSync(
      require.resolve('@/components/agents/MarketingEmailCard'),
      'utf-8'
    )
    expect(source).not.toContain('function plainTextToHtml')
  })
})
```

- [ ] **Step 2: Run test**

Run: `cd frontend && npx vitest run src/__tests__/components/MarketingEmailCard.renderer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Edit MarketingEmailCard.tsx**

Open `frontend/src/components/agents/MarketingEmailCard.tsx`:
1. Add near top imports: `import { renderEmailHtml } from '@/lib/emailHtmlRenderer'`.
2. Delete the local `plainTextToHtml` function.
3. Replace any call site that invokes `plainTextToHtml(body)` with `renderEmailHtml(body, 'marketing')`.

- [ ] **Step 4: Run test**

Run: `cd frontend && npx vitest run src/__tests__/components/MarketingEmailCard`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agents/MarketingEmailCard.tsx frontend/src/__tests__/components/MarketingEmailCard.renderer.test.tsx
git commit -m "refactor(emails): MarketingEmailCard uses shared renderer"
```

---

### Task 2.5: CI parity workflow

**Files:**
- Create: `.github/workflows/email-parity.yml`

- [ ] **Step 1: Create workflow**

```yaml
name: email-renderer-parity

on:
  pull_request:
    paths:
      - 'backend/apps/email_engine/services/html_renderer.py'
      - 'frontend/src/lib/emailHtmlRenderer.ts'
      - 'backend/tests/fixtures/email_**'
      - 'frontend/src/__tests__/fixtures/email_**'
      - '.github/workflows/email-parity.yml'

jobs:
  parity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install backend deps
        run: |
          cd backend
          pip install -r requirements/base.txt
          pip install pytest
      - name: Install frontend deps
        run: |
          cd frontend
          npm ci
      - name: Run Python renderer tests
        run: |
          cd backend
          python -m pytest tests/test_html_renderer.py -v
      - name: Diff fixture snapshots backend vs frontend
        run: |
          diff -r backend/tests/fixtures/email_snapshots frontend/src/__tests__/fixtures/email_snapshots
      - name: Run TS parity tests
        run: |
          cd frontend
          npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/email-parity.yml
git commit -m "ci: add Python ↔ TS email renderer parity workflow"
```

---

### Task 2.6: Open PR 2

- [ ] **Step 1: Push + open PR**

```bash
git push -u origin feat/email-renderer-ts-port
gh pr create --title "feat(emails): typescript renderer port + dashboard swap" --body "$(cat <<'EOF'
## Summary
- New `frontend/src/lib/emailHtmlRenderer.ts` mirroring `backend/apps/email_engine/services/html_renderer.py` verbatim
- `EmailPreview.tsx` + `MarketingEmailCard.tsx` delete local `plainTextToHtml` and import from shared renderer
- Dashboard preview HTML is now byte-identical to Gmail recipient view (3 snapshot fixtures enforce this)
- New CI workflow `email-renderer-parity.yml` diffs Python vs TS snapshots and fails on drift
- DOMPurify allowlist expanded to cover new table attrs (role, cellpadding, cellspacing, border, align, target)

## Test plan
- [x] `npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts` — TS renderer passes
- [x] Snapshot parity test — TS output === Python output byte-for-byte
- [x] `npx vitest run src/__tests__/components/EmailPreview` — no regressions
- [x] `npx vitest run src/__tests__/components/MarketingEmailCard` — no regressions

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: CI green, merge, rebase master**

```bash
git checkout master
git pull origin master
```

---

## PR 3 — Approval Block Redesign

**Branch:** `feat/email-approval-blocks` (branch from fresh master after PR 2 merge)

**Goal:** Replace the legacy-body parse for approval emails with structured blocks: green ✓ hero, loan-details card, numbered next-step pills, bulletproof CTA, attachments chip row, divided signature block, footer with comparison-rate warning.

### Task 3.1: Add 4 more approval fixtures

**Files:**
- Create: `backend/tests/fixtures/email_bodies/approval_02_home_loan.txt`
- Create: `backend/tests/fixtures/email_bodies/approval_03_with_cosigner.txt`
- Create: `backend/tests/fixtures/email_bodies/approval_04_conditional.txt`
- Create: `backend/tests/fixtures/email_bodies/approval_05_auto_loan.txt`

- [ ] **Step 1: Create the four fixtures**

Each file is a plain-text approval email similar in structure to `approval_01_personal.txt` but varying:
- `02_home_loan`: Home Loan type, property value, deposit, 300-month term, LMI note
- `03_with_cosigner`: "with your co-signer Jane Smith" in greeting, dual-borrower language
- `04_conditional`: Includes "Conditions of Approval:" section with 3 conditions
- `05_auto_loan`: Auto Loan type, secured, 60-month term, no establishment fee

Use the existing approval prompt output format — refer to `backend/apps/email_engine/services/prompts.py::APPROVAL_EMAIL_PROMPT` for the structure. Each fixture should exercise a different combination of sections so later snapshot tests catch block-level drift.

- [ ] **Step 2: Also copy to frontend fixtures**

```bash
cp backend/tests/fixtures/email_bodies/approval_0*.txt frontend/src/__tests__/fixtures/email_bodies/
```

- [ ] **Step 3: Extend snapshot parametrization in both tests**

In `backend/tests/test_html_renderer.py`, expand the approval stem list:
```python
@pytest.mark.parametrize("stem", [
    "approval_01_personal",
    "approval_02_home_loan",
    "approval_03_with_cosigner",
    "approval_04_conditional",
    "approval_05_auto_loan",
    "denial_01_serviceability",
    "marketing_01_three_options",
])
def test_snapshot_matches(stem):
    ...
```

Mirror the list change in `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts`.

- [ ] **Step 4: Run tests — snapshots will auto-write, then re-run to assert**

Run twice:
```bash
cd backend && python -m pytest tests/test_html_renderer.py -v
cd backend && python -m pytest tests/test_html_renderer.py -v
```
Expected: First run skips with "Wrote new snapshot"; second run passes.

```bash
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS (TS snapshots auto-mirror via parity — copy updated backend snapshots forward before running; see Task 2.5 workflow).

Run `cp backend/tests/fixtures/email_snapshots/approval_0*.html frontend/src/__tests__/fixtures/email_snapshots/` before the TS run.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/ frontend/src/__tests__/fixtures/ backend/tests/test_html_renderer.py frontend/src/__tests__/lib/emailHtmlRenderer.test.ts
git commit -m "test(emails): add 4 more approval fixtures"
```

---

### Task 3.2: Approval hero block

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `frontend/src/lib/emailHtmlRenderer.ts`

**Decision:** Introduce a per-type dispatch. For `email_type="approval"`, the renderer now extracts the first paragraph after "Dear X," and renders the structured hero + subtitle, then renders the rest via the legacy parser. This lets PR 3 build up structure incrementally without breaking denial/marketing.

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_approval_renders_success_hero():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Green hero icon tile
    assert "background-color:#16a34a" in html  # SUCCESS
    # Check-mark entity
    assert "&#10003;" in html
    # Congratulations subtitle
    assert "Congratulations" in html
```

- [ ] **Step 2: Run — FAIL**

Run: `cd backend && python -m pytest tests/test_html_renderer.py::test_approval_renders_success_hero -v`
Expected: FAIL — no green tile yet.

- [ ] **Step 3: Implement approval hero in html_renderer.py**

Add to `backend/apps/email_engine/services/html_renderer.py`:
```python
HERO_CONFIG = {
    "approval": {
        "icon": "&#10003;",  # ✓
        "color": TOKENS["SUCCESS"],
        "default_headline": "Your Loan Is Approved",
    },
    "denial": {
        "icon": "&#9432;",  # Ⓘ
        "color": TOKENS["CAUTION"],
        "default_headline": "Update on Your Application",
    },
    "marketing": {
        "icon": "&#10022;",  # ✦
        "color": TOKENS["MARKETING"],
        "default_headline": "A Few Options for You",
    },
}


def _extract_applicant_name(body: str) -> str:
    for line in body.split("\n")[:5]:
        s = line.strip()
        if s.startswith("Dear "):
            return s[5:].rstrip(",").split()[0]
    return "there"


def _extract_approval_loan_type(body: str) -> str:
    # Scan the first 300 chars for "your application for a <Type> Loan"
    m = re.search(r"application for a ([A-Z][A-Za-z]+ Loan)", body)
    return m.group(1) if m else "Loan"


def _render_hero(email_type: EmailType, body: str) -> str:
    cfg = HERO_CONFIG[email_type]
    name = _extract_applicant_name(body)
    if email_type == "approval":
        loan_type = _extract_approval_loan_type(body)
        headline = f"Your {loan_type} Is Approved"
        subtitle = f"Congratulations, {name}!"
    elif email_type == "denial":
        headline = cfg["default_headline"]
        subtitle = f"{name}, we've reviewed your application"
    else:  # marketing
        headline = cfg["default_headline"]
        subtitle = "Following your recent application"

    return (
        f'<tr><td style="padding:32px 24px 16px 24px;">'
        f'<div style="width:48px; height:48px; border-radius:24px; '
        f'background-color:{cfg["color"]}; text-align:center; '
        f'line-height:48px; color:#ffffff; font-size:24px; '
        f'font-weight:600;">{cfg["icon"]}</div>'
        f'<h1 style="font-size:{TOKENS["HEAD_SIZE"]}; line-height:28px; '
        f'color:{TOKENS["TEXT"]}; margin:12px 0 4px 0; font-weight:600;">'
        f'{headline}</h1>'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; '
        f'color:{TOKENS["MUTED"]};">{subtitle}</div>'
        f'</td></tr>'
    )
```

Then update `render_html` to insert the hero between header and body. Replace the body-row line:
```python
f'{_render_header()}'
f'<tr><td style="padding:24px; font-family:{TOKENS["FONT_STACK"]}; '
```
with:
```python
f'{_render_header()}'
f'{_render_hero(email_type, plain_body)}'
f'<tr><td style="padding:0 24px 24px 24px; font-family:{TOKENS["FONT_STACK"]}; '
```

- [ ] **Step 4: Run — PASS (test); snapshots will drift**

Run: `cd backend && python -m pytest tests/test_html_renderer.py::test_approval_renders_success_hero -v`
Expected: PASS.

Then run full suite: `cd backend && python -m pytest tests/test_html_renderer.py -v`
Expected: snapshot tests FAIL because output changed. This is expected — re-accept snapshots:

```bash
# Delete drifted snapshots — the test will regenerate them
rm backend/tests/fixtures/email_snapshots/approval_*.html
rm backend/tests/fixtures/email_snapshots/denial_*.html
rm backend/tests/fixtures/email_snapshots/marketing_*.html
cd backend && python -m pytest tests/test_html_renderer.py -v  # writes new snapshots
cd backend && python -m pytest tests/test_html_renderer.py -v  # asserts them
```

Visually inspect one snapshot (e.g. `approval_01_personal.html`) and confirm the hero block is sensible.

- [ ] **Step 5: Mirror in TypeScript**

Open `frontend/src/lib/emailHtmlRenderer.ts` and add the mirror:
```typescript
const HERO_CONFIG = {
  approval: { icon: '&#10003;', color: TOKENS.SUCCESS, defaultHeadline: 'Your Loan Is Approved' },
  denial: { icon: '&#9432;', color: TOKENS.CAUTION, defaultHeadline: 'Update on Your Application' },
  marketing: { icon: '&#10022;', color: TOKENS.MARKETING, defaultHeadline: 'A Few Options for You' },
} as const

function extractApplicantName(body: string): string {
  for (const line of body.split('\n').slice(0, 5)) {
    const s = line.trim()
    if (s.startsWith('Dear ')) {
      return s.slice(5).replace(/,$/, '').split(/\s+/)[0]
    }
  }
  return 'there'
}

function extractApprovalLoanType(body: string): string {
  const m = body.match(/application for a ([A-Z][A-Za-z]+ Loan)/)
  return m ? m[1] : 'Loan'
}

function renderHero(emailType: EmailType, body: string): string {
  const cfg = HERO_CONFIG[emailType]
  const name = extractApplicantName(body)
  let headline: string
  let subtitle: string
  if (emailType === 'approval') {
    headline = `Your ${extractApprovalLoanType(body)} Is Approved`
    subtitle = `Congratulations, ${name}!`
  } else if (emailType === 'denial') {
    headline = cfg.defaultHeadline
    subtitle = `${name}, we've reviewed your application`
  } else {
    headline = cfg.defaultHeadline
    subtitle = 'Following your recent application'
  }
  return (
    `<tr><td style="padding:32px 24px 16px 24px;">` +
    `<div style="width:48px; height:48px; border-radius:24px; ` +
    `background-color:${cfg.color}; text-align:center; ` +
    `line-height:48px; color:#ffffff; font-size:24px; ` +
    `font-weight:600;">${cfg.icon}</div>` +
    `<h1 style="font-size:${TOKENS.HEAD_SIZE}; line-height:28px; ` +
    `color:${TOKENS.TEXT}; margin:12px 0 4px 0; font-weight:600;">` +
    `${headline}</h1>` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; ` +
    `color:${TOKENS.MUTED};">${subtitle}</div>` +
    `</td></tr>`
  )
}
```

And update `renderEmailHtml` to insert `${renderHero(emailType, plainBody)}` after `${renderHeader()}` with matching padding change.

- [ ] **Step 6: Refresh TS snapshots from backend, run TS tests**

```bash
cp backend/tests/fixtures/email_snapshots/*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS — TS output matches Python.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py frontend/src/lib/emailHtmlRenderer.ts backend/tests/fixtures/email_snapshots/ frontend/src/__tests__/fixtures/email_snapshots/ backend/tests/test_html_renderer.py
git commit -m "feat(emails): per-type hero block (success/caution/marketing icon)"
```

---

### Task 3.3: Approval loan-details card

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `frontend/src/lib/emailHtmlRenderer.ts`

**Intent:** When `email_type == "approval"` and the body contains a `Loan Details:` section followed by indented `Label: Value` rows, replace that block with the styled card (SUCCESS left border, uppercase label, key/value rows with 1px dividers).

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_approval_loan_details_renders_as_card():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # SUCCESS left border
    assert "border-left:4px solid #16a34a" in html
    # Uppercase label
    assert "LOAN DETAILS" in html.upper()  # allow case-insensitive match
    # Values preserved
    assert "$25,000.00" in html
    assert "6.50% p.a." in html
```

- [ ] **Step 2: Run — FAIL**

Run: `cd backend && python -m pytest tests/test_html_renderer.py::test_approval_loan_details_renders_as_card -v`
Expected: FAIL.

- [ ] **Step 3: Implement block detection + card rendering**

Add to `backend/apps/email_engine/services/html_renderer.py`:
```python
def _extract_loan_details(body: str) -> tuple[list[tuple[str, str]], int, int]:
    """Find the 'Loan Details:' block. Return [(label, value), ...] + start/end line indices.

    Returns ([], -1, -1) if no Loan Details block is found.
    """
    lines = body.split("\n")
    start = None
    end = None
    rows: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        if line.strip() == "Loan Details:":
            start = i
            continue
        if start is not None:
            m = LOAN_DETAIL_RE.match(line)
            if m:
                rows.append((m.group(2).rstrip(":"), m.group(3).strip()))
                end = i
                continue
            if line.strip() == "" and end is not None:
                # Blank line after rows ends the block
                end = i
                break
            if line.strip() != "" and not m:
                # Non-row content ends the block
                end = i - 1
                break
    return rows, start if start is not None else -1, end if end is not None else -1


def _render_loan_details_card(rows: list[tuple[str, str]]) -> str:
    row_html = ""
    for i, (label, value) in enumerate(rows):
        is_last = i == len(rows) - 1
        border = "" if is_last else f"border-bottom:1px solid {TOKENS['BORDER']};"
        row_html += (
            f'<tr>'
            f'<td style="padding:8px 0; font-size:14px; color:{TOKENS["MUTED"]}; {border}">{label}</td>'
            f'<td style="padding:8px 0; font-size:14px; color:{TOKENS["TEXT"]}; '
            f'font-weight:600; text-align:right; {border}">{value}</td>'
            f'</tr>'
        )
    return (
        f'<tr><td style="padding:16px 0;">'
        f'<table role="presentation" style="width:100%; background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["SUCCESS"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f'color:{TOKENS["BRAND_PRIMARY"]}; text-transform:uppercase; '
        f'letter-spacing:0.5px; padding-bottom:8px;">Loan Details</div>'
        f'<table role="presentation" style="width:100%;">{row_html}</table>'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _body_with_block_removed(body: str, start: int, end: int) -> str:
    lines = body.split("\n")
    return "\n".join(lines[:start] + lines[end + 1:])
```

Now wire this into `render_html` — for `email_type="approval"`, pre-extract the loan-details block, remove it from the body before legacy-parsing, and splice in the structured card at the right position.

Replace the body-row line in `render_html`:
```python
f'{bodyHtml_or_whatever_var_is_called}'
```
with (restructured approval path):
```python
if email_type == "approval":
    rows, start, end = _extract_loan_details(plain_body)
    if rows:
        body_for_legacy = _body_with_block_removed(plain_body, start, end)
        legacy_top = _render_legacy_body("\n".join(body_for_legacy.split("\n")[:start]))
        legacy_rest = _render_legacy_body("\n".join(body_for_legacy.split("\n")[start:]))
        body_html = legacy_top + _render_loan_details_card(rows) + legacy_rest
    else:
        body_html = _render_legacy_body(plain_body)
else:
    body_html = _render_legacy_body(plain_body)
```

(Update the skeleton string concatenation to insert `{body_html}` in the content cell. Keep the body wrapper `<tr><td>…</td></tr>` — only the interior string changes.)

- [ ] **Step 4: Regenerate snapshots, re-run**

```bash
rm backend/tests/fixtures/email_snapshots/approval_*.html
cd backend && python -m pytest tests/test_html_renderer.py -v
cd backend && python -m pytest tests/test_html_renderer.py -v
```
Expected: test PASS; snapshots updated.

- [ ] **Step 5: Mirror in TS**

Add equivalent `extractLoanDetails`, `renderLoanDetailsCard`, `bodyWithBlockRemoved` to `frontend/src/lib/emailHtmlRenderer.ts` using the same string outputs. Wire into `renderEmailHtml` for `emailType === 'approval'`.

Copy snapshots forward and run:
```bash
cp backend/tests/fixtures/email_snapshots/*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py frontend/src/lib/emailHtmlRenderer.ts backend/tests/fixtures/email_snapshots/ frontend/src/__tests__/fixtures/email_snapshots/ backend/tests/test_html_renderer.py
git commit -m "feat(emails): approval loan-details card with SUCCESS left border"
```

---

### Task 3.4: Approval next-steps pills + CTA button + attachments chips + signature

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `frontend/src/lib/emailHtmlRenderer.ts`
- Modify: `backend/tests/test_html_renderer.py`

**Why bundle these:** Each is a small block dependent on detecting a specific plain-text section. Doing them in one task keeps the diff coherent and avoids intermediate snapshots that never ship.

- [ ] **Step 1: Write failing tests for each block**

Add to `backend/tests/test_html_renderer.py`:
```python
def test_approval_next_steps_renders_numbered_pills():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Numbered pill with BRAND_PRIMARY bg
    assert "border-radius:50%" in html or "border-radius:12px" in html
    assert "background-color:#1e40af" in html


def test_approval_has_cta_button():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Bulletproof CTA wrapped in table + anchor
    assert "Sign & Return" in html or "Review & Sign" in html
    # BRAND_ACCENT button bg
    assert "background-color:#3b82f6" in html


def test_approval_signature_has_divider():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Top-border divider separates body from signature
    assert "border-top:1px solid #e5e7eb" in html
    assert "Sarah Mitchell" in html
    assert "Senior Lending Officer" in html


def test_approval_attachments_chip_row():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Attachment chips use CARD_BG
    if "Attachments:" in body:
        assert "📎" in html
```

- [ ] **Step 2: Run — FAIL**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v -k approval`
Expected: multiple FAIL.

- [ ] **Step 3: Implement the four blocks**

Extend `backend/apps/email_engine/services/html_renderer.py` with:

```python
def _extract_numbered_steps(body: str, section_label: str) -> tuple[list[str], int, int]:
    """Find a section like 'Next Steps:' followed by '  1. ...' lines.

    Returns ([step_text, ...], start_line, end_line) or ([], -1, -1).
    """
    lines = body.split("\n")
    start = None
    end = None
    steps: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == section_label and start is None:
            start = i
            continue
        if start is not None:
            m = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
            if m:
                steps.append(m.group(2).strip())
                end = i
                continue
            if steps and (line.strip() == "" or not m):
                end = i - 1 if line.strip() != "" else i
                break
    return steps, start if start else -1, end if end else -1


def _render_next_steps_block(steps: list[str]) -> str:
    rows = ""
    for i, text in enumerate(steps, start=1):
        rows += (
            f'<tr>'
            f'<td style="width:28px; padding:0 0 12px 0; vertical-align:top;">'
            f'<div style="width:24px; height:24px; border-radius:12px; '
            f'background-color:{TOKENS["BRAND_PRIMARY"]}; color:#ffffff; '
            f'font-size:12px; font-weight:600; line-height:24px; text-align:center;">{i}</div>'
            f'</td>'
            f'<td style="padding:0 0 12px 12px; font-size:{TOKENS["BODY_SIZE"]}; '
            f'color:{TOKENS["TEXT"]};">{text}</td>'
            f'</tr>'
        )
    return (
        f'<tr><td style="padding:8px 0 16px 0;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f'color:{TOKENS["MUTED"]}; text-transform:uppercase; letter-spacing:0.5px; '
        f'padding-bottom:12px;">Next Steps</div>'
        f'<table role="presentation" style="width:100%;">{rows}</table>'
        f'</td></tr>'
    )


def _render_cta(text: str, href: str, color: str = None) -> str:
    bg = color or TOKENS["BRAND_ACCENT"]
    return (
        f'<tr><td align="center" style="padding:16px 0 24px 0;">'
        f'<table role="presentation" cellspacing="0" cellpadding="0">'
        f'<tr><td style="background-color:{bg}; border-radius:6px;">'
        f'<a href="{href}" target="_blank" '
        f'style="display:inline-block; padding:12px 28px; color:#ffffff; '
        f'font-size:{TOKENS["BODY_SIZE"]}; font-weight:600; '
        f'text-decoration:none;">{text}</a>'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _render_signature_block(body: str) -> str:
    """Re-render the 'Kind regards, … ABN … Ph … Email …' tail as a divided block."""
    # Detect closing + signature lines
    lines = body.split("\n")
    sig_start = None
    for i, line in enumerate(lines):
        if line.strip() in CLOSINGS:
            sig_start = i
            break
    if sig_start is None:
        return ""
    tail = lines[sig_start:]
    # Parse: closing, [blank], name, title, company, [blank], ABN, Ph, Email
    closing = tail[0].strip()
    name = next((ln.strip() for ln in tail[1:] if ln.strip() and ln.strip() not in CLOSINGS), "")
    remaining = [ln.strip() for ln in tail[tail.index(name) + 1 if name in [t.strip() for t in tail] else 2:] if ln.strip()]
    title = remaining[0] if len(remaining) > 0 else ""
    company = remaining[1] if len(remaining) > 1 else ""
    contact_lines = [l for l in remaining[2:] if l.startswith(("ABN ", "Ph:", "Phone:", "Email:", "Website:"))]
    contact_html = "".join(
        f'<div style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]};">{line}</div>'
        for line in contact_lines
    )
    return (
        f'<tr><td style="padding:24px 0 0 0; border-top:1px solid {TOKENS["BORDER"]};">'
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding-bottom:8px;">{closing}</div>'
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'font-weight:600;">{name}</div>'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["MUTED"]};">{title}</div>'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["MUTED"]}; '
        f'padding-bottom:8px;">{company}</div>'
        f'{contact_html}'
        f'</td></tr>'
    )


def _render_attachments_chips(names: list[str]) -> str:
    if not names:
        return ""
    chips = "<td style=\"width:8px;\"></td>".join(
        f'<td style="padding:6px 12px; background-color:{TOKENS["PAGE_BG"]}; '
        f'border:1px solid {TOKENS["BORDER"]}; border-radius:4px; '
        f'font-size:{TOKENS["LABEL_SIZE"]}; color:#374151;">&#128206; {n}</td>'
        for n in names
    )
    return (
        f'<tr><td style="padding:16px 0;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f'color:{TOKENS["MUTED"]}; text-transform:uppercase; letter-spacing:0.5px; '
        f'padding-bottom:8px;">Attachments</div>'
        f'<table role="presentation"><tr>{chips}</tr></table>'
        f'</td></tr>'
    )
```

Now wire the approval branch in `render_html`:
```python
if email_type == "approval":
    rows, ld_start, ld_end = _extract_loan_details(plain_body)
    steps, ns_start, ns_end = _extract_numbered_steps(plain_body, "Next Steps:")
    # Remove both blocks from body-for-legacy to avoid duplication
    working = plain_body
    if rows:
        working = _body_with_block_removed(working, ld_start, ld_end)
    # After removal, recompute next-steps indices against the shortened body
    steps, ns_start, ns_end = _extract_numbered_steps(working, "Next Steps:")
    if steps:
        working = _body_with_block_removed(working, ns_start, ns_end)

    # Split signature off so it's not double-rendered
    working_lines = working.split("\n")
    sig_idx = next((i for i, ln in enumerate(working_lines) if ln.strip() in CLOSINGS), None)
    if sig_idx is not None:
        top_body = "\n".join(working_lines[:sig_idx])
        signature_block = _render_signature_block(plain_body)
    else:
        top_body = working
        signature_block = ""

    legacy_top = _render_legacy_body(top_body)
    card_html = _render_loan_details_card(rows) if rows else ""
    steps_html = _render_next_steps_block(steps) if steps else ""
    cta_html = _render_cta(
        "Review & Sign Documents",
        "https://portal.aussieloanai.com.au/sign",
    ) if steps else ""
    # Attachments — detect from body or use defaults for approval
    att_names = []
    if "Attachments:" in plain_body:
        att_names = ["Loan Contract.pdf", "Key Facts Sheet.pdf", "Credit Guide.pdf"]
    att_html = _render_attachments_chips(att_names)

    body_html = (
        legacy_top + card_html + steps_html + cta_html + att_html + signature_block
    )
else:
    body_html = _render_legacy_body(plain_body)
```

- [ ] **Step 4: Regenerate snapshots, assert tests**

```bash
rm backend/tests/fixtures/email_snapshots/approval_*.html
cd backend && python -m pytest tests/test_html_renderer.py -v
cd backend && python -m pytest tests/test_html_renderer.py -v
```
Expected: PASS. Visually inspect `approval_01_personal.html` snapshot — should show hero, greeting, loan card, next-steps block, CTA, attachments, signature.

- [ ] **Step 5: Mirror in TS**

Port all four functions (`extractNumberedSteps`, `renderNextStepsBlock`, `renderCta`, `renderSignatureBlock`, `renderAttachmentsChips`) to `frontend/src/lib/emailHtmlRenderer.ts` with identical output. Wire into the approval branch of `renderEmailHtml`.

Copy snapshots forward + run TS tests:
```bash
cp backend/tests/fixtures/email_snapshots/*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py frontend/src/lib/emailHtmlRenderer.ts backend/tests/fixtures/email_snapshots/ frontend/src/__tests__/fixtures/email_snapshots/ backend/tests/test_html_renderer.py
git commit -m "feat(emails): approval next-steps pills + CTA + attachments + signature block"
```

---

### Task 3.5: Open PR 3

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/email-approval-blocks
gh pr create --title "feat(emails): approval block redesign (hero, loan-card, cta, attachments, signature)" --body "$(cat <<'EOF'
## Summary
- Green ✓ hero tile with "Your {Loan Type} Is Approved" headline
- Loan details card with SUCCESS left border and uppercase label
- Numbered next-step pills with BRAND_PRIMARY circles
- Bulletproof CTA button (Review & Sign Documents)
- Attachments chip row with file icon and CARD_BG chips
- Signature block with 1px top divider and dim contact details
- Python + TS renderers in lockstep (snapshots byte-identical)
- 5 approval fixtures snapshot-tested

## Test plan
- [x] `pytest backend/tests/test_html_renderer.py` — all approval tests pass
- [x] `npx vitest run frontend/src/__tests__/lib/emailHtmlRenderer` — parity preserved
- [x] Visual inspect: approval_01 snapshot renders hero, card, pills, CTA, chips, signature

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: CI green, merge, rebase master**

```bash
git checkout master && git pull origin master
```

---

## PR 4 — Denial Block Redesign

**Branch:** `feat/email-denial-blocks` (branch from fresh master after PR 3 merge)

**Goal:** Denial-specific blocks: amber Ⓘ hero, assessment-factors card (CAUTION border), what-you-can-do card (SUCCESS border, forward-looking), free credit report card (BRAND_ACCENT border, three bureau rows), dual CTA (Call Sarah button + reply-to-email link), dignified tone preserved.

### Task 4.1: Add 4 more denial fixtures

**Files:**
- Create: `backend/tests/fixtures/email_bodies/denial_0{2,3,4,5}*.txt`

- [ ] **Step 1: Create 4 fixtures**

- `denial_02_credit_score.txt` — credit-score-based denial, includes "Free Credit Report:" with bureau URLs
- `denial_03_employment.txt` — employment-stability denial, dignified wording
- `denial_04_multiple_factors.txt` — 3 assessment factors, What-You-Can-Do has 4 bullets
- `denial_05_policy.txt` — bankruptcy/policy-based denial, shorter body

Each follows the format of `denial_01_serviceability.txt`. Pull directly from `backend/apps/email_engine/services/template_fallback.py::generate_denial_template()` output to match prompt format.

- [ ] **Step 2: Mirror to frontend + extend parametrization**

```bash
cp backend/tests/fixtures/email_bodies/denial_0*.txt frontend/src/__tests__/fixtures/email_bodies/
```
Update both test files' `@pytest.mark.parametrize` and TS `for (const stem of [...])` lists.

- [ ] **Step 3: Baseline snapshots**

```bash
cd backend && python -m pytest tests/test_html_renderer.py -v  # writes snapshots
cd backend && python -m pytest tests/test_html_renderer.py -v  # asserts them
cp backend/tests/fixtures/email_snapshots/denial_*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/fixtures/ frontend/src/__tests__/fixtures/ backend/tests/test_html_renderer.py frontend/src/__tests__/lib/emailHtmlRenderer.test.ts
git commit -m "test(emails): add 4 more denial fixtures"
```

---

### Task 4.2: Denial assessment-factors + what-you-can-do + credit-report cards

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `frontend/src/lib/emailHtmlRenderer.ts`
- Modify: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Write failing tests**

Add:
```python
def test_denial_assessment_factors_card():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    # CAUTION left border
    assert "border-left:4px solid #d97706" in html
    assert "ASSESSMENT FACTORS" in html.upper()


def test_denial_what_you_can_do_card():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    # SUCCESS left border (forward-looking)
    assert "border-left:4px solid #16a34a" in html
    assert "WHAT YOU CAN DO" in html.upper()


def test_denial_credit_report_card():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    assert "FREE CREDIT REPORT" in html.upper()
    # BRAND_ACCENT border + clickable URLs
    assert "border-left:4px solid #3b82f6" in html
    assert 'href="https://equifax.com.au"' in html or 'equifax.com.au' in html


def test_denial_dual_cta():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    # Call-Sarah button
    assert 'href="tel:' in html
    assert "Call Sarah" in html
```

- [ ] **Step 2: Run — FAIL**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v -k denial`
Expected: multiple FAIL.

- [ ] **Step 3: Implement denial blocks**

Extend `backend/apps/email_engine/services/html_renderer.py`:

```python
def _extract_section_bullets(body: str, section_label: str) -> tuple[list[str], int, int]:
    """Find '{label}:' followed by bullet-point lines.  Return (lines, start, end)."""
    lines = body.split("\n")
    start = None
    end = None
    bullets: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == section_label and start is None:
            start = i
            continue
        if start is not None:
            s = line.strip()
            m = re.match(r"^[\u2022•]\s*(.+)$", s)
            if m:
                bullets.append(m.group(1))
                end = i
                continue
            if bullets and s == "":
                end = i
                break
            if bullets and s != "":
                end = i - 1
                break
    return bullets, start if start else -1, end if end else -1


def _extract_factor_paragraphs(body: str) -> tuple[list[tuple[str, str]], int, int]:
    """Factors follow 'specifically:' line, each is 'Label: explanation sentence.'
    Return ([(label, text), ...], start, end).
    """
    lines = body.split("\n")
    trigger_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("This decision was based on"):
            trigger_idx = i
            break
    if trigger_idx is None:
        return [], -1, -1
    factors: list[tuple[str, str]] = []
    end = trigger_idx
    i = trigger_idx + 1
    while i < len(lines):
        s = lines[i].strip()
        if s == "":
            i += 1
            continue
        m = re.match(r"^([A-Z][A-Za-z\s\-/]+):\s+(.+)$", s)
        if m:
            factors.append((m.group(1).strip(), m.group(2).strip()))
            end = i
            i += 1
            continue
        # Non-factor line ends the block
        break
    return factors, trigger_idx, end


def _render_factor_card(factors: list[tuple[str, str]]) -> str:
    rows = ""
    for i, (label, text) in enumerate(factors):
        is_last = i == len(factors) - 1
        border = "" if is_last else f"border-bottom:1px solid {TOKENS['BORDER']};"
        rows += (
            f'<tr><td style="padding:12px 0; {border}">'
            f'<div style="font-size:14px; font-weight:600; '
            f'color:{TOKENS["TEXT"]};">{label}</div>'
            f'<div style="font-size:14px; color:{TOKENS["TEXT"]}; '
            f'padding-top:4px;">{text}</div>'
            f'</td></tr>'
        )
    return (
        f'<tr><td style="padding:16px 0;">'
        f'<table role="presentation" style="width:100%; '
        f'background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["CAUTION"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f'color:{TOKENS["CAUTION"]}; text-transform:uppercase; '
        f'letter-spacing:0.5px; padding-bottom:8px;">Assessment Factors</div>'
        f'<table role="presentation" style="width:100%;">{rows}</table>'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _render_what_you_can_do_card(bullets: list[str], intro: str = "") -> str:
    items = "".join(
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding:4px 0 4px 16px; position:relative;">'
        f'<span style="color:{TOKENS["SUCCESS"]};">&#10003;</span> &nbsp;{b}</div>'
        for b in bullets
    )
    intro_html = (
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding-bottom:8px;">{intro}</div>' if intro else ""
    )
    return (
        f'<tr><td style="padding:16px 0;">'
        f'<table role="presentation" style="width:100%; '
        f'background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["SUCCESS"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f'color:{TOKENS["SUCCESS"]}; text-transform:uppercase; '
        f'letter-spacing:0.5px; padding-bottom:8px;">What You Can Do</div>'
        f'{intro_html}{items}'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _render_credit_report_card() -> str:
    bureaus = [
        ("Equifax", "https://equifax.com.au"),
        ("Experian", "https://experian.com.au"),
        ("Illion", "https://illion.com.au"),
    ]
    rows = "".join(
        f'<tr><td style="padding:6px 0; font-size:14px; color:{TOKENS["TEXT"]};">'
        f'<strong>{name}</strong> &mdash; '
        f'<a href="{url}" style="color:{TOKENS["BRAND_ACCENT"]};">{url.replace("https://", "")}</a>'
        f'</td></tr>'
        for name, url in bureaus
    )
    return (
        f'<tr><td style="padding:16px 0;">'
        f'<table role="presentation" style="width:100%; '
        f'background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["BRAND_ACCENT"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f'color:{TOKENS["BRAND_ACCENT"]}; text-transform:uppercase; '
        f'letter-spacing:0.5px; padding-bottom:8px;">Free Credit Report</div>'
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding-bottom:8px;">You are entitled to a free credit report from each bureau once per year:</div>'
        f'<table role="presentation" style="width:100%;">{rows}</table>'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _render_dual_cta() -> str:
    primary = _render_cta("Call Sarah on 1300 000 000", "tel:1300000000")
    secondary = (
        f'<tr><td align="center" style="padding:0 0 16px 0;">'
        f'<a href="mailto:aussieloanai@gmail.com" '
        f'style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["BRAND_ACCENT"]}; '
        f'text-decoration:underline;">Or reply to this email</a>'
        f'</td></tr>'
    )
    return primary + secondary
```

Add denial branch to `render_html`:
```python
elif email_type == "denial":
    factors, f_start, f_end = _extract_factor_paragraphs(plain_body)
    wycd, w_start, w_end = _extract_section_bullets(plain_body, "What You Can Do:")

    working = plain_body
    for start, end in sorted([(f_start, f_end), (w_start, w_end)], reverse=True):
        if start >= 0:
            working = _body_with_block_removed(working, start, end)

    # Also remove "Free Credit Report:" section — we render a structured card
    lines = working.split("\n")
    cr_start = None
    cr_end = None
    for i, line in enumerate(lines):
        if line.strip() == "Free Credit Report:":
            cr_start = i
            # Consume until blank line after URLs
            j = i + 1
            while j < len(lines):
                s = lines[j].strip()
                if s == "" and cr_end is not None:
                    break
                if s != "":
                    cr_end = j
                j += 1
            break
    if cr_start is not None and cr_end is not None:
        working = _body_with_block_removed(working, cr_start, cr_end)

    # Split signature off
    working_lines = working.split("\n")
    sig_idx = next((i for i, ln in enumerate(working_lines) if ln.strip() in CLOSINGS), None)
    top_body = "\n".join(working_lines[:sig_idx]) if sig_idx is not None else working
    sig_block = _render_signature_block(plain_body) if sig_idx is not None else ""

    legacy_top = _render_legacy_body(top_body)
    factor_html = _render_factor_card(factors) if factors else ""
    wycd_html = _render_what_you_can_do_card(
        wycd, intro="Here are some ways to strengthen a future application:"
    ) if wycd else ""
    cr_html = _render_credit_report_card() if cr_start is not None else ""
    cta_html = _render_dual_cta()

    body_html = (
        legacy_top + factor_html + wycd_html + cr_html + cta_html + sig_block
    )
```

- [ ] **Step 4: Regenerate snapshots, assert**

```bash
rm backend/tests/fixtures/email_snapshots/denial_*.html
cd backend && python -m pytest tests/test_html_renderer.py -v
cd backend && python -m pytest tests/test_html_renderer.py -v
```
Expected: PASS.

- [ ] **Step 5: Mirror in TS**

Port `extractSectionBullets`, `extractFactorParagraphs`, `renderFactorCard`, `renderWhatYouCanDoCard`, `renderCreditReportCard`, `renderDualCta` — and the denial branch — to `frontend/src/lib/emailHtmlRenderer.ts`.

```bash
cp backend/tests/fixtures/email_snapshots/denial_*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py frontend/src/lib/emailHtmlRenderer.ts backend/tests/fixtures/email_snapshots/ frontend/src/__tests__/fixtures/email_snapshots/ backend/tests/test_html_renderer.py
git commit -m "feat(emails): denial blocks (factor card, wycd card, credit card, dual cta)"
```

---

### Task 4.3: Open PR 4

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/email-denial-blocks
gh pr create --title "feat(emails): denial block redesign (hero, factor cards, bureau card, dual cta)" --body "$(cat <<'EOF'
## Summary
- Amber Ⓘ hero tile (CAUTION color, not red — dignified)
- Assessment Factors card with CAUTION border and per-factor dividers
- What You Can Do card with SUCCESS border (forward-looking) and check-marked bullets
- Free Credit Report card with BRAND_ACCENT border and clickable bureau URLs
- Dual CTA: primary Call Sarah button (tel: link) + secondary reply-to-email text link
- 5 denial fixtures snapshot-tested; Python + TS in lockstep

## Test plan
- [x] `pytest backend/tests/test_html_renderer.py` — denial tests pass
- [x] `npx vitest run` — TS parity preserved
- [x] Visual inspect: denial_01 snapshot shows amber hero, three distinct card borders, dual CTA

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: CI green, merge, rebase master**

```bash
git checkout master && git pull origin master
```

---

## PR 5 — Marketing Block Redesign

**Branch:** `feat/email-marketing-blocks` (branch from fresh master after PR 4 merge)

**Goal:** Marketing-specific blocks: purple ✦ hero, offer cards (MARKETING left border, 1-3 repeating), Call Sarah CTA, **mandatory unsubscribe link** in footer (Spam Act 2003), conditional disclaimers.

### Task 5.1: Add 4 more marketing fixtures

**Files:**
- Create: `backend/tests/fixtures/email_bodies/marketing_0{2,3,4,5}*.txt`

- [ ] **Step 1: Create 4 fixtures**

- `marketing_02_two_options.txt` — 2 offers only
- `marketing_03_single_option.txt` — 1 offer
- `marketing_04_term_deposit.txt` — includes FCS disclaimer trigger (contains "term deposit")
- `marketing_05_bonus_rate.txt` — includes bonus-rate disclaimer trigger (contains "bonus rate")

Derive format from `backend/apps/agents/services/marketing_agent.py::_marketing_template_fallback()` output.

- [ ] **Step 2: Mirror to frontend, extend parametrization**

```bash
cp backend/tests/fixtures/email_bodies/marketing_0*.txt frontend/src/__tests__/fixtures/email_bodies/
```
Extend both test file stem lists.

- [ ] **Step 3: Baseline snapshots + run**

```bash
cd backend && python -m pytest tests/test_html_renderer.py -v  # writes
cd backend && python -m pytest tests/test_html_renderer.py -v  # asserts
cp backend/tests/fixtures/email_snapshots/marketing_*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/fixtures/ frontend/src/__tests__/fixtures/ backend/tests/test_html_renderer.py frontend/src/__tests__/lib/emailHtmlRenderer.test.ts
git commit -m "test(emails): add 4 more marketing fixtures"
```

---

### Task 5.2: Marketing offer cards + unsubscribe footer

**Files:**
- Modify: `backend/apps/email_engine/services/html_renderer.py`
- Modify: `frontend/src/lib/emailHtmlRenderer.ts`
- Modify: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Write failing tests**

Add:
```python
def test_marketing_offer_cards():
    body = _load_fixture("marketing_01_three_options")
    html = render_html(body, email_type="marketing")
    # Purple left border
    assert "border-left:4px solid #7c3aed" in html
    # Option labels
    assert "OPTION 1" in html.upper()
    assert "OPTION 2" in html.upper()
    assert "OPTION 3" in html.upper()


def test_marketing_unsubscribe_mandatory():
    body = _load_fixture("marketing_01_three_options")
    html = render_html(body, email_type="marketing")
    assert "Unsubscribe" in html or "unsubscribe" in html
    # Must be a clickable link
    assert "href=" in html and "unsubscribe" in html.lower()


def test_marketing_term_deposit_fcs_disclaimer():
    body = _load_fixture("marketing_04_term_deposit")
    html = render_html(body, email_type="marketing")
    assert "FCS" in html or "Financial Claims Scheme" in html


def test_marketing_single_option_does_not_over_render():
    body = _load_fixture("marketing_03_single_option")
    html = render_html(body, email_type="marketing")
    # Should not accidentally show Option 2 / Option 3 from nowhere
    assert "OPTION 1" in html.upper()
    assert "OPTION 2" not in html.upper()
```

- [ ] **Step 2: Run — FAIL**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v -k marketing`
Expected: multiple FAIL.

- [ ] **Step 3: Implement marketing blocks**

Add to `backend/apps/email_engine/services/html_renderer.py`:

```python
def _extract_marketing_offers(body: str) -> list[dict]:
    """Parse 'Option N:' sections out of a marketing body.

    Each offer contains: label (e.g. 'Option 1'), title, bullets, customer_fit sentence.
    """
    lines = body.split("\n")
    offers: list[dict] = []
    current: dict | None = None
    for line in lines:
        s = line.strip()
        m = re.match(r"^Option\s+(\d+)[\s:.\-\u2013\u2014]+(.+)$", s)
        if m:
            if current:
                offers.append(current)
            current = {
                "label": f"Option {m.group(1)}",
                "title": m.group(2).strip(),
                "bullets": [],
                "fit": "",
            }
            continue
        if current is not None:
            bullet = re.match(r"^[\u2022•]\s*(.+)$", s)
            if bullet:
                current["bullets"].append(bullet.group(1))
                continue
            # Customer-fit sentence: non-bullet paragraph after bullets
            if current["bullets"] and s and not s.startswith(("Dear ", "Kind regards", "Warm regards")) \
                    and not s.startswith(("ABN", "Ph:", "Phone:", "Email:", "Unsubscribe")):
                # First non-bullet sentence after bullets is the customer-fit
                if not current["fit"]:
                    current["fit"] = s
                    continue
            # Closing/signature or next Option ends this offer
            if s.startswith(("Kind regards", "Warm regards")) or \
                    re.match(r"^Option\s+\d+", s):
                offers.append(current)
                current = None
                if re.match(r"^Option\s+\d+", s):
                    # Re-process this line as start of new offer
                    m2 = re.match(r"^Option\s+(\d+)[\s:.\-\u2013\u2014]+(.+)$", s)
                    if m2:
                        current = {
                            "label": f"Option {m2.group(1)}",
                            "title": m2.group(2).strip(),
                            "bullets": [],
                            "fit": "",
                        }
    if current:
        offers.append(current)
    return offers


def _render_offer_card(offer: dict) -> str:
    bullets_html = "".join(
        f'<div style="font-size:14px; color:#374151; padding:4px 0;">'
        f'&#8226;&nbsp;&nbsp;{b}</div>'
        for b in offer["bullets"]
    )
    fit_html = (
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["MUTED"]}; '
        f'font-style:italic; padding-top:8px; '
        f'border-top:1px solid {TOKENS["BORDER"]};">{offer["fit"]}</div>'
        if offer["fit"] else ""
    )
    return (
        f'<tr><td style="padding:12px 0;">'
        f'<table role="presentation" style="width:100%; '
        f'background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["MARKETING"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:11px; font-weight:600; '
        f'color:{TOKENS["MARKETING"]}; text-transform:uppercase; '
        f'letter-spacing:0.5px;">{offer["label"]}</div>'
        f'<div style="font-size:17px; font-weight:600; '
        f'color:{TOKENS["TEXT"]}; padding:4px 0 12px 0;">{offer["title"]}</div>'
        f'{bullets_html}'
        f'{fit_html}'
        f'</td></tr></table>'
        f'</td></tr>'
    )


def _render_marketing_footer(body: str) -> str:
    parts = []
    if "term deposit" in body.lower():
        parts.append(
            f'<div style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]}; padding:4px 0;">'
            f'Deposits are protected by the Financial Claims Scheme (FCS) up to $250,000 per account holder per ADI.</div>'
        )
    if "bonus rate" in body.lower():
        parts.append(
            f'<div style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]}; padding:4px 0;">'
            f'Bonus rates apply to eligible accounts subject to monthly deposit and transaction conditions.</div>'
        )
    # Mandatory unsubscribe (Spam Act 2003)
    # Try to extract existing unsubscribe URL; fall back to default
    m = re.search(r"Unsubscribe:\s*(\S+)", body)
    unsub_url = m.group(1) if m else "https://aussieloanai.com.au/unsubscribe"
    parts.append(
        f'<div style="padding:16px 0 0 0; border-top:1px solid {TOKENS["BORDER"]};">'
        f'<a href="{unsub_url}" '
        f'style="font-size:{TOKENS["FINE_SIZE"]}; '
        f'color:{TOKENS["BRAND_ACCENT"]}; text-decoration:underline;">Unsubscribe</a>'
        f' &nbsp;·&nbsp; '
        f'<span style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]};">'
        f'You received this email because you recently applied for a loan with AussieLoanAI.'
        f'</span>'
        f'</div>'
    )
    return "".join(parts)
```

Add marketing branch to `render_html`:
```python
elif email_type == "marketing":
    offers = _extract_marketing_offers(plain_body)

    # Strip offer blocks from body by marking lines inside Option N...
    lines = plain_body.split("\n")
    strip_idxs: set[int] = set()
    current_start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if re.match(r"^Option\s+\d+", s):
            current_start = i
        if current_start is not None:
            strip_idxs.add(i)
            # End at closing, next Option is handled by outer loop iteration
            if s.startswith(("Kind regards", "Warm regards")):
                current_start = None
                # Don't strip the closing itself
                strip_idxs.discard(i)
    working = "\n".join(ln for i, ln in enumerate(lines) if i not in strip_idxs)

    # Also strip the Unsubscribe line (we render it in the structured footer)
    working = "\n".join(
        ln for ln in working.split("\n") if not ln.strip().startswith("Unsubscribe:")
    )

    # Split signature off
    working_lines = working.split("\n")
    sig_idx = next((i for i, ln in enumerate(working_lines) if ln.strip() in CLOSINGS), None)
    top_body = "\n".join(working_lines[:sig_idx]) if sig_idx is not None else working
    sig_block = _render_signature_block(plain_body) if sig_idx is not None else ""

    legacy_top = _render_legacy_body(top_body)
    offer_html = "".join(_render_offer_card(o) for o in offers)
    cta_html = _render_cta("Call Sarah on 1300 000 000", "tel:1300000000",
                           color=TOKENS["MARKETING"])
    footer_extra = _render_marketing_footer(plain_body)

    body_html = (
        legacy_top + offer_html + cta_html + sig_block +
        f'<tr><td style="padding:0;">{footer_extra}</td></tr>'
    )
```

- [ ] **Step 4: Regenerate snapshots, assert**

```bash
rm backend/tests/fixtures/email_snapshots/marketing_*.html
cd backend && python -m pytest tests/test_html_renderer.py -v
cd backend && python -m pytest tests/test_html_renderer.py -v
```
Expected: PASS.

- [ ] **Step 5: Mirror in TS**

Port `extractMarketingOffers`, `renderOfferCard`, `renderMarketingFooter`, + the marketing branch to `frontend/src/lib/emailHtmlRenderer.ts`.

```bash
cp backend/tests/fixtures/email_snapshots/marketing_*.html frontend/src/__tests__/fixtures/email_snapshots/
cd frontend && npx vitest run src/__tests__/lib/emailHtmlRenderer.test.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/email_engine/services/html_renderer.py frontend/src/lib/emailHtmlRenderer.ts backend/tests/fixtures/email_snapshots/ frontend/src/__tests__/fixtures/email_snapshots/ backend/tests/test_html_renderer.py
git commit -m "feat(emails): marketing offer cards + mandatory unsubscribe footer"
```

---

### Task 5.3: Open PR 5

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/email-marketing-blocks
gh pr create --title "feat(emails): marketing block redesign (hero, offer cards, unsubscribe footer)" --body "$(cat <<'EOF'
## Summary
- Purple ✦ hero tile (MARKETING color)
- Offer cards (1-3 repeating) with MARKETING left border, option label, title, bullets, italic customer-fit sentence separated by divider
- Call Sarah CTA (MARKETING button color)
- **Mandatory unsubscribe** link in footer — Spam Act 2003 compliance
- Conditional FCS disclaimer (triggered by "term deposit" in body)
- Conditional bonus-rate disclaimer (triggered by "bonus rate" in body)
- 5 marketing fixtures snapshot-tested

## Test plan
- [x] `pytest backend/tests/test_html_renderer.py` — marketing tests pass including unsubscribe mandatory check
- [x] `npx vitest run` — TS parity preserved
- [x] Visual inspect: marketing_01 snapshot shows purple hero, three purple-bordered offer cards, unsubscribe in footer

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: CI green, merge, rebase master**

```bash
git checkout master && git pull origin master
```

---

## PR 6 — Playwright Visual Regression + Gmail-safe Hardening

**Branch:** `feat/email-preview-playwright` (branch from fresh master after PR 5 merge)

**Goal:** Lock down visual output with Playwright screenshot baselines for all three preview pages. Extend Gmail-safe lint to cover margin-on-td warnings, image-less rendering, and dark-mode CTA contrast. Add CI workflow running the Playwright suite.

### Task 6.1: Install Playwright

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/playwright.config.ts`

- [ ] **Step 1: Check if Playwright already installed**

Run: `cd frontend && cat package.json | grep -i playwright`
Expected: either shows `"@playwright/test"` (skip install) or nothing.

- [ ] **Step 2: Install if missing**

```bash
cd frontend && npm install --save-dev @playwright/test
cd frontend && npx playwright install --with-deps chromium
```

- [ ] **Step 3: Create playwright.config.ts**

```typescript
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  snapshotDir: './tests/e2e/__snapshots__',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: process.env.CI ? undefined : {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
```

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/playwright.config.ts
git commit -m "chore: install Playwright for email preview visual regression"
```

---

### Task 6.2: Playwright email-preview test

**Files:**
- Create: `frontend/tests/e2e/email-preview.spec.ts`

- [ ] **Step 1: Draft the test**

```typescript
import { test, expect } from '@playwright/test'

test.describe('email preview visual regression', () => {
  test('approval email renders expected structure', async ({ page }) => {
    await page.goto('/dashboard/applications/demo-approval/emails')
    await page.waitForSelector('.email-html-preview', { state: 'visible' })
    // Hero, loan card, CTA must be present
    await expect(page.locator('.email-html-preview h1')).toContainText(/Approved/i)
    await expect(page.locator('.email-html-preview')).toContainText('LOAN DETAILS')
    await expect(page.locator('.email-html-preview')).toContainText(/Review & Sign/i)
    await expect(page.locator('.email-html-preview')).toHaveScreenshot(
      'approval-body.png',
      { animations: 'disabled', maxDiffPixelRatio: 0.01 }
    )
  })

  test('denial email renders expected structure', async ({ page }) => {
    await page.goto('/dashboard/applications/demo-denial/emails')
    await page.waitForSelector('.email-html-preview', { state: 'visible' })
    await expect(page.locator('.email-html-preview')).toContainText('ASSESSMENT FACTORS')
    await expect(page.locator('.email-html-preview')).toContainText('WHAT YOU CAN DO')
    await expect(page.locator('.email-html-preview')).toContainText('FREE CREDIT REPORT')
    await expect(page.locator('.email-html-preview')).toHaveScreenshot(
      'denial-body.png',
      { animations: 'disabled', maxDiffPixelRatio: 0.01 }
    )
  })

  test('marketing email renders expected structure', async ({ page }) => {
    await page.goto('/dashboard/agents/demo-marketing')
    await page.waitForSelector('.email-html-preview, [data-testid="marketing-email"]', { state: 'visible' })
    const target = page.locator('.email-html-preview').first()
    await expect(target).toContainText(/OPTION 1/i)
    await expect(target).toContainText(/Unsubscribe/i)
    await expect(target).toHaveScreenshot(
      'marketing-body.png',
      { animations: 'disabled', maxDiffPixelRatio: 0.01 }
    )
  })
})
```

- [ ] **Step 2: Set up demo-*\*-id routes or seed data**

Check whether the dashboard has a deterministic demo/fixture route. If not, add one by seeding the backend with three fixed applications on test setup (or rely on the existing smoke-test fixtures if present). Document the seed command in `frontend/tests/e2e/README.md`:

```markdown
# E2E Setup

Before running Playwright locally:

```bash
cd backend && python manage.py loaddata tests/fixtures/playwright_demo.json
```

This seeds three deterministic applications: demo-approval, demo-denial, demo-marketing.
```

If no seed fixture exists yet, create `backend/tests/fixtures/playwright_demo.json` — a minimal Django fixture with the three LoanApplication records, their decisions, and pre-generated email bodies from the snapshot fixtures.

- [ ] **Step 3: Run locally to create baselines**

```bash
cd frontend && npm run dev  # in one terminal
cd frontend && npx playwright test --update-snapshots  # in another
```
Expected: three PNG baselines created under `frontend/tests/e2e/__snapshots__/`.

- [ ] **Step 4: Run again to assert baselines stable**

```bash
cd frontend && npx playwright test
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/e2e/ backend/tests/fixtures/playwright_demo.json
git commit -m "test(emails): Playwright visual regression for approval/denial/marketing preview"
```

---

### Task 6.3: Harden Gmail-safe lint

**Files:**
- Modify: `backend/tests/test_html_renderer.py`

- [ ] **Step 1: Add margin-on-td, <style>, and CTA dark-mode readability checks**

Append to `backend/tests/test_html_renderer.py`:
```python
def test_no_margin_on_td():
    """<td> margin is ignored by Gmail — padding only."""
    for stem in [
        "approval_01_personal", "approval_02_home_loan",
        "denial_01_serviceability", "denial_02_credit_score",
        "marketing_01_three_options", "marketing_02_two_options",
    ]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        # Regex: any <td ... style="... margin ..."> is a failure
        assert not re.search(r'<td[^>]*style="[^"]*margin', html), (
            f"{stem}: found margin on <td> — Gmail ignores this. Use padding."
        )


def test_all_urls_https_or_tel_or_mailto():
    for stem in ["approval_01_personal", "denial_01_serviceability", "marketing_01_three_options"]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        for m in re.finditer(r'href="([^"]+)"', html):
            url = m.group(1)
            assert url.startswith(("https://", "tel:", "mailto:", "#")), (
                f"{stem}: href {url} must be https, tel, mailto, or anchor"
            )


def test_no_image_tags():
    """No <img> tags — brand identity is pure CSS/unicode so images can't fail to load."""
    for stem in ["approval_01_personal", "denial_01_serviceability", "marketing_01_three_options"]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert "<img" not in html.lower(), f"{stem}: found <img> — brand is CSS-only"


def test_cta_button_has_inline_bg_and_color():
    """Dark-mode readability: button bg and color must be inline on the anchor."""
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Find all anchors
    for anchor in re.finditer(r'<a\s[^>]+>', html):
        tag = anchor.group()
        if "Review & Sign" in html[anchor.end():anchor.end() + 50] or \
                "Call Sarah" in html[anchor.end():anchor.end() + 50]:
            assert 'color:#ffffff' in tag, "CTA anchor must have inline white color"
```

- [ ] **Step 2: Run — FAIL if any issues found, fix inline until PASS**

Run: `cd backend && python -m pytest tests/test_html_renderer.py -v -k "margin or url or image or cta"`
Expected: PASS. If any fail, fix in `html_renderer.py` (most likely: a stray `margin:` on a `<td>` — change to `padding:`).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_html_renderer.py backend/apps/email_engine/services/html_renderer.py
git commit -m "test(emails): harden Gmail-safe lint (margin/td, img-free, cta contrast)"
```

---

### Task 6.4: Playwright CI workflow

**Files:**
- Create: `.github/workflows/email-preview-e2e.yml`

- [ ] **Step 1: Add workflow**

```yaml
name: email-preview-e2e

on:
  pull_request:
    paths:
      - 'backend/apps/email_engine/services/html_renderer.py'
      - 'frontend/src/lib/emailHtmlRenderer.ts'
      - 'frontend/src/components/emails/**'
      - 'frontend/src/components/agents/MarketingEmailCard.tsx'
      - 'frontend/tests/e2e/email-preview.spec.ts'
      - '.github/workflows/email-preview-e2e.yml'

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Install frontend deps
        run: |
          cd frontend
          npm ci
          npx playwright install --with-deps chromium
      - name: Install backend deps
        run: |
          cd backend
          pip install -r requirements/base.txt
      - name: Start backend (background)
        run: |
          cd backend
          python manage.py migrate --run-syncdb --noinput
          python manage.py loaddata tests/fixtures/playwright_demo.json
          python manage.py runserver 8000 &
          sleep 5
      - name: Start frontend (background)
        run: |
          cd frontend
          npm run build
          npm run start &
          sleep 10
      - name: Run Playwright
        run: |
          cd frontend
          npx playwright test
      - name: Upload Playwright report on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: frontend/playwright-report/
          retention-days: 7
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/email-preview-e2e.yml
git commit -m "ci: Playwright email-preview visual regression workflow"
```

---

### Task 6.5: Open PR 6

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/email-preview-playwright
gh pr create --title "test(emails): playwright smoke + Gmail-safe lint" --body "$(cat <<'EOF'
## Summary
- Playwright config + three visual-regression specs: approval, denial, marketing
- Hardened Gmail-safe lint: no margin on <td>, no <img> tags, all hrefs https/tel/mailto, CTA inline color
- Playwright CI workflow `email-preview-e2e.yml` with artifact upload on failure
- Deterministic demo fixtures for seeded preview pages

## Test plan
- [x] `pytest backend/tests/test_html_renderer.py` — all 30+ tests pass
- [x] `npx playwright test` — three baselines stable
- [x] Intentional margin-on-td change fails the lint
- [x] Intentional <img> addition fails the lint

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: CI green, merge, rebase master**

```bash
git checkout master && git pull origin master
```

---

## Post-ship

- [ ] Manual Gmail smoke: send one approval, one denial, one marketing email via `manage.py shell` using a real recipient (`eddie.zeng95@gmail.com`). Confirm on Gmail web + Gmail mobile + Apple Mail.
- [ ] Add memory entry `project_email_redesign_aesthetic_v2.md` with merged SHAs.
- [ ] Close issue / move changelog entry to v1.9.2 if relevant.

---
