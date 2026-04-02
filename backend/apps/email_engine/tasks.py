import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.email_engine.models import GeneratedEmail, GuardrailAnalytics, GuardrailLog
from apps.email_engine.services.persistence import EmailPersistenceService
from apps.loans.models import LoanApplication

logger = logging.getLogger("email_engine.tasks")


@shared_task(
    bind=True,
    name="apps.email_engine.tasks.generate_email_task",
    time_limit=120,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=3,
)
def generate_email_task(self, application_id, decision):
    """Generate a decision email for a loan application."""
    from apps.email_engine.services.email_generator import EmailGenerator

    application = LoanApplication.objects.select_related("applicant", "decision").get(pk=application_id)

    generator = EmailGenerator()
    try:
        result = generator.generate(application, decision)
    except (ConnectionError, TimeoutError, OSError):
        raise  # let Celery autoretry handle infrastructure errors
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

    # Send email to customer if guardrails passed
    email_sent = False
    if result["passed_guardrails"] and application.applicant.email:
        from apps.email_engine.services.sender import send_decision_email

        email_sent = send_decision_email(
            recipient_email=application.applicant.email,
            subject=result["subject"],
            body=result["body"],
        )

    # Audit trail: log email generation/delivery
    from apps.loans.models import AuditLog

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
