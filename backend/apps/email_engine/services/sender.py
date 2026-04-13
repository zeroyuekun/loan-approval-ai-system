import html
import logging
import re

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _esc(value: str) -> str:
    """HTML-escape user-controlled text before interpolating into HTML templates."""
    return html.escape(value, quote=True)


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


def _plain_text_to_html(body: str) -> str:
    """Convert a plain-text email body to styled HTML matching the dashboard preview."""
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

        # Section headers
        is_section = stripped in SECTION_LABELS
        is_option = bool(OPTION_PATTERN.match(stripped))
        is_dear = stripped.startswith("Dear ")
        is_closing = stripped in CLOSINGS

        if is_section or is_option:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:20px 0 4px 0;"><strong>{_esc(stripped)}</strong></p>')
            continue

        if is_dear:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:0 0 4px 0;"><strong>{_esc(stripped)}</strong></p>')
            continue

        if is_closing:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:20px 0 4px 0;"><strong>{_esc(stripped)}</strong></p>')
            continue

        # Bullet points — render as plain text with bullet character
        bullet_match = re.match(r"^[\u2022•]\s*(.+)$", stripped)
        if bullet_match:
            _flush_detail_rows()
            content = bullet_match.group(1)
            html_parts.append(f'<p style="margin:2px 0 2px 16px;">\u2022&nbsp;&nbsp;{_esc(content)}</p>')
            continue

        # Numbered list items (e.g. "  1. Document.pdf")
        num_match = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
        if num_match:
            _flush_detail_rows()
            html_parts.append(f'<p style="margin:2px 0 2px 16px;">{_esc(num_match.group(1))}. {_esc(num_match.group(2))}</p>')
            continue

        # Loan detail key-value lines (e.g. "  Loan Amount:   $35,000.00")
        detail_match = LOAN_DETAIL_RE.match(line)
        if detail_match:
            label = detail_match.group(2)
            value = detail_match.group(3)
            if len(label) < 35 and len(value) < 50:
                detail_rows.append(f"<tr><td {td_label}>{_esc(label)}</td><td {td_value}>{_esc(value)}</td></tr>")
                continue

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
            html_parts.append(f'<p style="margin:0;font-size:12px;color:#888;">{_esc(stripped)}</p>')
            continue

        # Empty lines
        if stripped == "":
            html_parts.append('<div style="height:12px;"></div>')
            continue

        # Body text — sentences get paragraph spacing
        margin = "16px" if stripped.endswith(".") else "4px"
        top_margin = "16px" if stripped.startswith("Congratulations") else "0"
        html_parts.append(f'<p style="margin:{top_margin} 0 {margin} 0;">{_esc(stripped)}</p>')

    _flush_detail_rows()

    html_body = "\n".join(html_parts)
    return (
        '<div style="font-family: Arial, Helvetica, sans-serif; '
        'font-size: 14px; line-height: 1.6; color: #333;">\n'
        f"{html_body}\n"
        "</div>"
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
