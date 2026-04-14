"""Tests for the purge_expired_quotes management command."""

import datetime
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from apps.ml_engine.models import QuoteLog


def _make_user(username: str = "purge-user"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="x-pass", role="customer")


def _make_quote_with_expiry(user, expires_at) -> QuoteLog:
    quote = QuoteLog.objects.create(
        user=user,
        inputs_hash="y" * 64,
        eligible=False,
        expires_at=timezone.now() + datetime.timedelta(days=7),  # placeholder; overwritten below
    )
    QuoteLog.objects.filter(pk=quote.pk).update(expires_at=expires_at)
    quote.refresh_from_db()
    return quote


@pytest.mark.django_db
def test_dry_run_does_not_delete():
    user = _make_user()
    old = _make_quote_with_expiry(user, timezone.now() - datetime.timedelta(days=60))
    live = _make_quote_with_expiry(user, timezone.now() + datetime.timedelta(days=7))

    out = StringIO()
    call_command("purge_expired_quotes", stdout=out)

    assert "Dry-run only" in out.getvalue()
    assert QuoteLog.objects.filter(pk=old.pk).exists()
    assert QuoteLog.objects.filter(pk=live.pk).exists()


@pytest.mark.django_db
def test_apply_deletes_only_rows_older_than_threshold():
    user = _make_user("purge-owner")
    old = _make_quote_with_expiry(user, timezone.now() - datetime.timedelta(days=60))
    recent_expired = _make_quote_with_expiry(user, timezone.now() - datetime.timedelta(days=5))
    live = _make_quote_with_expiry(user, timezone.now() + datetime.timedelta(days=7))

    out = StringIO()
    call_command("purge_expired_quotes", "--apply", stdout=out)

    assert not QuoteLog.objects.filter(pk=old.pk).exists()
    assert QuoteLog.objects.filter(pk=recent_expired.pk).exists()  # within 30d buffer
    assert QuoteLog.objects.filter(pk=live.pk).exists()
    assert "Deleted 1" in out.getvalue()


@pytest.mark.django_db
def test_older_than_days_override():
    user = _make_user("purge-override")
    _make_quote_with_expiry(user, timezone.now() - datetime.timedelta(days=10))

    out = StringIO()
    call_command("purge_expired_quotes", "--older-than-days", "5", "--apply", stdout=out)

    assert QuoteLog.objects.count() == 0
    assert "Deleted 1" in out.getvalue()


@pytest.mark.django_db
def test_no_rows_to_purge_prints_success():
    user = _make_user("purge-empty")
    _make_quote_with_expiry(user, timezone.now() + datetime.timedelta(days=7))

    out = StringIO()
    call_command("purge_expired_quotes", "--apply", stdout=out)

    assert "No expired QuoteLog rows to purge" in out.getvalue()
