# Email Redesign — Spacing, Hierarchy, Professional Aesthetics

**Date:** 2026-04-17
**Status:** Approved; implementation pending
**Author:** Claude (brainstormed with Neville Zeng)

## Context

The loan-approval product sends three email types to customers: approval, denial, and marketing follow-up. The plain-text content is already thoughtfully written (Sarah Mitchell tone, Banking Code compliance, Kahneman framing). What is weak is **presentation**:

1. **Inconsistent rendering** — the backend renders emails through `backend/apps/email_engine/services/sender.py::_plain_text_to_html()` (table-aware, section-label bolding, signature styling). The frontend dashboard renders the same plain text through a **simpler** converter (paragraph splits on blank lines + `<br>` on single newlines) that does not reproduce the backend's tables, signature treatment, or section spacing. The dashboard preview therefore does not match what the Gmail recipient actually sees — violating the existing memory rule `feedback_email_gmail_preview`.
2. **No brand identity** — emails are monochrome Arial 14/1.6 on `#333`. There is no AussieLoanAI wordmark, brand color, or visual anchor. The tokens are already defined in `frontend/src/app/globals.css` (primary `#3b82f6`, navy `#1e40af`) but the email renderer never references them.
3. **Flat hierarchy** — every section label (e.g. `Loan Details:`, `Before You Sign:`) renders identically: bold paragraph with `margin:20px 0 4px 0`. The approval hero ("your loan is approved") looks the same as the comparison-rate footnote. A reader scanning the email has nothing to anchor on.
4. **No CTA buttons** — action steps like "sign and return by [date]" are buried in numbered paragraph text. Real bank emails surface actions as bulletproof buttons.
5. **Signature collapse** — Sarah Mitchell's block runs straight into body text. There is no divider, no credential separation, and the ABN / phone / email lines render as dim 12px gray text jammed together.
6. **Marketing "Option" blocks** look like regular paragraphs** — no card structure, no accent color, no visual separation between offers.

## Goals

- Produce visually professional emails matching the polish of modern Australian banks (ANZ, Westpac, CBA) and clean fintech transactional design (Monzo, Starling).
- Unify backend and frontend rendering so the dashboard preview is byte-for-byte the HTML the Gmail recipient receives.
- Establish reusable design tokens (colors, type scale, spacing scale) that live in one place and mirror between Python and TypeScript.
- Ship atomically across 6 small PRs, each independently reviewable and reversible.
- Stay within Gmail-safe HTML constraints (inline CSS, table layout, no flexbox/grid, ≤102 KB).

## Non-Goals

- Restructuring email **content** — wording, Banking Code compliance rules, guardrail checks, Sarah Mitchell tone all stay exactly as they are today.
- Migration to a templating library (MJML, Maizzle, React Email) — we stay with plain-text-first + Python renderer, because it is simple and the guardrail system already operates on the plain text.
- Dark-mode perfection — we include a single `@media (prefers-color-scheme: dark)` override for CTA readability, but we do not build a full dark theme.
- Outlook desktop fidelity — we test Gmail web + Gmail mobile app + Apple Mail. Outlook ≥ 2016 must render readably but not necessarily identically.
- Accessibility audit beyond WCAG AA contrast on the tokens.
- Internationalization / RTL.

## Architecture

### Renderer unification

A new module `backend/apps/email_engine/services/html_renderer.py` becomes the single source of truth:

```python
def render_html(plain_body: str, email_type: Literal["approval", "denial", "marketing"]) -> str:
    """Convert plain-text email body into Gmail-safe HTML for delivery and dashboard preview."""
```

- `backend/apps/email_engine/services/sender.py` deletes its local `_plain_text_to_html()` and imports from `html_renderer`.
- A TypeScript mirror `frontend/src/lib/emailHtmlRenderer.ts` exports `renderEmailHtml(body: string, type: EmailType): string` with identical logic.
- `frontend/src/components/emails/EmailPreview.tsx` and `frontend/src/components/agents/MarketingEmailCard.tsx` delete their local `plainTextToHtml` and import from `emailHtmlRenderer`. DOMPurify sanitization stays — the renderer output is treated as untrusted HTML for defense in depth (this is also why PR-D3 from Track D will land first).
- A parity test in CI: for each of 15 fixture bodies (5 per type), Python and TS must produce identical HTML strings (normalized for trivial whitespace).

