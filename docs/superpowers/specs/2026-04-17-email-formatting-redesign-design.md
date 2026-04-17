# Email Formatting Redesign — Design Spec

**Date:** 2026-04-17
**Status:** Approved for implementation
**Scope:** (1) Approval, denial, and marketing email HTML rendering. (2) Switch email generation to template-only (skip Claude API to save cost).
**Effort estimate:** 5–7 hours (Approach A — polish `_plain_text_to_html` + template-only flag)

## Problem

Current outbound emails (approval, denial, marketing) use a functional but dated HTML rendering:

- Body text 14px — modern transactional emails use 16px
- No 600px max-width container — email stretches across screen width in desktop Gmail
- Bullet items rendered as `<p>` tags, not `<ul>/<li>` (breaks screen readers, inconsistent spacing)
- Section headers are plain `<strong>` with no visual hierarchy
- No branded header, no CTA buttons, no visual differentiation between email types
- Loan detail table has no card framing
- Attachments list is a flat row of grey pills instead of a cohesive block

**User goal:** "Use best email formatting practices… line spacing and paragraphing is not the best aesthetic… make the email look professionally formatted."

**Hard constraint:** the frontend dashboard preview (`EmailPreview`, `MarketingEmailCard`) must render exactly what Gmail shows the recipient. No divergence between inbox and preview.

## Template-only generation (cost-saving)

**Problem:** Every approval/denial/marketing email currently calls Claude API ($0.003–$0.015 per email). At scale this becomes meaningful cost and adds latency + failure modes (rate limits, timeouts, credit exhaustion).

**Solution:** Default to the existing template fallback path (`_generate_fallback` in `email_generator.py`, `_marketing_template_fallback` in `marketing_agent.py`). Templates already produce complete, guardrail-compliant plain-text bodies indistinguishable from Claude output in content. Gate Claude with a Django setting:

```python
# settings/base.py
EMAIL_USE_CLAUDE_API = env.bool("EMAIL_USE_CLAUDE_API", default=False)
```

- Default `False` → zero Claude cost for emails.
- Flip to `True` via env var if Claude output ever proves preferable.
- Template path is already covered by existing tests — no new test scaffolding needed.
- `prompt_used` field records `"[TEMPLATE — Claude disabled by config]"` when template is used by choice (vs `"[TEMPLATE FALLBACK — Claude API unavailable]"` when forced by outage). This keeps audit trails distinguishable.

**Impact:** Cost drops from ~$0.005 per email to $0. All formatting improvements below apply to both paths (template and Claude) — the HTML renderer doesn't care which path produced the plain text.

## Approach

**Approach A — polish `_plain_text_to_html` in `sender.py`.**

Reasons for picking A over B (Django templates) or C (MJML):

- Single file change (lowest blast radius)
- Zero changes to Claude prompts or plain-text output — tone, compliance, and content stay identical
- Existing plain-text markers (`SECTION_LABELS`, `OPTION_PATTERN`, `LOAN_DETAIL_RE`) already detect the content we need to style — we swap **what** each marker renders to, not **how** we detect them
- Matches stability preference — safe, reversible, tested

## Gmail-client constraints

All generated HTML must be Gmail-compatible:

- **Inline CSS only.** Gmail strips `<style>` blocks.
- **Table-based layout** for the 600px container. Flex/grid are unreliable in Gmail and Outlook.
- **`style=""` on every styled element**, no classes, no external CSS.
- Font stack: `Arial, Helvetica, sans-serif` (zero webfont risk).
- Use `background-color` inline; add `bgcolor` fallback on `<td>` elements where needed.
- Test preview against Gmail web client before claiming done.

Frontend `HtmlEmailBody` already uses DOMPurify with `ALLOWED_TAGS` including `ul`, `ol`, `li`, `table`, `tr`, `td`, `th`, `div`, `p`, `strong`, `em`, `br`, `hr`, `span`, `b`, `i`, `u`, `a`, `h1`, `h2`, `h3` and `ALLOWED_ATTR: ['style', 'href']`. No allowlist changes needed.

