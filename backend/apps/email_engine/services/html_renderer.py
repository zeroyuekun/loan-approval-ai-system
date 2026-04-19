"""Unified plain-text → Gmail-safe HTML renderer for decision + marketing emails.

Single source of truth for all three email types. Design tokens (colors, type
scale, spacing) live here and mirror verbatim in frontend/src/lib/emailHtmlRenderer.ts.
A CI snapshot parity test fails if the two drift.

See: docs/superpowers/specs/2026-04-17-email-redesign-design.md
"""

import re
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
APPROVAL_LOAN_TYPE_RE = re.compile(r"application for an? ([A-Z][A-Za-z]+ Loan)")

HERO_CONFIG: dict[str, dict[str, str]] = {
    "approval": {
        "icon": "&#10003;",
        "color": TOKENS["SUCCESS"],
        "default_headline": "Your Loan Is Approved",
    },
    "denial": {
        "icon": "&#9432;",
        "color": TOKENS["CAUTION"],
        "default_headline": "Update on Your Application",
    },
    "marketing": {
        "icon": "&#10022;",
        "color": TOKENS["MARKETING"],
        "default_headline": "A Few Options for You",
    },
}


def _extract_applicant_name(body: str) -> str:
    for line in body.split("\n")[:5]:
        s = line.strip()
        if s.startswith("Dear "):
            rest = s[5:].rstrip(",").strip()
            if not rest:
                return "there"
            return rest.split()[0]
    return "there"


def _extract_approval_loan_type(body: str) -> str:
    m = APPROVAL_LOAN_TYPE_RE.search(body)
    return m.group(1) if m else "Loan"


def _extract_loan_details(body: str) -> tuple[list[tuple[str, str]], int, int]:
    """Find the 'Loan Details:' block. Return (rows, start_idx, end_idx).

    Block starts at "Loan Details:" line and ends at the last indented label:value row
    before a non-matching line. Returns ([], -1, -1) if no block found.
    """
    lines = body.split("\n")
    start = -1
    end = -1
    rows: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        if start == -1:
            if line.strip() == "Loan Details:":
                start = i
                end = i
            continue
        m = LOAN_DETAIL_RE.match(line)
        if m:
            rows.append((m.group(2).rstrip(":").strip(), m.group(3).strip()))
            end = i
            continue
        if line.strip() == "":
            continue
        break
    return rows, start, end


def _render_loan_details_card(rows: list[tuple[str, str]]) -> str:
    row_html = ""
    for i, (label, value) in enumerate(rows):
        is_last = i == len(rows) - 1
        border = "" if is_last else f"border-bottom:1px solid {TOKENS['BORDER']};"
        row_html += (
            f"<tr>"
            f'<td style="padding:8px 0; font-size:14px; color:{TOKENS["MUTED"]}; {border}">{label}</td>'
            f'<td style="padding:8px 0; font-size:14px; color:{TOKENS["TEXT"]}; '
            f'font-weight:600; text-align:right; {border}">{value}</td>'
            f"</tr>"
        )
    return (
        f'<div style="margin:16px 0;">'
        f'<table role="presentation" style="width:100%; background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["SUCCESS"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f"color:{TOKENS['BRAND_PRIMARY']}; text-transform:uppercase; "
        f'letter-spacing:0.5px; padding-bottom:8px;">Loan Details</div>'
        f'<table role="presentation" style="width:100%;">{row_html}</table>'
        f"</td></tr></table>"
        f"</div>"
    )


NUMBERED_STEP_RE = re.compile(r"^\s+(\d+)\.\s+(.+)$")
HR_RE = re.compile(r"^[\u2500\u2501\-]{5,}$")