### Design tokens

Tokens live in `backend/apps/email_engine/services/html_renderer.py` as a top-level `TOKENS: dict[str, str]` and mirror in `frontend/src/lib/emailHtmlRenderer.ts` as a `TOKENS` const. The TS port is copy-pasted verbatim; CI parity test compares the dicts.

| Token | Value | Use |
|---|---|---|
| `BRAND_PRIMARY` | `#1e40af` | Header bar background, primary section accents |
| `BRAND_ACCENT` | `#3b82f6` | CTA button backgrounds, key-value labels |
| `SUCCESS` | `#16a34a` | Approval hero icon + left-border of loan-details card |
| `CAUTION` | `#d97706` | Denial hero icon + assessment-factors card left border (muted amber, not red — a denial is not a failure) |
| `MARKETING` | `#7c3aed` | Marketing hero icon + offer-card left border |
| `TEXT` | `#111827` | Body copy |
| `MUTED` | `#6b7280` | Section labels, key cells in loan-detail tables |
| `FINE` | `#9ca3af` | 12px footers, regulatory fine print |
| `CARD_BG` | `#f8fafc` | Tint on loan-details / offer / assessment cards |
| `BORDER` | `#e5e7eb` | 1px row dividers |
| `PAGE_BG` | `#f3f4f6` | Outer table background |
| `FONT_STACK` | `system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif` | Everywhere |
| `BODY_SIZE` | `15px` | Body copy (up from 14, per 2026 best practices) |
| `HEAD_SIZE` | `22px` | Hero H1 |
| `LABEL_SIZE` | `13px` | Section labels (uppercase letter-spacing treatment) |
| `FINE_SIZE` | `12px` | Footer |
| `LINE_HEIGHT` | `1.6` | All body text |
| `MAX_WIDTH` | `600px` | Inner container |
| Spacing scale | 4 / 8 / 12 / 16 / 24 / 32 / 48 px | Padding on `<td>`, never margin |

### Shared skeleton

Every email, regardless of type, renders into this skeleton:

```
<!-- Outer wrapper: full-width background -->
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="width:100%; background-color:#f3f4f6; margin:0; padding:0;">
  <tr><td style="padding:32px 16px;">
    <!-- Inner container: 600px centered white card -->
    <table role="presentation" cellpadding="0" cellspacing="0" border="0"
           style="width:100%; max-width:600px; margin:0 auto; background-color:#ffffff;
                  border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">

      <!-- Header bar: brand primary color, 48px tall, wordmark -->
      <tr><td style="background-color:#1e40af; padding:16px 24px; border-radius:8px 8px 0 0;">
        <span style="color:#ffffff; font-size:16px; font-weight:600; letter-spacing:0.3px;">
          AussieLoanAI
        </span>
        <span style="color:#bfdbfe; font-size:12px; margin-left:8px;">
          Australian Credit Licence No. 012345
        </span>
      </td></tr>

      <!-- Decision hero: type-specific icon + headline + subtitle -->
      <tr><td style="padding:32px 24px 16px 24px; text-align:left;">
        <div style="font-size:32px; line-height:1;">{HERO_ICON}</div>
        <h1 style="font-size:22px; line-height:28px; color:#111827; margin:12px 0 4px 0;">
          {HERO_HEADLINE}
        </h1>
        <div style="font-size:13px; color:#6b7280;">{HERO_SUBTITLE}</div>
      </td></tr>

      <!-- Greeting -->
      <tr><td style="padding:16px 24px 0 24px; font-size:15px; color:#111827;">
        Dear {first_name},
      </td></tr>

      <!-- Body blocks (per email type) -->
      {BODY_BLOCKS}

      <!-- Signature block with top divider -->
      <tr><td style="padding:24px 24px 0 24px;
                     border-top:1px solid #e5e7eb;">
        {SIGNATURE}
      </td></tr>

      <!-- Footer: fine print -->
      <tr><td style="padding:24px; background-color:#f8fafc;
                     border-radius:0 0 8px 8px;">
        {FOOTER}
      </td></tr>

    </table>
  </td></tr>
</table>
```

