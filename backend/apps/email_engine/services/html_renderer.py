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
        f'color:{TOKENS["BRAND_PRIMARY"]}; text-transform:uppercase; '
        f'letter-spacing:0.5px; padding-bottom:8px;">Loan Details</div>'
        f'<table role="presentation" style="width:100%;">{row_html}</table>'
        f"</td></tr></table>"
        f"</div>"
    )


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
        f'background-color:{cfg["color"]}; text-align:center; '
        f'line-height:48px; color:#ffffff; font-size:24px; '
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
        rows, start, end = _extract_loan_details(plain_body)
    else:
        rows, start, end = [], -1, -1

    if rows:
        lines = plain_body.split("\n")
        top_body = "\n".join(lines[:start])
        rest_body = "\n".join(lines[end + 1 :])
        body_html = (
            _render_legacy_body(top_body) + _render_loan_details_card(rows) + _render_legacy_body(rest_body)
        )
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