def _extract_numbered_steps(body: str, section_label: str) -> tuple[list[str], int, int]:
    """Find a section like 'Next Steps:' followed by indented numbered steps.

    The numbered list may be preceded by intro paragraphs. Indices span from
    the section label through the last numbered step.
    """
    lines = body.split("\n")
    start = -1
    last_num = -1
    steps: list[str] = []
    for i, line in enumerate(lines):
        if start == -1:
            if line.strip() == section_label:
                start = i
            continue
        m = NUMBERED_STEP_RE.match(line)
        if m:
            steps.append(m.group(2).strip())
            last_num = i
            continue
        if steps and line.strip() == "":
            continue
        if steps and line.strip() != "":
            break
    return steps, start, last_num


def _render_next_steps_block(steps: list[str]) -> str:
    rows = ""
    for i, text in enumerate(steps, start=1):
        rows += (
            f"<tr>"
            f'<td style="width:28px; padding:0 0 12px 0; vertical-align:top;">'
            f'<div style="width:24px; height:24px; border-radius:12px; '
            f"background-color:{TOKENS['BRAND_PRIMARY']}; color:#ffffff; "
            f'font-size:12px; font-weight:600; line-height:24px; text-align:center;">{i}</div>'
            f"</td>"
            f'<td style="padding:0 0 12px 12px; font-size:{TOKENS["BODY_SIZE"]}; '
            f'color:{TOKENS["TEXT"]};">{text}</td>'
            f"</tr>"
        )
    return (
        f'<div style="padding:8px 0 16px 0;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f"color:{TOKENS['MUTED']}; text-transform:uppercase; letter-spacing:0.5px; "
        f'padding-bottom:12px;">Next Steps</div>'
        f'<table role="presentation" style="width:100%;">{rows}</table>'
        f"</div>"
    )


def _render_cta(text: str, href: str, color: str | None = None) -> str:
    bg = color or TOKENS["BRAND_ACCENT"]
    return (
        f'<div style="padding:8px 0 24px 0; text-align:center;">'
        f'<table role="presentation" cellspacing="0" cellpadding="0" '
        f'style="margin:0 auto;">'
        f'<tr><td style="background-color:{bg}; border-radius:6px;">'
        f'<a href="{href}" target="_blank" '
        f'style="display:inline-block; padding:12px 28px; color:#ffffff; '
        f"font-size:{TOKENS['BODY_SIZE']}; font-weight:600; "
        f'text-decoration:none;">{text}</a>'
        f"</td></tr></table>"
        f"</div>"
    )


def _render_attachments_chips(names: list[str]) -> str:
    if not names:
        return ""
    chips = '<td style="width:8px;"></td>'.join(
        f'<td style="padding:6px 12px; background-color:{TOKENS["PAGE_BG"]}; '
        f"border:1px solid {TOKENS['BORDER']}; border-radius:4px; "
        f'font-size:{TOKENS["LABEL_SIZE"]}; color:#374151;">&#128206; {n}</td>'
        for n in names
    )
    return (
        f'<div style="padding:8px 0 16px 0;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f"color:{TOKENS['MUTED']}; text-transform:uppercase; letter-spacing:0.5px; "
        f'padding-bottom:8px;">Attachments</div>'
        f'<table role="presentation"><tr>{chips}</tr></table>'
        f"</div>"
    )


def _split_at_signature(body: str) -> tuple[str, list[str], str]:
    """Split body into (pre_signature, signature_lines, post_signature).

    Signature spans from the 'Kind regards,'/'Warm regards,' line to the first
    horizontal-rule divider after it (exclusive). Post-signature (HR + fine
    print) returns as its own string for legacy rendering.
    """
    lines = body.split("\n")
    sig_start = next((i for i, ln in enumerate(lines) if ln.strip() in CLOSINGS), -1)
    if sig_start == -1:
        return body, [], ""
    sig_end = len(lines)
    for j in range(sig_start + 1, len(lines)):
        if HR_RE.match(lines[j].strip()):
            sig_end = j
            break
    pre = "\n".join(lines[:sig_start])
    sig = lines[sig_start:sig_end]
    post = "\n".join(lines[sig_end:])
    return pre, sig, post


