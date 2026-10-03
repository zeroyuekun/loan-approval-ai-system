"""EMAIL_REDIRECT_ALL_TO sends every outbound email to one inbox instead of the applicant."""

from unittest.mock import patch

from apps.email_engine.services import sender


def _send(settings_obj, redirect):
    settings_obj.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings_obj.EMAIL_HOST_USER = "aussieloanai@gmail.com"
    settings_obj.EMAIL_HOST_PASSWORD = "app-password"
    settings_obj.EMAIL_REDIRECT_ALL_TO = redirect
    with patch.object(sender, "send_mail") as send_mail:
        result = sender.send_decision_email("applicant@example.com", "Subject", "Body", email_type="denial")
    return result, send_mail.call_args.kwargs["recipient_list"]


def test_redirect_replaces_the_applicant_address(settings):
    result, recipients = _send(settings, "aussieloanai@gmail.com")
    assert recipients == ["aussieloanai@gmail.com"]
    assert result == {"sent": True, "recipient": "aussieloanai@gmail.com"}


def test_no_redirect_sends_to_the_applicant(settings):
    result, recipients = _send(settings, "")
    assert recipients == ["applicant@example.com"]
    assert result["recipient"] == "applicant@example.com"


def test_template_backend_uses_no_llm(monkeypatch):
    """EMAIL_LLM_BACKEND=template: no client, even with an API key present."""
    from apps.email_engine.services.email_generator import EmailGenerator

    monkeypatch.setenv("EMAIL_LLM_BACKEND", "template")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    gen = EmailGenerator()
    assert gen.client is None
    assert gen.provider == "template"
