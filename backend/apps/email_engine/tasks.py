import logging
from datetime import timedelta

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
from django.utils import timezone

from apps.email_engine.models import GeneratedEmail, GuardrailAnalytics, GuardrailLog
from apps.email_engine.services.exceptions import RateLimited
from apps.email_engine.services.persistence import EmailPersistenceService
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
def generate_email_task(self, application_id, decision):
    """Generate a decision email for a loan application."""
    from apps.email_engine.services.email_generator import EmailGenerator

    # Idempotency: if email already generated for this application+decision, return it.
    # Report the TRUE sent state from the sent_at marker so callers don't think an
    # already-delivered email still needs sending on a redelivery.
    existing = (
        GeneratedEmail.objects.filter(application_id=application_id, decision=decision).order_by("-created_at").first()
    )
    if existing:
        logger.info("Email already exists for application %s (%s), skipping generation", application_id, decision)
        return {
            "email_id": str(existing.id),
            "subject": existing.subject,
            "passed_guardrails": existing.passed_guardrails,
            "attempt_number": existing.attempt_number,
            "email_sent": existing.sent_at is not None,
        }

    application = LoanApplication.objects.select_related("applicant", "decision").get(pk=application_id)

    generator = EmailGenerator()
    try:
        result = generator.generate(application, decision)
    except (ConnectionError, TimeoutError, OSError):
        raise  # let Celery autoretry handle infrastructure errors
    except RateLimited as exc:
        # The generator no longer blocks on time.sleep for 429s. Free the worker
        # by scheduling a Celery retry instead of holding it inside time_limit.
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

    # Save email record and guardrail logs
    email = EmailPersistenceService.save_generated_email(application, decision, result)
    EmailPersistenceService.save_guardrail_logs(email, result.get("guardrail_results", []))

    # Send email to customer if guardrails passed. The send is idempotent: under
    # a row lock we only send when sent_at is unset, then persist sent_at. This
    # closes the acks_late window where a SIGKILLed-then-redelivered task could
    # otherwise send a second decision email (M6).
    email_sent = False
    if result["passed_guardrails"] and application.applicant.email:
        with transaction.atomic():
            locked = GeneratedEmail.objects.select_for_update().get(pk=email.pk)
            if locked.sent_at is None:
                from apps.email_engine.services.sender import send_decision_email

                send_result = send_decision_email(
                    recipient_email=application.applicant.email,
                    subject=result["subject"],
                    body=result["body"],
                    email_type="approval" if decision == "approved" else "denial",
                )
                if send_result.get("sent"):
                    locked.sent_at = timezone.now()
                    locked.save(update_fields=["sent_at"])
                    email_sent = True

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

    # Get all guardrail logs from the past week
    logs = GuardrailLog.objects.filter(
        created_at__date__gte=week_start,
        created_at__date__lt=week_end,
    ).values("check_name", "passed")

    # Aggregate by check_name
    from collections import defaultdict

    stats = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for log in logs:
        name = log["check_name"]
        stats[name]["total"] += 1
        if log["passed"]:
            stats[name]["passed"] += 1
        else:
            stats[name]["failed"] += 1

    # Compute retry rate (emails with attempt_number > 1)
    total_emails = GeneratedEmail.objects.filter(
        created_at__date__gte=week_start,
        created_at__date__lt=week_end,
    ).count()
    retried_emails = GeneratedEmail.objects.filter(
        created_at__date__gte=week_start,
        created_at__date__lt=week_end,
        attempt_number__gt=1,
    ).count()
    retry_rate = retried_emails / total_emails if total_emails > 0 else 0.0

    # Save analytics
    created = 0
    for check_name, data in stats.items():
        pass_rate = data["passed"] / data["total"] if data["total"] > 0 else 0.0
        GuardrailAnalytics.objects.update_or_create(
            week_start=week_start,
            check_name=check_name,
            defaults={
                "total_runs": data["total"],
                "pass_count": data["passed"],
                "fail_count": data["failed"],
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
