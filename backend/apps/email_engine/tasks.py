import logging
from datetime import timedelta

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import Count, Q
from django.utils import timezone

from apps.email_engine.models import GeneratedEmail, GuardrailAnalytics, GuardrailLog
from apps.email_engine.services.decision_email import (
    deliver_decision_email,
    generate_decision_email,
    require_decision_on_record,
)
from apps.email_engine.services.exceptions import RateLimited
from apps.loans.models import AuditLog, LoanApplication

logger = logging.getLogger("email_engine.tasks")


@shared_task(
    bind=True,
    name="apps.email_engine.tasks.generate_email_task",
    time_limit=120,
    soft_time_limit=100,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=3,
)
def generate_email_task(self, application_id, decision, regenerate=False):
    """Generate and send the decision email for a loan application.

    Refuses (DecisionMismatch, not retried) when ``decision`` disagrees with
    the application's LoanDecision, whoever the caller is.

    ``regenerate=True`` always writes a fresh email instead of re-delivering
    the latest stored one (used after a human-review outcome, where the stored
    draft may be the one the review held back).
    """
    require_decision_on_record(application_id, decision)

    # Idempotency: if email already generated for this application+decision, return it.
    # Report the TRUE sent state from the sent_at marker so callers don't think an
    # already-delivered email still needs sending on a redelivery.
    existing = None
    if not regenerate:
        existing = (
            GeneratedEmail.objects.filter(application_id=application_id, decision=decision)
            .select_related("application__applicant")
            .order_by("-created_at")
            .first()
        )
    if existing:
        if existing.passed_guardrails and existing.sent_at is None:
            # Generated but never delivered (transient SMTP failure, or a worker
            # killed after persist-before-send). Attempt delivery now using the
            # stored subject/body instead of returning 'done' — the row-locked
            # send is idempotent, so this cannot double-send under a redelivery race.
            outcome = deliver_decision_email(existing)
            delivered = outcome["sent"] or outcome["already_sent"]
            logger.info(
                "Redelivery for application %s (%s): generated-but-unsent email send attempted (delivered=%s)",
                application_id,
                decision,
                delivered,
            )
            AuditLog.objects.create(
                action="email_sent" if delivered else "email_generated",
                resource_type="GeneratedEmail",
                resource_id=str(existing.id),
                details={
                    "decision": decision,
                    "passed_guardrails": existing.passed_guardrails,
                    "attempt_number": existing.attempt_number,
                    "email_sent": delivered,
                    "redelivery": True,
                },
            )
            return {
                "email_id": str(existing.id),
                "subject": existing.subject,
                "passed_guardrails": existing.passed_guardrails,
                "attempt_number": existing.attempt_number,
                "email_sent": delivered,
            }

        logger.info("Email already exists for application %s (%s), skipping generation", application_id, decision)
        return {
            "email_id": str(existing.id),
            "subject": existing.subject,
            "passed_guardrails": existing.passed_guardrails,
            "attempt_number": existing.attempt_number,
            "email_sent": existing.sent_at is not None,
        }

    application = LoanApplication.objects.select_related("applicant", "decision").get(pk=application_id)

    try:
        # on_rate_limit="raise": this task can reschedule itself, so a 429
        # retries the LLM later instead of taking the template now.
        result, email = generate_decision_email(application, decision, on_rate_limit="raise")
    except (ConnectionError, TimeoutError, OSError):
        raise  # let Celery autoretry handle infrastructure errors
    except RateLimited as exc:
        # The generator raises RateLimited on a 429 instead of sleeping; free the
        # worker by scheduling a Celery retry instead of holding it inside time_limit.
        raise self.retry(countdown=exc.retry_after, exc=exc) from exc
    except SoftTimeLimitExceeded:
        AuditLog.objects.create(
            action="email_generation_timeout",
            resource_type="LoanApplication",
            resource_id=str(application_id),
            details={"decision": decision},
        )
        raise
    except Exception as exc:
        logger.exception("Email generation failed for application %s", application_id)
        AuditLog.objects.create(
            action="email_generation_failed",
            resource_type="LoanApplication",
            resource_id=str(application_id),
            details={"error": str(exc), "decision": decision},
        )
        raise

    # Send to the customer if guardrails passed: once, under a row lock, with
    # sent_at stamped on success (see deliver_decision_email).
    email_sent = False
    if result["passed_guardrails"]:
        email_sent = deliver_decision_email(email)["sent"]

    # Audit trail: log email generation/delivery
    AuditLog.objects.create(
        action="email_sent" if email_sent else "email_generated",
        resource_type="GeneratedEmail",
        resource_id=str(email.id),
        details={
            "decision": decision,
            "passed_guardrails": result["passed_guardrails"],
            "attempt_number": result["attempt_number"],
            "email_sent": email_sent,
            "template_fallback": result.get("template_fallback", False),
        },
    )

    return {
        "email_id": str(email.id),
        "subject": result["subject"],
        "passed_guardrails": result["passed_guardrails"],
        "attempt_number": result["attempt_number"],
        "email_sent": email_sent,
    }


@shared_task(name="apps.email_engine.tasks.compute_guardrail_analytics")
def compute_guardrail_analytics():
    """Weekly task computing per-check pass/fail rates and retry rate trends."""
    now = timezone.now()
    week_start = (now - timedelta(days=7)).date()
    week_end = now.date()

    # Aggregate guardrail results at the DB level — avoids loading all rows into
    # Python memory.
    analytics_qs = (
        GuardrailLog.objects.filter(
            created_at__date__gte=week_start,
            created_at__date__lt=week_end,
        )
        .values("check_name")
        .annotate(
            total=Count("id"),
            passed=Count("id", filter=Q(passed=True)),
            failed=Count("id", filter=Q(passed=False)),
        )
        .order_by("check_name")
    )

    # Retry rate: share of the week's emails that needed more than one attempt.
    email_counts = GeneratedEmail.objects.filter(
        created_at__date__gte=week_start,
        created_at__date__lt=week_end,
    ).aggregate(total=Count("id"), retried=Count("id", filter=Q(attempt_number__gt=1)))
    total_emails = email_counts["total"]
    retry_rate = email_counts["retried"] / total_emails if total_emails > 0 else 0.0

    created = 0
    for row in analytics_qs:
        pass_rate = row["passed"] / row["total"] if row["total"] > 0 else 0.0
        GuardrailAnalytics.objects.update_or_create(
            week_start=week_start,
            check_name=row["check_name"],
            defaults={
                "total_runs": row["total"],
                "pass_count": row["passed"],
                "fail_count": row["failed"],
                "pass_rate": pass_rate,
                "retry_rate": retry_rate,
            },
        )
        created += 1

    logger.info(
        "Guardrail analytics computed for week %s: %d checks, %.1f%% retry rate",
        week_start,
        created,
        retry_rate * 100,
    )
    return {"week_start": str(week_start), "checks": created, "retry_rate": retry_rate}