## Per-Type Blocks

### Approval email

**Hero:**
- Icon: `&#10003;` (U+2713 ✓) wrapped in a 48×48 rounded-full tile with `SUCCESS` background color, white glyph. (Unicode check ensures graceful fallback to a plain check char on clients that strip images; no image assets needed.)
- Headline: "Your {Loan Type} Loan Is Approved"
- Subtitle: "Congratulations, {first_name}!"

**Body blocks (in order):**

1. **Intro paragraph** — `padding:12px 24px;`, renders the "We are pleased to advise…" line.

2. **Loan Details card:**
   ```
   <tr><td style="padding:16px 24px;">
     <table role="presentation" style="width:100%; background-color:#f8fafc;
            border-left:4px solid #16a34a; border-radius:4px;
            border-collapse:separate; border-spacing:0;">
       <tr><td style="padding:16px 20px;">
         <div style="font-size:13px; font-weight:600; color:#1e40af;
                     text-transform:uppercase; letter-spacing:0.5px; padding-bottom:8px;">
           Loan Details
         </div>
         <!-- key/value rows with 1px #e5e7eb bottom borders between them -->
         <table role="presentation" style="width:100%;">
           <tr>
             <td style="padding:8px 0; font-size:14px; color:#6b7280;
                        border-bottom:1px solid #e5e7eb;">Loan Amount</td>
             <td style="padding:8px 0; font-size:14px; color:#111827; font-weight:600;
                        text-align:right; border-bottom:1px solid #e5e7eb;">$50,000.00</td>
           </tr>
           <!-- further rows: Interest Rate, Comparison Rate, Loan Term, Monthly Repayment,
                Establishment Fee, First Repayment Date -->
         </table>
       </td></tr>
     </table>
   </td></tr>
   ```
   The renderer detects the existing `  Label:           Value` indented format (already produced by the prompt) and transforms it into this card.

3. **Next Steps** — H-labeled block with numbered pills:
   ```
   <div>Next Steps</div>
   <!-- for each step -->
   <table><tr>
     <td style="width:28px; padding:0; vertical-align:top;">
       <div style="width:24px; height:24px; border-radius:50%;
                   background-color:#1e40af; color:#ffffff;
                   font-size:12px; font-weight:600; line-height:24px;
                   text-align:center;">1</div>
     </td>
     <td style="padding:0 0 12px 12px; font-size:15px; color:#111827;">
       Sign and return your documents by 17 May 2026…
     </td>
   </tr></table>
   ```

4. **CTA button row:** one bulletproof button, center-aligned:
   ```
   <tr><td align="center" style="padding:24px;">
     <table role="presentation" cellspacing="0" cellpadding="0">
       <tr><td style="background-color:#3b82f6; border-radius:6px;">
         <a href="https://portal.aussieloanai.com.au/sign" target="_blank"
            style="display:inline-block; padding:12px 28px; color:#ffffff;
                   font-size:15px; font-weight:600; text-decoration:none;">
           Sign & Return Documents
         </a>
       </td></tr>
     </table>
   </td></tr>
   ```

5. **Required Documentation** — bullet list inside a muted card.

6. **Before You Sign / We're Here For You** — plain body blocks with section labels styled as uppercase 13px letter-spaced muted text (not bold paragraphs as today).

7. **Attachments chip row:**
   ```
   <tr><td style="padding:16px 24px;">
     <div style="font-size:13px; font-weight:600; color:#6b7280;
                 text-transform:uppercase; letter-spacing:0.5px; padding-bottom:8px;">
       Attachments
     </div>
     <table role="presentation"><tr>
       <td style="padding:6px 12px; background-color:#f3f4f6;
                  border:1px solid #e5e7eb; border-radius:4px;
                  font-size:13px; color:#374151;">
         📎 Loan Contract.pdf
       </td>
       <td style="width:8px;"></td>
       <!-- Key Facts Sheet.pdf, Credit Guide.pdf chips -->
     </tr></table>
   </td></tr>
   ```