def _render_signature_block(sig_lines: list[str]) -> str:
    """Render closing + name/title/company + contact lines with top divider.

    sig_lines[0] is the closing ('Kind regards,'). Subsequent non-blank lines
    are name, title, company, then contact lines (ABN/Ph/Email/Website).
    """
    if not sig_lines:
        return ""
    closing = sig_lines[0].strip()
    non_blank = [ln.strip() for ln in sig_lines[1:] if ln.strip()]
    name = non_blank[0] if len(non_blank) > 0 else ""
    title = non_blank[1] if len(non_blank) > 1 else ""
    company = non_blank[2] if len(non_blank) > 2 else ""
    contact = [ln for ln in non_blank[3:] if ln.startswith(("ABN ", "Ph:", "Phone:", "Email:", "Website:"))]
    contact_html = "".join(
        f'<div style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]};">{ln}</div>' for ln in contact
    )
    return (
        f'<div style="padding:24px 0 0 0; margin-top:16px; '
        f'border-top:1px solid {TOKENS["BORDER"]};">'
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding-bottom:8px;">{closing}</div>'
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'font-weight:600;">{name}</div>'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["MUTED"]};">{title}</div>'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["MUTED"]}; '
        f'padding-bottom:8px;">{company}</div>'
        f"{contact_html}"
        f"</div>"
    )


DEFAULT_APPROVAL_ATTACHMENTS = [
    "Loan Contract.pdf",
    "Key Facts Sheet.pdf",
    "Credit Guide.pdf",
]

BULLET_LINE_RE = re.compile(r"^[\u2022•]\s*(.+)$")
FACTOR_LINE_RE = re.compile(r"^([A-Z][A-Za-z\s\-/]+):\s+(.+)$")
FACTOR_TRIGGER_PREFIX = "This decision was based on"
OFFER_HEADER_RE = re.compile(r"^Option\s+(\d+)[\s:.\-\u2013\u2014]+(.+)$")
UNSUBSCRIBE_LINE_RE = re.compile(r"^Unsubscribe:\s*(\S+)")
CALL_SARAH_LINE_RE = re.compile(r"^Call Sarah on\s+(\d[\d\s]+)", re.I)
MARKETING_BREAK_PREFIXES = ("ABN ", "Ph:", "Phone:", "Email:", "Website:", "Unsubscribe:")
BUREAU_BULLET_RE = re.compile(r"^[\u2022•]\s*(Equifax|Illion|Experian)\b", re.I)


def _extract_section_bullets(body: str, section_label: str) -> tuple[list[str], int, int]:
    """Find '{label}:' followed by bullet-point lines.

    Intro paragraph between label and first bullet is included in the block range
    (so it gets removed from the legacy body), but the bullets are what's returned.
    """
    lines = body.split("\n")
    start = -1
    last_bullet = -1
    bullets: list[str] = []
    for i, line in enumerate(lines):
        if start == -1:
            if line.strip() == section_label:
                start = i
            continue
        m = BULLET_LINE_RE.match(line.strip())
        if m:
            bullets.append(m.group(1).strip())
            last_bullet = i
            continue
        if bullets and line.strip() == "":
            continue
        if bullets and line.strip() != "":
            break
    return bullets, start, last_bullet


def _extract_factor_paragraphs(body: str) -> tuple[list[tuple[str, str]], int, int]:
    """Find factor-label paragraphs after the 'This decision was based on…' line.

    Accepts both plain ``Label: explanation.`` and bulleted ``•  Label: explanation.``
    shapes — live Claude output uses the bullet form per the prompt template.
    """
    lines = body.split("\n")
    trigger_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(FACTOR_TRIGGER_PREFIX):
            trigger_idx = i
            break
    if trigger_idx == -1:
        return [], -1, -1
    factors: list[tuple[str, str]] = []
    end = trigger_idx
    i = trigger_idx + 1
    while i < len(lines):
        s = lines[i].strip()
        if s == "":
            i += 1
            continue
        bm = BULLET_LINE_RE.match(s)
        inner = bm.group(1).strip() if bm else s
        m = FACTOR_LINE_RE.match(inner)
        if m:
            factors.append((m.group(1).strip(), m.group(2).strip()))
            end = i
            i += 1
            continue
        break
    return factors, trigger_idx, end