## Visual design system

### Container

- 600px max-width centered `<table align="center">`
- Outer page bg: `#f6f6f6`
- Inner card: `#ffffff`, `border: 1px solid #e5e7eb`, 8px border-radius
- Card padding: 32px horizontal, 24px vertical

### Typography

| Role | Size | Weight | Color | Line-height |
|------|------|--------|-------|-------------|
| Body | 16px | 400 | `#1f2937` | 1.6 |
| Section header | 18px | 700 | `#111827` | 1.3 |
| Detail label | 13px | 400 | `#6b7280` | 1.4 |
| Detail value | 15px | 700 | `#111827` | 1.4 |
| CTA text | 15px | 700 | `#ffffff` | 1 |
| Footer microcopy | 12px | 400 | `#6b7280` | 1.5 |
| AFCA/compliance | 11px | 400 | `#6b7280` | 1.5 |

### Accent colors per email type

| Type | Accent hex | Rationale |
|------|-----------|-----------|
| Approval | `#16a34a` (green) | Positive, congratulatory |
| Denial | `#374151` (slate) | Professional, not alarming — NOT red per tone preference |
| Marketing | `#7c3aed` (purple) | Matches existing `MarketingEmailCard` badge |

### Spacing scale (inline `margin` values)

- Between paragraphs: 12px
- Between sections: 28px
- Between section header and first body line: 8px
- List items: 6px vertical
- CTA button vertical margin: 24px top/bottom

## Reusable content blocks

### Block A — Branded header (shared)

```html
<table align="center" cellpadding="0" cellspacing="0" style="width:600px; max-width:100%;">
  <tr><td style="background-color: {accent_color}; height: 4px; font-size: 0; line-height: 0;">&nbsp;</td></tr>
  <tr><td style="padding: 20px 32px; background: #ffffff;">
    <table style="width:100%;"><tr>
      <td style="font-size: 18px; font-weight: bold; color: #111827;">Aussie Loan AI</td>
      <td style="text-align: right; font-size: 12px; color: #6b7280;">{timestamp}</td>
    </tr></table>
  </td></tr>
</table>
```

### Block B — Section header with accent underline

```html
<tr><td style="padding: 28px 32px 8px 32px;">
  <p style="margin: 0; font-size: 18px; font-weight: bold; color: #111827;
            border-bottom: 2px solid {accent_color}; padding-bottom: 6px;
            display: inline-block;">
    {section_label}
  </p>
</td></tr>
```

Replaces current `<p style="margin:20px 0 4px 0;"><strong>{label}</strong></p>`.

### Block C — Loan details card (replaces bare table)

```html
<tr><td style="padding: 0 32px;">
  <table style="width:100%; background:#f9fafb; border-radius:6px; padding:16px;">
    <tr>
      <td style="padding:8px 0; font-size:13px; color:#6b7280;">Loan Amount</td>
      <td style="padding:8px 0; font-size:15px; font-weight:bold; color:#111827; text-align:right;">$35,000.00</td>
    </tr>
    <!-- repeat rows, with border-bottom: 1px solid #e5e7eb except last -->
  </table>
</td></tr>
```

### Block D — Semantic list (bullet)

```html
<tr><td style="padding: 8px 32px;">
  <ul style="margin: 8px 0; padding-left: 24px;">
    <li style="margin-bottom: 6px; font-size: 16px; color: #1f2937; line-height: 1.6;">Item</li>
  </ul>
</td></tr>
```

Replaces the current `<p style="margin:2px 0 2px 16px;">•&nbsp;&nbsp;{content}</p>` hack.

### Block E — Semantic list (numbered)

Same as D with `<ol>` instead of `<ul>`. Replaces current `<p>`-with-inline-number hack for numbered documentation lists.

### Block F — Attachments card (approval only)

