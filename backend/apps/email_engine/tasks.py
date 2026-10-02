import logging
from datetime import timedelta

from celery import shared_task
from celery.exceptions import Retry, SoftTimeLimitExceeded
from django.db.models import Count, Q
from django.utils import timezone

from apps.common.tasks import task_dedup_lock
from apps.email_engine.models import GeneratedEmail, GuardrailAnalytics, GuardrailLog
from apps.email_engine.services.decision_email import (
    HeldForBiasReview,
    bias_hold_reason,
    deliver_decision_email,
    generate_decision_email,
    require_decision_on_record,
)
from apps.email_engine.services.exceptions import RateLimited
from apps.loans.models import AuditLog, LoanApplication

logger = logging.getLogger("email_engine.tasks")


def _email_context(application, decision):
    """Same next-best offer the orchestrator gives a denial (no API call, best-effort)."""
    if decision != "denied":
        return None
    # Imported here: email_engine does not import the agents app at module level.
    from apps.agents.services.email_pipeline import build_denial_email_context

    return build_denial_email_context(application, None)


# Infrastructure errors Celery retries (ConnectionError and TimeoutError are
# OSErrors). The dedup lock is kept across them and across the RateLimited
# retry, as the orchestrate task keeps its lock (M22).
_AUTORETRY = (OSError,)
_EMAIL_TIME_LIMIT = 120
# The longest wait before a retry: a provider's Retry-After is capped here, and
# the autoretry backoff (1, 2, 4 s) stays far below it.
_MAX_RETRY_COUNTDOWN = 300
# A retry refreshes the lock when it starts, so the lock has to outlive one run
# plus the longest countdown before the retry, with a minute for queueing.
_EMAIL_LOCK_TTL = _EMAIL_TIME_LIMIT + _MAX_RETRY_COUNTDOWN + 60


def _email_lock_key(application_id, decision):
    return f"generate_email_lock:{application_id}:{decision}"


@shared_task(
    bind=True,
    name="apps.email_engine.tasks.generate_email_task",
    time_limit=_EMAIL_TIME_LIMIT,
    soft_time_limit=100,
    autoretry_for=_AUTORETRY,
    retry_backoff=True,
    retry_backoff_max=_MAX_RETRY_COUNTDOWN,
    max_retries=3,
)
def generate_email_task(self, application_id, decision, regenerate=False):
    """Generate and send the decision email for a loan application.

    Refuses (DecisionMismatch, not retried) when ``decision`` disagrees with
    the application's LoanDecision, whoever the caller is.

    ``regenerate=True`` always writes a fresh email instead of re-delivering
    the latest stored one.

    Refuses (HeldForBiasReview, not retried) while the application is under
    human review, and never re-delivers a draft the bias check held back:
    only the human-review paths, which re-run the bias check, release those.

    Every email it sends is bias-checked first, as in the pipeline: a flagged
    email is replaced by the template, and a severe finding (or a flagged
    template) holds the email unsent (``held_reason`` in the result).

    One run at a time per application and decision: the "is there an email
    already" check has no row to lock before the first email exists, so two
    concurrent runs (a staff Generate during a redelivery, a double click)
    would each generate and send one. A run that finds the lock held by
    another task skips.
    """
    lock = task_dedup_lock(
        _email_lock_key(application_id, decision), self.request.id, _EMAIL_LOCK_TTL, keep_on=(*_AUTORETRY, Retry)
    )
    with lock as held:
        if not held:
            logger.info("Application %s (%s): email task already running, skipping", application_id, decision)
            return {"skipped": True, "reason": "dedup_lock_held"}
        return _generate_and_send(self, application_id, decision, regenerate)


def _generate_and_send(task, application_id, decision, regenerate):
    """The body of ``generate_email_task``, run under its dedup lock."""
    # Imported here: email_engine does not import the agents app at module level.
    from apps.agents.services.decision_email_screening import screen_and_deliver_decision_email

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
    hold = bias_hold_reason(application_id, existing)
    if hold:
        raise HeldForBiasReview(hold)
    if existing:
        if existing.passed_guardrails and existing.sent_at is None:
            # Generated but never delivered (transient SMTP failure, or a worker
            # killed after persist-before-send). Attempt delivery now using the
            # stored subject/body instead of returning 'done' — the row-locked
            # send is idempotent, so this cannot double-send under a redelivery race.
            if existing.bias_reports.exists():
                outcome = deliver_decision_email(existing)
                delivered = outcome["sent"] or outcome["already_sent"]
            else:
                # Never bias-checked (the bias check was down, or the worker died
                # before it ran): screen it like a freshly generated email.
                application = existing.application
                outcome = screen_and_deliver_decision_email(
                    application,
                    decision,
                    {
                        "body": existing.body,
                        "passed_guardrails": existing.passed_guardrails,
                        "template_fallback": existing.template_fallback,
                    },
                    existing,
                    profile_context=_email_context(application, decision),
                )
                delivered = outcome["sent"]
                existing = outcome["generated_email"]
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
    profile_context = _email_context(application, decision)

    try:
        # on_rate_limit="raise": this task can reschedule itself, so a 429
        # retries the LLM later instead of taking the template now.
        result, email = generate_decision_email(
            application, decision, profile_context=profile_context, on_rate_limit="raise"
        )
    except _AUTORETRY:
        raise  # let Celery autoretry handle infrastructure errors
    except RateLimited as exc:
        # The generator raises RateLimited on a 429 instead of sleeping; free the
        # worker by scheduling a Celery retry instead of holding it inside time_limit.
        raise task.retry(countdown=min(exc.retry_after, _MAX_RETRY_COUNTDOWN), exc=exc) from exc
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

    # Bias-check it as the pipeline does, then send it (or the template that
    # replaced a flagged email) once, under a row lock, with sent_at stamped.
    # A held email stays unsent with its flagged bias report.
    outcome = screen_and_deliver_decision_email(application, decision, result, email, profile_context=profile_context)
    email_sent = outcome["sent"]
    email = outcome["generated_email"]

    # Audit trail: log email generation/delivery
    AuditLog.objects.create(
        action="email_sent" if email_sent else "email_generated",
        resource_type="GeneratedEmail",
        resource_id=str(email.id),
        details={
            "decision": decision,
            "passed_guardrails": email.passed_guardrails,
            "attempt_number": email.attempt_number,
            "email_sent": email_sent,
            "template_fallback": email.template_fallback,
            "held_reason": outcome["held_reason"],
        },
    )

    return {
        "email_id": str(email.id),
        "subject": email.subject,
        "passed_guardrails": email.passed_guardrails,
        "attempt_number": email.attempt_number,
        "email_sent": email_sent,
        "held_reason": outcome["held_reason"],
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