8. **Signature:**
   ```
   <div style="font-size:15px; color:#111827;">Kind regards,</div>
   <div style="font-size:15px; color:#111827; font-weight:600; padding-top:8px;">
     Sarah Mitchell
   </div>
   <div style="font-size:13px; color:#6b7280;">Senior Lending Officer</div>
   <div style="font-size:13px; color:#6b7280;">AussieLoanAI Pty Ltd</div>
   <div style="font-size:12px; color:#9ca3af; padding-top:8px;">
     ABN 12 345 678 901 · ACL 012345
   </div>
   <div style="font-size:12px; color:#9ca3af;">
     <a href="tel:1300000000" style="color:#9ca3af;">1300 000 000</a> ·
     <a href="mailto:aussieloanai@gmail.com" style="color:#9ca3af;">aussieloanai@gmail.com</a>
   </div>
   ```

9. **Footer:**
   - 1px `BORDER` horizontal rule
   - Comparison rate warning: 12px `FINE` italic
   - AFCA / validity / confidentiality: 12px `FINE`
   - No unsubscribe (transactional email, not required)

### Denial email

**Hero:**
- Icon: `&#9432;` (U+24B8 Ⓘ) on 48×48 rounded-full tile with `CAUTION` background. Subtle, dignified — not red, not alarmed.
- Headline: "Update on Your Application"
- Subtitle: "Ref #{reference_number}"

**Body blocks:**

1. **Intro paragraph** — "Thank you for giving us the opportunity…"

2. **Decision + transition paragraph** — "We have carefully reviewed…"

3. **Assessment Factors card:**
   - `CARD_BG` background, `CAUTION` 4px left border
   - Uppercase label "Assessment Factors"
   - Each factor: bold 14px label + 14px body explanation
   - 12px vertical padding per factor, 1px `BORDER` divider between factors

4. **Responsible lending one-liner** — plain paragraph.

5. **What You Can Do card:**
   - `CARD_BG` background, `SUCCESS` 4px left border (green because it is forward-looking)
   - Uppercase label "What You Can Do"
   - Intro sentence then bulleted improvement steps

6. **Credit Report card:**
   - `CARD_BG` background, `BRAND_ACCENT` 4px left border
   - Uppercase label "Free Credit Report"
   - Intro sentence then three bureau rows, each with name + clickable URL:
     ```
     <tr><td>
       <strong>Equifax</strong> — <a href="https://equifax.com.au"
       style="color:#3b82f6;">equifax.com.au</a>
     </td></tr>
     ```

7. **CTA row:** two actions —
   - Primary button: "Call Sarah on 1300 000 000" (`BRAND_ACCENT` bg, `tel:` href)
   - Secondary text link: "Or reply to this email"

8. **"We'd Still Like to Help" paragraph.**

9. **Closing paragraph** — "Thanks for coming to us, {first_name}…"

10. **Signature** — same structure as approval.

11. **Footer:**
    - 1px `BORDER` horizontal rule
    - AFCA block with contact details
    - Confidentiality notice
    - No attachments (none sent)
    - No unsubscribe (transactional)

### Marketing email

**Hero:**
- Icon: `&#10022;` (U+2726 ✦) on 48×48 rounded-full tile with `MARKETING` background (purple).
- Headline: "A Few Options for You"
- Subtitle: "Following your recent application"

**Body blocks:**

1. **Intro paragraph.**

2. **Offer cards** (1–3, repeating template):
   ```
   <tr><td style="padding:12px 24px;">
     <table role="presentation" style="width:100%; background-color:#f8fafc;
            border-left:4px solid #7c3aed; border-radius:4px;">
       <tr><td style="padding:16px 20px;">
         <div style="font-size:11px; font-weight:600; color:#7c3aed;
                     text-transform:uppercase; letter-spacing:0.5px;">
           Option 1
         </div>
         <div style="font-size:17px; font-weight:600; color:#111827;
                     padding:4px 0 12px 0;">
           Smaller Personal Loan
         </div>
         <!-- bullet benefits -->
         <div style="font-size:14px; color:#374151; padding-bottom:8px;">
           • <strong>Lower monthly repayments:</strong> A $15,000 loan at…
         </div>
         <!-- customer-fit sentence -->
         <div style="font-size:13px; color:#6b7280; font-style:italic;
                     padding-top:8px; border-top:1px solid #e5e7eb;">
           With $12,000 in savings, this smaller amount sits comfortably…
         </div>
       </td></tr>
     </table>
   </td></tr>
   ```