def _extract_credit_report_block(body: str) -> tuple[int, int]:
    """Locate the credit report section so it can be replaced by the structured card.

    Recognizes two shapes:

    1. Explicit ``Free Credit Report:`` section label followed by intro + bureau URLs.
    2. Prose intro mentioning "credit report" immediately followed (with optional
       blank line) by two or more ``• Equifax/Illion/Experian – url`` bullets.
       This is what the live denial prompt produces.

    Returns (start, end) spanning the full section, or (-1, -1) if not found.
    """
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "Free Credit Report:":
            start = i
            end = start
            for j in range(start + 1, len(lines)):
                s = lines[j].strip()
                if s in SECTION_LABELS or s in CLOSINGS:
                    break
                if s:
                    end = j
            return start, end

    n = len(lines)
    for i in range(n):
        if not BUREAU_BULLET_RE.match(lines[i].strip()):
            continue
        last_bureau = i
        bureau_count = 1
        j = i + 1
        while j < n:
            s = lines[j].strip()
            if s == "":
                j += 1
                continue
            if BUREAU_BULLET_RE.match(s):
                last_bureau = j
                bureau_count += 1
                j += 1
                continue
            break
        if bureau_count < 2:
            continue
        start = i
        for k in range(i - 1, -1, -1):
            s = lines[k].strip()
            if s == "":
                continue
            if s in SECTION_LABELS or s in CLOSINGS:
                break
            if BULLET_LINE_RE.match(s):
                break
            if "credit report" in s.lower():
                start = k
                # Asymmetric with outer walk: outer `continue`s past blanks to
                # locate the "credit report" intro across paragraph gaps; inner
                # `break`s at the first blank so the prose intro stays bounded
                # to its own paragraph and doesn't swallow preceding content.
                for k2 in range(k - 1, -1, -1):
                    s2 = lines[k2].strip()
                    if s2 == "":
                        break
                    if s2 in SECTION_LABELS or s2 in CLOSINGS:
                        break
                    if BULLET_LINE_RE.match(s2):
                        break
                    start = k2
                break
            break
        return start, last_bureau
    return -1, -1


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
            f"</td></tr>"
        )
    return (
        f'<div style="margin:16px 0;">'
        f'<table role="presentation" style="width:100%; '
        f"background-color:{TOKENS['CARD_BG']}; "
        f'border-left:4px solid {TOKENS["CAUTION"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f"color:{TOKENS['CAUTION']}; text-transform:uppercase; "
        f'letter-spacing:0.5px; padding-bottom:8px;">Assessment Factors</div>'
        f'<table role="presentation" style="width:100%;">{rows}</table>'
        f"</td></tr></table>"
        f"</div>"
    )


def _render_what_you_can_do_card(bullets: list[str], intro: str = "") -> str:
    items = "".join(
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding:4px 0;">'
        f'<span style="color:{TOKENS["SUCCESS"]}; font-weight:600;">&#10003;</span> &nbsp;{b}</div>'
        for b in bullets
    )
    intro_html = (
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; padding-bottom:8px;">{intro}</div>'
        if intro
        else ""
    )
    return (
        f'<div style="margin:16px 0;">'
        f'<table role="presentation" style="width:100%; '
        f"background-color:{TOKENS['CARD_BG']}; "
        f'border-left:4px solid {TOKENS["SUCCESS"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f"color:{TOKENS['SUCCESS']}; text-transform:uppercase; "
        f'letter-spacing:0.5px; padding-bottom:8px;">What You Can Do</div>'
        f"{intro_html}{items}"
        f"</td></tr></table>"
        f"</div>"
    )


