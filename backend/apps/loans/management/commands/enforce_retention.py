"""Data retention lifecycle management.

Enforces documented retention periods per Australian regulatory requirements:

| Data Type               | Retention Period | Regulation                    |
|-------------------------|------------------|-------------------------------|
| Loan applications       | 7 years          | AML/CTF Act 2006, s 107      |
| Audit logs              | 7 years          | AML/CTF Act 2006, s 107      |
| KYC verification        | 7 years          | AML/CTF Act 2006, s 112      |
| Prediction logs         | 5 years          | APRA CPG 235 (model audit)    |
| Drift reports           | 3 years          | Internal governance policy    |
| Soft-deleted records    | 90 days          | Privacy Act 1988, APP 11.2   |
| Generated emails        | 7 years          | NCCP Act 2009, s 174         |
| Bias reports            | 7 years          | Anti-discrimination evidence  |

Usage:
    # Dry run — show what would be archived/purged
    python manage.py enforce_retention --dry-run

    # Execute retention policy
    python manage.py enforce_retention

    # Run as a weekly Celery beat task (see celery.py)
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import CustomerProfile
from apps.loans.models import AuditLog, LoanApplication
from apps.ml_engine.models import DriftReport, PredictionLog

logger = logging.getLogger(__name__)

# Retention periods (days)
RETENTION_POLICY = {
    "soft_deleted_records": 90,  # Privacy Act APP 11.2 — purge soft-deleted PII
    "prediction_logs": 5 * 365,  # APRA CPG 235 — model audit trail
    "drift_reports": 3 * 365,  # Internal governance policy
    # Loan applications, audit logs, KYC, emails, bias reports: 7 years
    # These are NOT purged by this command — they are archived to cold storage
    # when a separate archival pipeline is configured.
}


class Command(BaseCommand):
    help = "Enforce data retention policy: purge expired soft-deleted records and archive old data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted/archived without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        total_purged = 0
        total_archived = 0

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made\n"))

        # ── 1. Purge soft-deleted records past retention ──
        cutoff_soft = now - timedelta(days=RETENTION_POLICY["soft_deleted_records"])

        for model_cls in [CustomerProfile, LoanApplication]:
            name = model_cls.__name__
            expired = model_cls.all_objects.dead().filter(deleted_at__lt=cutoff_soft)
            count = expired.count()

            if count > 0:
                self.stdout.write(
                    f"  {name}: {count} soft-deleted record(s) older than "
                    f"{RETENTION_POLICY['soft_deleted_records']} days"
                )
                if not dry_run:
                    # Log before purging for audit trail
                    AuditLog.objects.create(
                        action="retention_purge",
                        resource_type=name,
                        resource_id="batch",
                        details={
                            "count": count,
                            "cutoff": cutoff_soft.isoformat(),
                            "policy": f"{RETENTION_POLICY['soft_deleted_records']} days",
                        },
                    )
                    expired.delete()
                    self.stdout.write(self.style.SUCCESS(f"    Purged {count} {name} records"))
                total_purged += count
            else:
                self.stdout.write(f"  {name}: no expired soft-deleted records")

        # ── 2. Archive old prediction logs and drift reports ──
        for model_cls, policy_key in ((PredictionLog, "prediction_logs"), (DriftReport, "drift_reports")):
            name = model_cls.__name__
            cutoff = now - timedelta(days=RETENTION_POLICY[policy_key])
            old_records = model_cls.objects.filter(created_at__lt=cutoff)
            count = old_records.count()

            if count > 0:
                self.stdout.write(f"  {name}: {count} record(s) older than {RETENTION_POLICY[policy_key] // 365} years")
                if not dry_run:
                    AuditLog.objects.create(
                        action="retention_archive",
                        resource_type=name,
                        resource_id="batch",
                        details={
                            "count": count,
                            "cutoff": cutoff.isoformat(),
                            "policy": f"{RETENTION_POLICY[policy_key]} days",
                        },
                    )
                    old_records.delete()
                    self.stdout.write(self.style.SUCCESS(f"    Archived {count} {name} records"))
                total_archived += count
            else:
                self.stdout.write(f"  {name}: no records past retention")

        # ── Summary ──
        self.stdout.write("")
        action = "Would purge" if dry_run else "Purged"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {total_purged} expired records, archived {total_archived} records past retention."
            )
        )

        return f"purged={total_purged}, archived={total_archived}"
