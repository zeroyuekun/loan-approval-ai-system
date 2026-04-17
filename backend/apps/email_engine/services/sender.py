import logging
import re

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


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

# Loan detail line: "  Label:   Value" with leading whitespace
LOAN_DETAIL_RE = re.compile(r"^(\s{2,})(\S[^:]+:)\s+(.+)$")


ACCENT_COLORS = {
    "approval": "#16a34a",
    "denial": "#374151",
    "marketing": "#7c3aed",
}

CTA_LABELS = {
    "approval": "Review &amp; Sign",
    "denial": "Explore Options",
    "marketing": "See Alternatives",
}


def _get_accent_color(email_type: str) -> str:
    return ACCENT_COLORS.get(email_type, ACCENT_COLORS["approval"])


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


def _render_section_header(label: str, accent: str) -> str:
    return (
        '<p style="margin:28px 0 8px 0;">'
        f'<span style="font-size:18px; font-weight:bold; color:#111827; '
        f'border-bottom:2px solid {accent}; padding-bottom:6px; '
        'display:inline-block;">'
        f'{label.rstrip(":")}'
        '</span></p>'
    )


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


def _plain_text_to_html(body: str, *, email_type: str = "approval") -> str:
    """Convert a plain-text email body to styled HTML matching the dashboard preview.

    email_type selects the accent color and determines whether compliance blocks
    (AFCA for denial) are appended.
    """
    accent = _get_accent_color(email_type)
    lines = body.split("\n")
    html_parts: list[str] = []
    detail_rows: list[str] = []
    list_state: dict = {"items": [], "type": None}

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

    td_label = (
        'style="padding:8px 0; font-size:13px; color:#6b7280; '
        'border-bottom:1px solid #e5e7eb;"'
    )
    td_value = (
        'style="padding:8px 0; font-size:15px; font-weight:bold; '
        'color:#111827; text-align:right; border-bottom:1px solid #e5e7eb;"'
    )

    for line in lines:
        stripped = line.strip()

        # Section headers
        is_section = stripped in SECTION_LABELS
        is_option = bool(OPTION_PATTERN.match(stripped))
        is_dear = stripped.startswith("Dear ")
        is_closing = stripped in CLOSINGS

        if is_section or is_option:
            _flush_list()
            _flush_detail_rows()
            html_parts.append(_render_section_header(stripped, accent))
            continue

        if is_dear:
            _flush_list()
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:0 0 12px 0;">{stripped}</p>')
            continue

        if is_closing:
            _flush_list()
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:24px 0 4px 0;">{stripped}</p>')
            continue

        # Bullet points — semantic <ul>/<li> via list accumulator
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

        # Numbered list items (e.g. "  1. Document.pdf") — semantic <ol>/<li>
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

        # Loan detail key-value lines (e.g. "  Loan Amount:   $35,000.00")
        detail_match = LOAN_DETAIL_RE.match(line)
        if detail_match:
            label = detail_match.group(2)
            value = detail_match.group(3)
            if len(label) < 35 and len(value) < 50:
                _flush_list()
                detail_rows.append(f"<tr><td {td_label}>{label}</td><td {td_value}>{value}</td></tr>")
                continue

        _flush_list()
        _flush_detail_rows()

        # Horizontal rule
        if re.match(r"^[\u2500\u2501\-]{5,}$", stripped):
            html_parts.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">')
            continue

        # Signature details (ABN, Ph/Phone, Email, Website)
        if (
            stripped.startswith("ABN ")
            or stripped.startswith("Ph:")
            or stripped.startswith("Phone:")
            or stripped.startswith("Email:")
            or stripped.startswith("Website:")
        ):
            html_parts.append(f'<p style="margin:0;font-size:12px;color:#888;">{stripped}</p>')
            continue

        # Empty lines — paragraph margins already carry the gap, no extra spacer
        if stripped == "":
            continue

        # Body text — sentences get paragraph spacing
        margin = "16px" if stripped.endswith(".") else "4px"
        top_margin = "16px" if stripped.startswith("Congratulations") else "0"
        html_parts.append(f'<p style="margin:{top_margin} 0 {margin} 0;">{stripped}</p>')

    _flush_list()
    _flush_detail_rows()

    # Inject CTA button before the closing signature block, if any.
    cta_html = _render_cta(email_type, accent)
    insert_index = len(html_parts)
    for i, part in enumerate(html_parts):
        if any(closing in part for closing in CLOSINGS):
            insert_index = i
            break
    html_parts.insert(insert_index, cta_html)

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


def send_decision_email(recipient_email, subject, body):
    """Send a loan decision email to the customer via Gmail SMTP.

    Sends both plain-text and HTML versions. Section headers (lines ending
    with ':') are rendered in bold in the HTML version.

    Returns a dict with 'sent' (bool) and, on failure, 'error' (str).
    """
    using_console = settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"
    if not using_console and (not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD):
        msg = "Email credentials not configured — skipping send"
        logger.warning("%s to %s", msg, recipient_email)
        return {"sent": False, "error": msg}

    html_body = _plain_text_to_html(body)

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