```html
<tr><td style="padding: 0 32px;">
  <table style="width:100%; background:#f9fafb; border-radius:6px; padding:16px;">
    <tr><td style="padding-bottom:8px; font-size:13px; color:#6b7280;">Attached documents</td></tr>
    <tr><td style="font-size:14px; color:#1f2937;">📎 &nbsp;Loan Contract.pdf</td></tr>
    <tr><td style="font-size:14px; color:#1f2937; padding-top:6px;">📎 &nbsp;Key Facts Sheet.pdf</td></tr>
    <tr><td style="font-size:14px; color:#1f2937; padding-top:6px;">📎 &nbsp;Credit Guide.pdf</td></tr>
  </table>
</td></tr>
```

### Block G — CTA button (table-based for Gmail/Outlook)

```html
<tr><td style="padding: 24px 32px; text-align: center;">
  <table cellspacing="0" cellpadding="0" style="margin: 0 auto;">
    <tr><td style="background: {accent_color}; border-radius: 6px;">
      <a href="#" style="display: inline-block; padding: 12px 28px;
                        color: #ffffff; font-size: 15px; font-weight: bold;
                        text-decoration: none;">{cta_label}</a>
    </td></tr>
  </table>
</td></tr>
```

CTA labels by type:
- Approval → "Review & Sign"
- Denial → "Explore Options"
- Marketing → "See Alternatives"

Single CTA per email — no competing buttons.

### Block H — Horizontal rule (between sections when needed)

`<hr style="border:none; border-top:1px solid #e5e7eb; margin:24px 0;">` (unchanged from current).

### Block I — Standard footer

```html
<tr><td style="padding: 24px 32px; border-top: 1px solid #e5e7eb;">
  <p style="margin:0; font-size:14px; font-weight:bold; color:#111827;">Sarah Mitchell</p>
  <p style="margin:2px 0 12px 0; font-size:13px; color:#6b7280;">Senior Lending Officer</p>
  <p style="margin:0; font-size:12px; color:#6b7280;">ABN 12 345 678 901</p>
  <p style="margin:0; font-size:12px; color:#6b7280;">Phone: 1300 LOAN AI</p>
  <p style="margin:0; font-size:12px; color:#6b7280;">Email: decisions@aussieloanai.com.au</p>
</td></tr>
```

### Block J — Compliance footer (denial only)

```html
<tr><td style="padding: 16px 32px 24px 32px; border-top: 1px solid #e5e7eb;">
  <p style="margin:0; font-size:11px; font-weight:bold; color:#6b7280;">External dispute resolution</p>
  <p style="margin:4px 0 0 0; font-size:11px; color:#6b7280;">AFCA — 1800 931 678 | afca.org.au</p>
</td></tr>
```

## Per-email-type layouts

All three share container, header, and footer. Body content differs as below.

### Approval email — accent `#16a34a`

Order:
1. Branded header (green 4px bar + "Aussie Loan AI")
2. Greeting (`Dear {name},`)
3. Opening paragraph (congratulations)
4. Section header "Loan Details" + Block C details card
5. Section header "Next Steps" + Block D bullet list
6. Block G CTA — "Review & Sign"
7. Section header "Required Documentation" + Block E numbered list
8. Block F attachments card
9. Closing ("Kind regards,")
10. Block I standard footer

### Denial email — accent `#374151`

Order:
1. Branded header (slate 4px bar)
2. Greeting
3. Opening paragraph
4. Section header "Review Factors" (was "This decision was based on…") + Block D bullet list of factors
5. Section header "What You Can Do" + Block D bullet list of actions
6. Block G CTA — "Explore Options"
7. Section header "We'd Still Like to Help" (conditional — only if NBO is attached)
8. Closing
9. Block I standard footer
10. Block J AFCA compliance footer (visually separated from main footer)

Key denial touches:
- NO red/orange anywhere — slate only
- Factors as proper bulleted list, not squashed prose
- AFCA visually separated at the bottom

### Marketing email — accent `#7c3aed`

