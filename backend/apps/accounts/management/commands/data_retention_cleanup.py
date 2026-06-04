"""Archive/purge customer data beyond the 7-year retention period.

Australian Privacy Act 1988, APP 11.2: personal information that is no longer
needed for any purpose must be destroyed or de-identified.

Banking records are retained for 7 years per AML/CTF Act 2006 (s 112).
After 7 years, PII is de-identified while preserving aggregated analytics.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CustomerProfile, CustomUser
from apps.loans.models import AuditLog


class Command(BaseCommand):
    help = "Archive/purge customer data beyond 7-year retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be cleaned up without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=7 * 365)

        self.stdout.write(f"Retention cutoff: {cutoff.date()}")

        # Find users with no activity since cutoff. API-registered users
        # authenticate via JWT and never hit Django's login(), so last_login
        # stays NULL forever — keying staleness on last_login alone would retain
        # their PII indefinitely. Treat a NULL last_login as eligible once the
        # account itself (created_at) predates the cutoff.
        stale_users = (
            CustomUser.objects.filter(role="customer")
            .filter(Q(last_login__lt=cutoff) | Q(last_login__isnull=True, created_at__lt=cutoff))
            .exclude(loan_applications__created_at__gte=cutoff)
        )

        count = stale_users.count()
        self.stdout.write(f"Found {count} customer accounts older than 7 years.")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes made."))
            return

        # De-identify PII in profiles (preserve aggregated data)
        profiles = CustomerProfile.objects.filter(user__in=stale_users)
        deidentified = 0
        with transaction.atomic():
            for profile in profiles.iterator(chunk_size=100):
                profile.phone = ""
                profile.address_line_1 = "REDACTED"
                profile.address_line_2 = ""
                profile.primary_id_number = ""
                profile.secondary_id_number = ""
                profile.employer_name = ""
                profile.occupation = ""
                profile.save(
                    update_fields=[
                        "phone",
                        "address_line_1",
                        "address_line_2",
                        "primary_id_number",
                        "secondary_id_number",
                        "employer_name",
                        "occupation",
                    ]
                )
                deidentified += 1

            # De-identify user records and write an AuditLog entry for each
            for user in stale_users.iterator(chunk_size=100):
                user.first_name = "REDACTED"
                user.last_name = ""
                user.email = f"redacted_{user.pk}@deidentified.local"
                user.phone = ""
                user.is_active = False
                user.save(
                    update_fields=[
                        "first_name",
                        "last_name",
                        "email",
                        "phone",
                        "is_active",
                    ]
                )
                AuditLog.objects.create(
                    user=None,  # system action — no acting officer
                    action="data_retention_cleanup",
                    resource_type="CustomUser",
                    resource_id=str(user.pk),
                    details={"detail": "PII de-identified per retention policy"},
                )

        self.stdout.write(
            self.style.SUCCESS(f"Done. De-identified {deidentified} profiles, {count} user accounts marked inactive.")
        )