def _render_credit_report_card() -> str:
    bureaus = [
        ("Equifax", "https://equifax.com.au"),
        ("Experian", "https://experian.com.au"),
        ("Illion", "https://illion.com.au"),
    ]
    rows = "".join(
        f'<tr><td style="padding:6px 0; font-size:14px; color:{TOKENS["TEXT"]};">'
        f"<strong>{name}</strong> &mdash; "
        f'<a href="{url}" style="color:{TOKENS["BRAND_ACCENT"]};">'
        f"{url.replace('https://', '')}</a>"
        f"</td></tr>"
        for name, url in bureaus
    )
    return (
        f'<div style="margin:16px 0;">'
        f'<table role="presentation" style="width:100%; '
        f"background-color:{TOKENS['CARD_BG']}; "
        f'border-left:4px solid {TOKENS["BRAND_ACCENT"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; font-weight:600; '
        f"color:{TOKENS['BRAND_ACCENT']}; text-transform:uppercase; "
        f'letter-spacing:0.5px; padding-bottom:8px;">Free Credit Report</div>'
        f'<div style="font-size:{TOKENS["BODY_SIZE"]}; color:{TOKENS["TEXT"]}; '
        f'padding-bottom:8px;">You are entitled to a free credit report from each bureau once per year:</div>'
        f'<table role="presentation" style="width:100%;">{rows}</table>'
        f"</td></tr></table>"
        f"</div>"
    )


def _render_dual_cta() -> str:
    primary = _render_cta("Call Sarah on 1300 000 000", "tel:1300000000")
    secondary = (
        f'<div style="text-align:center; padding:0 0 16px 0;">'
        f'<a href="mailto:aussieloanai@gmail.com" '
        f'style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["BRAND_ACCENT"]}; '
        f'text-decoration:underline;">Or reply to this email</a>'
        f"</div>"
    )
    return primary + secondary


def _render_denial_body(plain_body: str) -> str:
    factors, f_start, f_end = _extract_factor_paragraphs(plain_body)
    wycd, w_start, w_end = _extract_section_bullets(plain_body, "What You Can Do:")
    cr_start, cr_end = _extract_credit_report_block(plain_body)
    pre_sig, sig_lines, post_sig = _split_at_signature(plain_body)
    pre_sig_end_idx = len(pre_sig.split("\n")) if pre_sig else 0

    lines = plain_body.split("\n")
    parts: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            parts.append(_render_legacy_body("\n".join(buffer)))
            buffer.clear()

    i = 0
    while i < pre_sig_end_idx:
        if factors and i == f_start:
            flush()
            parts.append(_render_factor_card(factors))
            i = f_end + 1
            continue
        if wycd and i == w_start:
            flush()
            parts.append(
                _render_what_you_can_do_card(wycd, intro="Here are some ways to strengthen a future application:")
            )
            i = w_end + 1
            continue
        if cr_start != -1 and i == cr_start:
            flush()
            parts.append(_render_credit_report_card())
            i = cr_end + 1
            continue
        buffer.append(lines[i])
        i += 1
    flush()

    parts.append(_render_dual_cta())
    parts.append(_render_signature_block(sig_lines))
    if post_sig.strip():
        parts.append(_render_legacy_body(post_sig))
    return "".join(parts)