Order:
1. Branded header (purple 4px bar + "Aussie Loan AI — Alternatives")
2. Greeting
3. Opening paragraph
4. For each NBO option:
   - Section header "Option N: {title}" + Block C details card
   - 1–2 sentence description paragraph
5. Block G CTA — "See Alternatives"
6. Closing
7. Block I standard footer (NO AFCA block)

Key marketing touches:
- Each option gets its own details card (not one flat table)
- Single CTA, not one per option

## Parsing strategy (plain-text → HTML)

`_plain_text_to_html` detects content via existing markers. We preserve detection and swap rendering:

| Marker | Current render | New render |
|--------|---------------|-----------|
| Line in `SECTION_LABELS` | `<p><strong>{label}</strong></p>` | Block B (accent underline) |
| `OPTION_PATTERN` match | `<p><strong>{label}</strong></p>` | Block B |
| Line starting with `Dear ` | `<p><strong>{line}</strong></p>` | Plain `<p>` greeting (no bold) |
| Line in `CLOSINGS` | `<p><strong>{line}</strong></p>` | Plain `<p>` closing |
| Bullet char `•` | Paragraph with `•` prefix | Block D `<li>` — collect consecutive bullets into one `<ul>` |
| Numbered list | Paragraph with `N.` prefix | Block E `<li>` — collect consecutive into one `<ol>` |
| `LOAN_DETAIL_RE` match | Row in bare `<table>` | Block C row inside styled card |
| `ABN/Phone/Email/Website` lines | Small grey paragraphs inline | Collect into Block I footer |
| Plain body text | Paragraph | Paragraph (unchanged, but 16px + better margins) |

List accumulation: walk the lines once, group consecutive bullet/numbered lines, emit a single `<ul>`/`<ol>` per group. Avoids N-separate-list bugs and matches semantic HTML expectation.

## Email-type detection

`_plain_text_to_html` currently takes only `body: str`. New signature:

```python
def _plain_text_to_html(body: str, *, email_type: Literal["approval", "denial", "marketing"] = "approval") -> str:
```

`send_decision_email(recipient_email, subject, body)` infers `email_type` from subject prefix or decision context. For safety, add an optional kwarg:

```python
def send_decision_email(recipient_email, subject, body, email_type: str = "approval"):
```

Backfill callers:
- `apps.email_engine.services.email_generator.generate_approval_email` → `email_type="approval"`
- `apps.email_engine.services.email_generator.generate_denial_email` → `email_type="denial"`
- `apps.agents.services.marketing_agent` (whoever sends) → `email_type="marketing"`

If a caller doesn't pass `email_type`, default to `"approval"` (safest — green accent is the least jarring fallback).

## Frontend changes

- `frontend/src/components/emails/EmailPreview.tsx` — no structural changes needed. DOMPurify allowlist already covers new tags.
- `frontend/src/components/agents/MarketingEmailCard.tsx` — no structural changes; already delegates to `HtmlEmailBody`.
- Verify `<ul>`, `<ol>`, `<li>` render with spacing — Tailwind's default reset may zero out `<ul>` padding. Fix via inline `style="padding-left:24px"` on `<ul>` (already in spec Block D).

## Data flow (unchanged)

```
Claude API / template fallback
   └─> plain text body (unchanged)
        └─> _plain_text_to_html(body, email_type=X)
             ├─> send via SMTP as html_message     [goes to recipient Gmail inbox]
             └─> returned in GeneratedEmail.html_body  [rendered in EmailPreview/MarketingEmailCard]
```

Same function output feeds both destinations → preview always matches inbox.

## Testing strategy

1. **Unit tests for `_plain_text_to_html`** (`backend/tests/test_email_sender.py` — create if not present):
   - Given approval plain-text fixture → HTML contains `#16a34a` accent
   - Given denial plain-text fixture → HTML contains `#374151` accent AND AFCA footer block
   - Given marketing plain-text fixture → HTML contains `#7c3aed` accent, NO AFCA footer
   - Bullet lines → single `<ul>` with multiple `<li>`
   - Numbered lines → single `<ol>` with multiple `<li>`
   - Loan detail lines → inside `<table>` with card background
   - All generated HTML uses inline `style=""` only — assert no `<style>` block or `class=`
