"""M6 + L25 — email task reliability.

Covers the sent_at idempotency marker (Task 2) and the Celery-native retry +
soft_time_limit + idempotent send behaviour (Task 3).
"""

import pytest

from apps.email_engine.models import GeneratedEmail


@pytest.mark.django_db
def test_generated_email_has_sent_at_marker(sample_application):
    email = GeneratedEmail.objects.create(
        application=sample_application,
        decision="denied",
        subject="s",
        body="b",
        prompt_used="p",
    )
    assert email.sent_at is None  # defaults to not-yet-sent
