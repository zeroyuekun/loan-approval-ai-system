"""Purge QuoteLog rows whose expires_at is in the past (with a retention buffer).

Quotes are indicative and short-lived (7-day window from creation). Rows past
their expiry have no user-facing purpose; keeping them indefinitely just grows
the table. This command deletes QuoteLog rows whose expires_at is older than
``--older-than-days`` days (default 30) — a month-long buffer past the 7-day
indicative window for analytics / audit.

Dry-run by default — pass ``--apply`` to actually delete.

Usage:
    # Show what would be deleted
    python manage.py purge_expired_quotes

    # Keep only the last 60 days of expired quotes (older than 60d deleted)
    python manage.py purge_expired_quotes --older-than-days 60 --apply
"""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ml_engine.models import QuoteLog


class Command(BaseCommand):
    help = "Delete QuoteLog rows whose expires_at is older than --older-than-days days."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=30,
            help=(
                "Delete rows whose expires_at is older than this many days. "
                "Default 30 (keeps a ~month buffer past the 7-day indicative window)."
            ),
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this flag the command runs as a dry-run.",
        )

    def handle(self, *args, **options):
        older_than_days = options["older_than_days"]
        apply = options["apply"]

        cutoff = timezone.now() - datetime.timedelta(days=older_than_days)
        qs = QuoteLog.objects.filter(expires_at__lt=cutoff)
        count = qs.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No expired QuoteLog rows to purge."))
            return

        self.stdout.write(
            f"{count} QuoteLog row(s) have expires_at older than {older_than_days}d (cutoff: {cutoff.isoformat()})."
        )

        if not apply:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to delete. No changes made."))
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} QuoteLog row(s)."))