2. **Visual smoke test**: Generate one email of each type in dev, open dashboard preview, verify by eye.
3. **Gmail test**: Run `python manage.py send_test_email` (add script if missing) against a test Gmail address, verify rendering in Gmail web + Gmail mobile.

## Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| DOMPurify strips required inline styles | Verify allowlist; `border-radius`, `background`, `padding`, `margin` all standard CSS — no allowlist change expected |
| Gmail mobile breaks 600px layout | `max-width:100%` on container ensures graceful degrade |
| Tailwind in `EmailPreview` global styles leak into preview HTML | Preview already isolated via scoped `.email-html-preview` class — verify; if leaking, add CSS reset |
| Template fallback path produces different HTML than Claude path | Both paths feed the same `_plain_text_to_html` — already identical. No divergence risk. |
| Existing tests break on HTML snapshot | Snapshots will update with new HTML. Run test suite, commit updated snapshots as part of the change. |

## Non-goals (explicit scope cuts)

- Responsive mobile breakpoints beyond `max-width: 100%`
- Dark mode support
- Outlook-specific VML fallbacks
- Email A/B testing framework
- Unsubscribe link (not requested, not required for transactional/approval mail)
- Unicode emoji rendering tests across clients (📎 degrades to filename-only cleanly)

## Files touched

| File | Change type | Est. lines |
|------|-------------|-----------|
| `backend/apps/email_engine/services/sender.py` | Rewrite `_plain_text_to_html`, add `email_type` kwarg | +~220, -~100 |
| `backend/apps/email_engine/services/email_generator.py` | Gate Claude with `EMAIL_USE_CLAUDE_API`; always use template if off | +~10 |
| `backend/apps/agents/services/marketing_agent.py` | Gate Claude the same way | +~10 |
| `backend/config/settings/base.py` | Add `EMAIL_USE_CLAUDE_API = env.bool(..., default=False)` | +1 |
| `backend/apps/email_engine/services/lifecycle.py` | Pass `email_type` to `send_decision_email` | +1 |
| `backend/apps/email_engine/tasks.py` | Pass `email_type` | +1 |
| `backend/apps/email_engine/views.py` | Pass `email_type` | +1 |
| `backend/apps/agents/services/email_pipeline.py` | Pass `email_type` | +1 |
| `backend/apps/agents/services/marketing_pipeline.py` | Pass `email_type="marketing"` | +1 |
| `backend/apps/agents/services/human_review_handler.py` | Pass `email_type` | +1 |
| `backend/tests/test_email_sender.py` | New tests | +~150 |
| `backend/tests/test_email_generator.py` | Add test for `EMAIL_USE_CLAUDE_API=False` path | +~20 |
| `frontend/src/components/emails/EmailPreview.tsx` | No change (verify only) | 0 |
| `frontend/src/components/agents/MarketingEmailCard.tsx` | No change (verify only) | 0 |

**Total: ~1 backend file rewritten, 6 call sites touched, ~170 lines of tests, 1 settings flag.**

## Success criteria

1. `pytest backend/tests/test_email_sender.py` passes with new tests
2. Full `pytest` suite passes (existing tests may need HTML snapshot updates)
3. With `EMAIL_USE_CLAUDE_API=False` (default), `EmailGenerator.generate()` never calls `self.client.messages.create` — verified by a test that asserts `client.messages.create` is not called
4. Frontend dev preview (`/dashboard` → sample email) shows new layout
5. Actual Gmail web inbox renders the same layout (visual parity with preview)
6. No new exceptions in backend logs
7. Existing email send still works (SMTP unchanged)
8. Flipping `EMAIL_USE_CLAUDE_API=True` still works — Claude path is not removed, just gated
