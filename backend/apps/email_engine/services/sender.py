import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.email_engine.services.html_renderer import render_html

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
