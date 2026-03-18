import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_decision_email(recipient_email, subject, body):
    """Send a loan decision email to the customer via Gmail SMTP.

    Returns a dict with 'sent' (bool) and, on failure, 'error' (str).
    """
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        msg = 'Email credentials not configured — skipping send'
        logger.warning('%s to %s', msg, recipient_email)
        return {'sent': False, 'error': msg}

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        logger.info('Email sent to %s: %s', recipient_email, subject)
        return {'sent': True}
    except Exception as exc:
        logger.exception('Failed to send email to %s', recipient_email)
        return {'sent': False, 'error': str(exc)}
