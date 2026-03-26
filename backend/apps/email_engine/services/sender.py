import logging
import re

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _plain_text_to_html(body: str) -> str:
    """Convert a plain-text email body to HTML with bold section headers.

    Recognises lines ending with a colon (e.g. "Next Steps:", "What You Can Do:")
    and wraps them in <strong> tags. Preserves whitespace and bullet points.
    """
    lines = body.split('\n')
    html_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Section headers: lines that end with ':' and are mostly alphabetic
        if (
            stripped.endswith(':')
            and len(stripped) > 3
            and not stripped.startswith('\u2022')
            and not stripped.startswith('•')
            and not stripped[0].isdigit()
            and re.match(r'^[A-Za-z\s\u2019\u2018\'&,\-]+:$', stripped)
        ):
            indent = line[:len(line) - len(line.lstrip())]
            html_lines.append(f'{indent}<strong>{stripped}</strong>')
        else:
            html_lines.append(line)

    html_body = '<br>\n'.join(
        ln.replace('  ', '&nbsp;&nbsp;') for ln in html_lines
    )

    return (
        '<div style="font-family: Arial, Helvetica, sans-serif; '
        'font-size: 14px; line-height: 1.6; color: #333;">\n'
        f'{html_body}\n'
        '</div>'
    )


def send_decision_email(recipient_email, subject, body):
    """Send a loan decision email to the customer via Gmail SMTP.

    Sends both plain-text and HTML versions. Section headers (lines ending
    with ':') are rendered in bold in the HTML version.

    Returns a dict with 'sent' (bool) and, on failure, 'error' (str).
    """
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        msg = 'Email credentials not configured — skipping send'
        logger.warning('%s to %s', msg, recipient_email)
        return {'sent': False, 'error': msg}

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
        logger.info('Email sent to %s: %s', recipient_email, subject)
        return {'sent': True}
    except Exception as exc:
        logger.exception('Failed to send email to %s', recipient_email)
        return {'sent': False, 'error': str(exc)}