def _extract_marketing_offers(body: str) -> tuple[list[dict], int, int]:
    """Parse 'Option N:' sections. Returns (offers, combined_start, combined_end).

    Each offer dict contains: label, title, bullets, fit.
    Indices span the combined offers block (first header to last fit line).
    Returns ([], -1, -1) if no offers found.
    """
    lines = body.split("\n")
    header_idxs: list[tuple[int, re.Match[str]]] = []
    for i, ln in enumerate(lines):
        m = OFFER_HEADER_RE.match(ln.strip())
        if m:
            header_idxs.append((i, m))
    if not header_idxs:
        return [], -1, -1

    def _offer_end(start_i: int, next_header_i: int | None) -> int:
        upper = next_header_i - 1 if next_header_i is not None else len(lines) - 1
        end_i = start_i
        for j in range(start_i + 1, upper + 1):
            s = lines[j].strip()
            if s in CLOSINGS or CALL_SARAH_LINE_RE.match(s) or any(s.startswith(p) for p in MARKETING_BREAK_PREFIXES):
                return j - 1
            end_i = j
        return end_i

    offers: list[dict] = []
    for h_idx, (start_i, m) in enumerate(header_idxs):
        next_header_i = header_idxs[h_idx + 1][0] if h_idx + 1 < len(header_idxs) else None
        end_i = _offer_end(start_i, next_header_i)
        while end_i > start_i and not lines[end_i].strip():
            end_i -= 1

        bullets: list[str] = []
        fit = ""
        for j in range(start_i + 1, end_i + 1):
            s = lines[j].strip()
            if not s:
                continue
            bm = BULLET_LINE_RE.match(s)
            if bm:
                bullets.append(bm.group(1))
                continue
            if bullets and not fit:
                fit = s

        offers.append(
            {
                "label": f"Option {m.group(1)}",
                "title": m.group(2).strip(),
                "bullets": bullets,
                "fit": fit,
            }
        )

    combined_start = header_idxs[0][0]
    last_start = header_idxs[-1][0]
    combined_end = _offer_end(last_start, None)
    while combined_end > combined_start and not lines[combined_end].strip():
        combined_end -= 1

    return offers, combined_start, combined_end


def _render_offer_card(offer: dict) -> str:
    bullets_html = "".join(
        f'<div style="font-size:14px; color:#374151; padding:4px 0;">&#8226;&nbsp;&nbsp;{b}</div>'
        for b in offer["bullets"]
    )
    fit_html = (
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; color:{TOKENS["MUTED"]}; '
        f"font-style:italic; padding-top:8px; margin-top:8px; "
        f'border-top:1px solid {TOKENS["BORDER"]};">{offer["fit"]}</div>'
        if offer["fit"]
        else ""
    )
    return (
        f'<div style="margin:12px 0;">'
        f'<table role="presentation" cellspacing="0" cellpadding="0" '
        f'style="width:100%; background-color:{TOKENS["CARD_BG"]}; '
        f'border-left:4px solid {TOKENS["MARKETING"]}; border-radius:4px;">'
        f'<tr><td style="padding:16px 20px;">'
        f'<div style="font-size:11px; font-weight:600; '
        f"color:{TOKENS['MARKETING']}; text-transform:uppercase; "
        f'letter-spacing:0.5px;">{offer["label"]}</div>'
        f'<div style="font-size:17px; font-weight:600; '
        f'color:{TOKENS["TEXT"]}; padding:4px 0 12px 0;">{offer["title"]}</div>'
        f"{bullets_html}"
        f"{fit_html}"
        f"</td></tr></table>"
        f"</div>"
    )


def _render_marketing_footer(body: str) -> str:
    parts: list[str] = []
    if "term deposit" in body.lower():
        parts.append(
            f'<div style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]}; '
            f'padding:4px 0;">Deposits are protected by the Financial Claims Scheme '
            f"(FCS) up to $250,000 per account holder per ADI.</div>"
        )
    if "bonus rate" in body.lower():
        parts.append(
            f'<div style="font-size:{TOKENS["FINE_SIZE"]}; color:{TOKENS["FINE"]}; '
            f'padding:4px 0;">Bonus rates apply to eligible accounts subject to '
            f"monthly deposit and transaction conditions.</div>"
        )
    m = UNSUBSCRIBE_LINE_RE.search(body)
    unsub_url = m.group(1) if m else "https://aussieloanai.com.au/unsubscribe"
    parts.append(
        f'<div style="padding:16px 0 0 0; margin-top:16px; '
        f'border-top:1px solid {TOKENS["BORDER"]};">'
        f'<a href="{unsub_url}" '
        f'style="font-size:{TOKENS["FINE_SIZE"]}; '
        f"color:{TOKENS['BRAND_ACCENT']}; "
        f'text-decoration:underline;">Unsubscribe</a>'
        f" &nbsp;&middot;&nbsp; "
        f'<span style="font-size:{TOKENS["FINE_SIZE"]}; '
        f'color:{TOKENS["FINE"]};">You received this email because you recently '
        f"applied for a loan with AussieLoanAI.</span>"
        f"</div>"
    )
    return "".join(parts)


