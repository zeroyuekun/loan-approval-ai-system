"""De-identify customer PII 7 years after the customer's last loan closed.

Australian Privacy Act 1988, APP 11.2: personal information that is no longer
needed for any purpose must be destroyed or de-identified. Banking records are
retained for 7 years after the relationship ends (AML/CTF Act 2006, ss 107,
112), so eligibility is keyed on loan closure, not on when the account or the
application was created: a customer 8 years into a 25-year home loan is still
a customer.

Loan closure, per application (there is no settlement/closure record yet):
- approved: the end of the loan term (created_at + loan_term_months);
- anything else (declined, withdrawn, abandoned): its last update.

De-identified: every EncryptedCharField on the profile (DOB, phone, address,
ID numbers, employer, incomes) plus the plain-text location, employment and
income-source fields; the user's username, name, email and phone (account
deactivated); application free text; decision and marketing email
subject/body/prompt; the customer's complaints and decision-review requests;
next-best-offer text; pipeline step summaries; bias-report analysis and
guardrail details. Decision facts (amounts, scores, outcomes, step names and
timings) stay for aggregate analytics.

Account activity: login and token refresh record last_login, so a customer
who still signs in is not treated as closed.

Runs weekly from apps.loans.tasks.enforce_data_retention. Idempotent:
CustomUser.deidentified_at marks a processed user (never the email domain,
which the user can set).

Not covered: AuditLog details written before this change can hold a
username (e.g. ``register``). The audit chain hashes details, so scrubbing
them would break verification; that needs a chain-aware redaction design.
"""

import calendar
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.fields import EncryptedCharField
from apps.accounts.models import CustomerProfile, CustomUser
from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.loans.models import AuditLog, Complaint, DecisionReview, LoanApplication

RETENTION = timedelta(days=7 * 365)
DEIDENTIFIED_EMAIL_DOMAIN = "deidentified.local"
REDACTED_TEXT = "[de-identified after the retention period]"

# Plain-text profile fields that identify a person (the encrypted ones are
# found from the model, so a new EncryptedCharField is covered automatically).
PROFILE_PLAIN_PII_FIELDS = (
    "suburb",
    "postcode",
    "occupation",
    "previous_employer",
    "previous_suburb",
    "previous_state",
    "previous_postcode",
    "other_income_source",
)
APPLICATION_FREE_TEXT_FIELDS = ("notes", "consumer_objectives", "consumer_requirements", "financial_situation_notes")


def _add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def loan_closure_date(application):
    if application.status == LoanApplication.Status.APPROVED:
        return _add_months(application.created_at, application.loan_term_months or 0)
    return application.updated_at


def _profile_pii_fields():
    encrypted = [f.name for f in CustomerProfile._meta.concrete_fields if isinstance(f, EncryptedCharField)]
    return encrypted + list(PROFILE_PLAIN_PII_FIELDS)


class Command(BaseCommand):
    help = "De-identify customer PII 7 years after the customer's last loan closed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be cleaned up without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - RETENTION
        self.stdout.write(f"Retention cutoff: {cutoff.date()}")

        # Account-level staleness first (cheap, in SQL). Login and refresh set
        # last_login; a NULL (never signed in) falls back to created_at.
        candidates = CustomUser.objects.filter(role="customer", deidentified_at__isnull=True).filter(
            Q(last_login__lt=cutoff) | Q(last_login__isnull=True, created_at__lt=cutoff)
        )

        eligible = []
        for user in candidates.iterator(chunk_size=100):
            applications = LoanApplication.all_objects.all_with_deleted().filter(applicant=user)
            if all(loan_closure_date(app) < cutoff for app in applications):
                eligible.append(user)

        self.stdout.write(f"Found {len(eligible)} customer account(s) closed for more than 7 years.")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes made."))
            return

        for user in eligible:
            # One transaction per user: the audit chain lock is not held
            # across the whole batch.
            with transaction.atomic():
                self._deidentify(user)

        self.stdout.write(self.style.SUCCESS(f"Done. De-identified {len(eligible)} customer account(s)."))

    def _deidentify(self, user):
        profile_fields = _profile_pii_fields()
        profiles = CustomerProfile.all_objects.all_with_deleted().filter(user=user)
        for profile in profiles:
            for name in profile_fields:
                setattr(profile, name, "")
            profile.save(update_fields=profile_fields)

        applications = LoanApplication.all_objects.all_with_deleted().filter(applicant=user)
        app_ids = list(applications.values_list("pk", flat=True))
        applications.update(**dict.fromkeys(APPLICATION_FREE_TEXT_FIELDS, ""))
        emails = GeneratedEmail.objects.filter(application_id__in=app_ids).update(
            subject=REDACTED_TEXT[:200], body=REDACTED_TEXT, prompt_used=""
        )
        marketing = MarketingEmail.objects.filter(application_id__in=app_ids).update(
            subject=REDACTED_TEXT[:200], body=REDACTED_TEXT, prompt_used=""
        )
        Complaint.objects.filter(Q(complainant=user) | Q(loan_application_id__in=app_ids)).update(
            subject=REDACTED_TEXT[:200], description=REDACTED_TEXT, resolution=""
        )
        DecisionReview.objects.filter(application_id__in=app_ids).update(reason=REDACTED_TEXT, resolution_note="")
        NextBestOffer.objects.filter(application_id__in=app_ids).update(
            analysis=REDACTED_TEXT, personalized_message="", marketing_message=""
        )
        BiasReport.objects.filter(agent_run__application_id__in=app_ids).update(analysis=REDACTED_TEXT)
        GuardrailLog.objects.filter(email__application_id__in=app_ids).update(details="")
        # Step summaries can quote the email (subject, findings); keep the
        # step names, statuses and timings the SLA metrics read.
        for run in AgentRun.objects.filter(application_id__in=app_ids).only("pk", "steps"):
            steps = [{k: v for k, v in step.items() if k != "result_summary"} for step in (run.steps or [])]
            AgentRun.objects.filter(pk=run.pk).update(steps=steps)

        user.username = f"deidentified_{user.pk}"
        user.first_name = "REDACTED"
        user.last_name = ""
        user.email = f"redacted_{user.pk}@{DEIDENTIFIED_EMAIL_DOMAIN}"
        user.phone = ""
        user.is_active = False
        user.deidentified_at = timezone.now()
        user.save(
            update_fields=["username", "first_name", "last_name", "email", "phone", "is_active", "deidentified_at"]
        )

        AuditLog.objects.create(
            user=None,  # system action — no acting officer
            action="data_retention_cleanup",
            resource_type="CustomUser",
            resource_id=str(user.pk),
            details={
                "detail": "PII de-identified per retention policy",
                "applications": len(app_ids),
                "emails": emails,
                "marketing_emails": marketing,
            },
        )
