"""Tests for the purge_expired_quotes_task Celery task."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ml_engine.models import QuoteLog
from apps.ml_engine.tasks import purge_expired_quotes_task


def _make_user(username: str = "task-purge-user"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="x-pass", role="customer")


def _make_quote(user, expires_at) -> QuoteLog:
    quote = QuoteLog.objects.create(
        user=user,
        inputs_hash="z" * 64,
        eligible=False,
        expires_at=timezone.now() + datetime.timedelta(days=7),
    )
    QuoteLog.objects.filter(pk=quote.pk).update(expires_at=expires_at)
    return quote


@pytest.mark.django_db
def test_task_deletes_only_rows_older_than_default_30_days():
    user = _make_user()
    old = _make_quote(user, timezone.now() - datetime.timedelta(days=60))
    recent = _make_quote(user, timezone.now() - datetime.timedelta(days=5))
    live = _make_quote(user, timezone.now() + datetime.timedelta(days=7))

    # Call the underlying function directly (bypass Celery dispatch).
    result = purge_expired_quotes_task.run()

    assert result["status"] == "completed"
    assert result["deleted"] == 1
    assert result["older_than_days"] == 30
    assert not QuoteLog.objects.filter(pk=old.pk).exists()
    assert QuoteLog.objects.filter(pk=recent.pk).exists()
    assert QuoteLog.objects.filter(pk=live.pk).exists()


@pytest.mark.django_db
def test_task_respects_older_than_days_argument():
    user = _make_user("override-user")
    _make_quote(user, timezone.now() - datetime.timedelta(days=10))

    result = purge_expired_quotes_task.run(older_than_days=5)

    assert result["deleted"] == 1
    assert QuoteLog.objects.count() == 0


@pytest.mark.django_db
def test_task_returns_zero_when_nothing_to_delete():
    user = _make_user("empty-task")
    _make_quote(user, timezone.now() + datetime.timedelta(days=7))

    result = purge_expired_quotes_task.run()

    assert result["deleted"] == 0
    assert QuoteLog.objects.count() == 1