def _render_marketing_body(plain_body: str) -> str:
    offers, o_start, o_end = _extract_marketing_offers(plain_body)
    pre_sig, sig_lines, post_sig = _split_at_signature(plain_body)
    pre_sig_end_idx = len(pre_sig.split("\n")) if pre_sig else 0

    lines = plain_body.split("\n")
    parts: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            parts.append(_render_legacy_body("\n".join(buffer)))
            buffer.clear()

    i = 0
    while i < pre_sig_end_idx:
        if offers and i == o_start:
            flush()
            for offer in offers:
                parts.append(_render_offer_card(offer))
            parts.append(
                _render_cta(
                    "Call Sarah on 1300 000 000",
                    "tel:1300000000",
                    color=TOKENS["MARKETING"],
                )
            )
            i = o_end + 1
            continue
        s = lines[i].strip()
        if CALL_SARAH_LINE_RE.match(s):
            i += 1
            continue
        buffer.append(lines[i])
        i += 1
    flush()

    parts.append(_render_signature_block(sig_lines))
    parts.append(_render_marketing_footer(plain_body))

    if post_sig.strip():
        parts.append(_render_legacy_body(post_sig))

    return "".join(parts)


def _render_approval_body(plain_body: str) -> str:
    ld_rows, ld_start, ld_end = _extract_loan_details(plain_body)
    ns_steps, ns_start, ns_end = _extract_numbered_steps(plain_body, "Next Steps:")
    pre_sig, sig_lines, post_sig = _split_at_signature(plain_body)
    pre_sig_end_idx = len(pre_sig.split("\n")) if pre_sig else 0

    lines = plain_body.split("\n")
    parts: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            parts.append(_render_legacy_body("\n".join(buffer)))
            buffer.clear()

    i = 0
    while i < pre_sig_end_idx:
        if ld_rows and i == ld_start:
            flush()
            parts.append(_render_loan_details_card(ld_rows))
            i = ld_end + 1
            continue
        if ns_steps and i == ns_start:
            flush()
            parts.append(_render_next_steps_block(ns_steps))
            parts.append(
                _render_cta(
                    "Review &amp; Sign Documents",
                    "https://portal.aussieloanai.com.au/sign",
                )
            )
            i = ns_end + 1
            continue
        buffer.append(lines[i])
        i += 1
    flush()

    if ns_steps:
        parts.append(_render_attachments_chips(DEFAULT_APPROVAL_ATTACHMENTS))

    parts.append(_render_signature_block(sig_lines))

    if post_sig.strip():
        parts.append(_render_legacy_body(post_sig))

    return "".join(parts)


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
    else:
        headline = cfg["default_headline"]
        subtitle = "A few options tailored to you"
    return (
        f'<tr><td style="padding:32px 24px 16px 24px; '
        f'font-family:{TOKENS["FONT_STACK"]};">'
        f'<div style="width:48px; height:48px; border-radius:24px; '
        f"background-color:{cfg['color']}; text-align:center; "
        f"line-height:48px; color:#ffffff; font-size:24px; "
        f'font-weight:600;">{cfg["icon"]}</div>'
        f'<h1 style="font-size:{TOKENS["HEAD_SIZE"]}; line-height:28px; '
        f'color:{TOKENS["TEXT"]}; margin:12px 0 4px 0; font-weight:600;">'
        f"{headline}</h1>"
        f'<div style="font-size:{TOKENS["LABEL_SIZE"]}; '
        f'color:{TOKENS["MUTED"]};">{subtitle}</div>'
        f"</td></tr>"
    )


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
                '<table style="width:100%;border-collapse:collapse;margin:8px 0;">' + "".join(detail_rows) + "</table>"
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
            html_parts.append(f'<p style="margin:2px 0 2px 16px;">\u2022&nbsp;&nbsp;{bullet_match.group(1)}</p>')
            continue

        num_match = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
        if num_match:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:2px 0 2px 16px;">{num_match.group(1)}. {num_match.group(2)}</p>')
            continue

        detail_match = LOAN_DETAIL_RE.match(line)
        if detail_match:
            label = detail_match.group(2)
            value = detail_match.group(3)
            if len(label) < 35 and len(value) < 50:
                detail_rows.append(f"<tr><td {td_label}>{label}</td><td {td_value}>{value}</td></tr>")
                continue

        _flush_detail_rows()

        if re.match(r"^[\u2500\u2501\-]{5,}$", stripped):
            html_parts.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">')
            continue

        if (
            stripped.startswith("ABN ")
            or stripped.startswith("Ph:")
            or stripped.startswith("Phone:")
            or stripped.startswith("Email:")
            or stripped.startswith("Website:")
        ):
            html_parts.append(f'<p style="margin:0;font-size:12px;color:#888;">{stripped}</p>')
            continue

        if stripped == "":
            html_parts.append('<div style="height:12px;"></div>')
            continue

        margin = "16px" if stripped.endswith(".") else "4px"
        top_margin = "16px" if stripped.startswith("Congratulations") else "0"
        html_parts.append(f'<p style="margin:{top_margin} 0 {margin} 0;">{stripped}</p>')

    _flush_detail_rows()
    return "\n".join(html_parts)


