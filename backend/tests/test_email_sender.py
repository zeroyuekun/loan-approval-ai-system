"""Functional tests for the email sender — uses Django locmem backend.

Previously sender.py was always mocked at the call sites. These tests exercise
the real send path including the credentials gate, the SMTP backend
(replaced by locmem in tests), and HTML body rendering.
"""

import pytest
from django.core import mail

from apps.email_engine.services.sender import send_decision_email


@pytest.fixture
def _locmem_settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST_USER = "tests@example.test"
    settings.EMAIL_HOST_PASSWORD = "test-password"
    settings.DEFAULT_FROM_EMAIL = "noreply@example.test"
    mail.outbox.clear()
    return settings


def test_send_decision_email_delivers_to_locmem(_locmem_settings):
    body = "Dear Applicant,\n\nWe have made a decision on your application.\n\nKind regards,\nLending Team"
    result = send_decision_email("applicant@example.test", "Your loan decision", body)

    assert result == {"sent": True}
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["applicant@example.test"]
    assert mail.outbox[0].subject == "Your loan decision"


def test_send_decision_email_includes_html_alternative(_locmem_settings):
    body = "Dear Applicant,\n\nApproved.\n\nKind regards,\nLending Team"
    send_decision_email("applicant@example.test", "Subj", body)

    msg = mail.outbox[0]
    html_alts = [c for c in msg.alternatives if c[1] == "text/html"]
    assert len(html_alts) == 1, "expected exactly one text/html alternative"
    assert "Dear Applicant" in html_alts[0][0]


def test_send_decision_email_skips_when_credentials_missing(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST_USER = ""
    settings.EMAIL_HOST_PASSWORD = ""
    mail.outbox.clear()

    result = send_decision_email("applicant@example.test", "Subj", "body")

    assert result["sent"] is False
    assert "credentials" in result["error"].lower()
    assert len(mail.outbox) == 0


def test_send_decision_email_html_escapes_user_content(_locmem_settings):
    """Regression test for the XSS bug fixed in _plain_text_to_html."""
    body = 'Dear <script>alert("xss")</script>,\n\nApproved.'
    send_decision_email("applicant@example.test", "Subj", body)

    msg = mail.outbox[0]
    html_alts = [c for c in msg.alternatives if c[1] == "text/html"]
    html_content = html_alts[0][0]
    assert "<script>" not in html_content
    assert "&lt;script&gt;" in html_content


def test_send_decision_email_returns_error_on_send_failure(monkeypatch, settings):
    """Backend exceptions should be caught and returned in the error field."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST_USER = "tests@example.test"
    settings.EMAIL_HOST_PASSWORD = "test-password"
    settings.DEFAULT_FROM_EMAIL = "noreply@example.test"

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated SMTP failure")

    monkeypatch.setattr("apps.email_engine.services.sender.send_mail", _raise)

    result = send_decision_email("applicant@example.test", "Subj", "body")

    assert result["sent"] is False
    assert "simulated SMTP failure" in result["error"]