3. **CTA button** — "Call Sarah on 1300 000 000".

4. **Closing paragraph.**

5. **Signature** — same structure as others.

6. **Footer** — the marketing footer is the **longest** of the three and requires the most care:
   - FCS disclaimer (conditional on term-deposit presence)
   - Bonus-rate disclaimer (conditional)
   - "Interest rates current as at DD/MM/YYYY" line
   - TMD/PDS disclaimer
   - **Unsubscribe link** — rendered prominently as 12px underlined `BRAND_ACCENT` color, **mandatory** for marketing emails (Spam Act 2003).

## Dashboard Preview Parity

The `EmailPreview.tsx` outer Gmail-chrome (sender row, subject bar, attachment chips, reply/forward row) stays as today — it is the *dashboard's* framing, not the email. What changes: the inner `<HtmlEmailBody>` component stops using its local `plainTextToHtml` and instead calls `renderEmailHtml(email.body, email.decision)` imported from `frontend/src/lib/emailHtmlRenderer.ts`. Same for `MarketingEmailCard.tsx` (which passes `'marketing'` as the type).

DOMPurify sanitization of the rendered HTML stays. Per-attribute allowlist stays. This is defense in depth — even though we trust our own renderer, we still sanitize because the plain-text input comes from user-sourced fields through Claude-generated output.

## Testing Strategy

### Unit tests

- `backend/apps/email_engine/tests/test_html_renderer.py` — new file:
  - 5 approval fixtures (varying loan types, co-signer, conditions)
  - 5 denial fixtures (varying reason sets, bureau references)
  - 5 marketing fixtures (1, 2, 3 offers; term-deposit / non-term-deposit)
  - Each fixture asserts: output contains `BRAND_PRIMARY` header, hero icon HTML entity, type-specific accent color, signature block, footer
  - Snapshot of rendered HTML string (Pytest `snapshot` or explicit golden file)

- `frontend/src/__tests__/lib/emailHtmlRenderer.test.ts` — new file:
  - Same 15 fixtures
  - Snapshot output matches Python snapshots byte-for-byte (normalized whitespace)

### Parity CI check

A pytest+vitest combined step runs both suites and diffs the golden files. Any divergence fails CI.

### Visual regression