def _render_header() -> str:
    return (
        f'<tr><td style="background-color:{TOKENS["BRAND_PRIMARY"]}; '
        f'padding:16px 24px; border-radius:8px 8px 0 0;">'
        f'<span style="color:#ffffff; font-size:16px; font-weight:600; '
        f'letter-spacing:0.3px;">AussieLoanAI</span>'
        f'<span style="color:#bfdbfe; font-size:12px; margin-left:8px;">'
        f"Australian Credit Licence No. 012345</span>"
        f"</td></tr>"
    )


def _render_footer_shell() -> str:
    return (
        f'<tr><td style="padding:24px; background-color:{TOKENS["CARD_BG"]}; '
        f"border-radius:0 0 8px 8px; font-size:{TOKENS['FINE_SIZE']}; "
        f'color:{TOKENS["FINE"]};">'
        f"&nbsp;"
        f"</td></tr>"
    )


def render_html(plain_body: str, email_type: EmailType) -> str:
    """Convert plain-text email body into Gmail-safe HTML.

    Args:
        plain_body: Raw plain-text email as produced by Claude/template fallback.
        email_type: One of "approval", "denial", "marketing".

    Returns:
        Gmail-safe HTML string with inline styles. Ready to pass to
        Django's send_mail(html_message=...).
    """
    if email_type == "approval":
        body_html = _render_approval_body(plain_body)
    elif email_type == "denial":
        body_html = _render_denial_body(plain_body)
    elif email_type == "marketing":
        body_html = _render_marketing_body(plain_body)
    else:
        body_html = _render_legacy_body(plain_body)

    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%; background-color:{TOKENS["PAGE_BG"]}; margin:0; padding:0;">'
        f'<tr><td style="padding:32px 16px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%; max-width:{TOKENS["MAX_WIDTH"]}; margin:0 auto; '
        f"background-color:#ffffff; border-radius:8px; "
        f'box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
        f"{_render_header()}"
        f"{_render_hero(email_type, plain_body)}"
        f'<tr><td style="padding:0 24px 24px 24px; font-family:{TOKENS["FONT_STACK"]}; '
        f"font-size:{TOKENS['BODY_SIZE']}; line-height:{TOKENS['LINE_HEIGHT']}; "
        f'color:{TOKENS["TEXT"]};">'
        f"{body_html}"
        f"</td></tr>"
        f"{_render_footer_shell()}"
        f"</table>"
        f"</td></tr>"
        f"</table>"
    )