Add a Playwright test at `frontend/tests/e2e/email-preview.spec.ts`:
- Create 3 fixture applications (approved, denied, marketing-followed)
- Navigate to their preview page in the dashboard
- Assert presence of `[data-section="hero"]`, `[data-section="loan-details"]`, `[data-section="signature"]`, `[data-section="footer"]` selectors
- Take screenshot, compare against baseline (Playwright's `toMatchSnapshot`)

### Gmail-safe lint

A Python check in `backend/apps/email_engine/tests/test_html_renderer.py`:
- Rendered HTML must not contain `display:flex`, `display:grid`, `display:inline-flex`
- Must not contain any `<style>` tags
- Max-width attribute on inner table must be `600px`
- All `margin:` uses must be on outer spacing rows only (property regex scan)

### Manual Gmail smoke

After each PR, send 1 real email of the affected type to `eddie.zeng95@gmail.com` via Gmail SMTP (EMAIL_USE_CLAUDE_API=false to skip paid API, template fallback produces comparable plain-text body). Visually inspect in Gmail web + Gmail mobile app + Apple Mail.

## Atomic PR Breakdown

Each PR is independently reviewable and reversible. Ordering runs foundation-first, then per-type, then tests.

| # | Title | Scope | Effort |
|---|---|---|---|
| 1 | `feat(emails): shared html_renderer + design tokens` | New `backend/apps/email_engine/services/html_renderer.py` with `TOKENS`, `render_html()`, shared skeleton. `sender.py` rewired to use it. Backend tests for skeleton only (no per-type blocks yet — renderer returns the old output wrapped in the new skeleton as an intermediate step). | ~2h |
| 2 | `feat(emails): typescript renderer port + dashboard swap` | New `frontend/src/lib/emailHtmlRenderer.ts` mirroring the Python renderer. `EmailPreview.tsx` + `MarketingEmailCard.tsx` swap to the shared TS renderer. Parity test added. | ~1.5h |
| 3 | `feat(emails): approval block redesign (hero, loan-card, cta, signature, attachments)` | Implement all approval-specific blocks in both renderers. Test fixtures added. | ~1h |
| 4 | `feat(emails): denial block redesign (hero, factor cards, bureau card, dual cta)` | Denial-specific blocks in both renderers. | ~1h |
| 5 | `feat(emails): marketing block redesign (hero, offer cards, unsubscribe footer)` | Marketing-specific blocks + conditional disclaimer renderer. | ~1h |
| 6 | `test(emails): playwright smoke + gmail-safe lint` | Playwright visual-regression baseline. Gmail-safe property lint. Snapshot parity CI gate. | ~1h |

Total ~7.5h. Sequenced — each PR merges green before the next branches.

## Out of Scope

- Localization or RTL support.
- Email client coverage beyond Gmail (web + mobile app), Apple Mail, Outlook 2016+ readable (not pixel-identical).
- Full dark-mode theme; only a CTA-readability override.
- Replacing the plain-text-first pipeline with an HTML-first system (MJML, React Email).
- Changing email **content** — wording, Banking Code compliance rules, Sarah Mitchell tone.
- Brand logo asset (SVG/PNG) — we use a CSS-styled wordmark instead.
- Unsubscribe-endpoint backend wiring — the existing `/api/marketing/unsubscribe/` URL is linked; no backend changes in this track.
- Email A/B testing infrastructure.
- Paid email-testing service integration (Litmus, Email on Acid) — covered by Playwright snapshots + manual Gmail smoke instead.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Unicode icons (✓ ⓘ ✦ 📎) render as tofu in Outlook / some Android clients | Wrap icons in `<span>` with ASCII fallback (e.g. `[Approved]`) hidden by default via VML conditional comments. If that is too complex, accept Outlook degradation — we state Outlook is "readable not pixel-identical" in goals. |
| Bulletproof CTA button invisible in Gmail dark mode (white text on white bg if button bg is stripped) | Add `@media (prefers-color-scheme: dark)` override setting button `background-color:#3b82f6 !important;` and `color:#ffffff !important;`. Also wrap the button in an outer `<div>` with the same brand bg for belt-and-braces. |
| TypeScript port drifts from Python port over time | Dedicated CI step runs `pytest --snapshot` + `vitest --snapshot` and diffs golden HTML files. Any divergence fails the build. |
| Deleting old `plainTextToHtml` breaks existing dashboard tests | PR-2 updates all impacted tests as part of the swap. Grep for `plainTextToHtml` pre-merge to catch stragglers. |
| `_plain_text_to_html` detects loan-detail rows by regex `^(\s{2,})(\S[^:]+:)\s+(.+)$` — prompt wording could drift and miss the regex | Snapshot tests capture this; drift shows as unformatted rows and fails the snapshot. Also add a test that inserts a deliberately-misformatted line and asserts renderer does not crash (graceful degradation to a plain paragraph). |
| Gmail clips emails > 102 KB | Per-type token budget: approval + attachments stays under 40 KB; denial under 25 KB; marketing with 3 offers under 35 KB. Snapshot test asserts size. |
| Playwright snapshots flaky due to rendering timing | Use `toHaveScreenshot` with `animations: 'disabled'` and `fullPage: false`. Snapshot only the email card, not the full dashboard. |
| "Call Sarah" CTA tel-link on desktop web Gmail does nothing | Provide both CTA button + text "Prefer to email? Reply to this message" — desktop users have a fallback. |

## Success Criteria

- Dashboard preview HTML === Gmail recipient HTML for all 15 test fixtures (parity CI gate passes).
- All 3 email types render with: brand header, colored hero, cards where specified, CTA button, divided signature, styled footer.
- Manual Gmail smoke for each type shows: correct hero color, readable on mobile, tappable CTA, signature block separated.
- All existing email tests still pass.
- Playwright visual-regression baseline captured and green.
- 6 PRs merged sequentially; no PR reverted.
- Memory entry `project_email_redesign_aesthetic_v2` added with merged SHAs.

## Handoff

This spec is ready for the writing-plans skill. The plan will decompose each of the 6 PRs into TDD steps with exact file paths, test code, and commit commands — readable by an engineer with zero context on this codebase.
