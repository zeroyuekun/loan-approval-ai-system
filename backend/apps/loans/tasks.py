import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.loans.tasks.enforce_data_retention")
def enforce_data_retention():
    """Weekly task: enforce data retention policy per regulatory requirements."""
    from django.core.management import call_command

    output = call_command("enforce_retention")
    logger.info("Data retention enforcement completed: %s", output)
    return output


@shared_task(name="apps.loans.tasks.retry_failed_dispatches")
def retry_failed_dispatches() -> dict:
    """Drain the PipelineDispatchOutbox — runs on a 60s beat schedule.

    For each row below MAX_DISPATCH_ATTEMPTS, attempt to re-queue the pipeline
    task. On success the row is deleted and the loan transitions back to
    submitted. On failure the attempt count is incremented and the error is
    recorded; once MAX_DISPATCH_ATTEMPTS is reached the row is kept for
    operator visibility but the automated loop stops retrying.
    """
    from apps.agents.tasks import orchestrate_pipeline_task
    from apps.loans.models import LoanApplication, PipelineDispatchOutbox

    pending = PipelineDispatchOutbox.objects.filter(
        attempts__lt=PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS
    ).select_related("application")

    recovered = 0
    failed = 0

    for entry in pending:
        application_id = entry.application_id
        try:
            orchestrate_pipeline_task.delay(str(application_id))
        except Exception as exc:
            entry.attempts += 1
            entry.last_error = str(exc)[:1000]
            entry.last_attempt_at = timezone.now()
            entry.save(update_fields=["attempts", "last_error", "last_attempt_at"])
            logger.warning(
                "Outbox retry failed for %s (attempt %d/%d): %s",
                application_id,
                entry.attempts,
                PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS,
                exc,
            )
            failed += 1
            continue

        LoanApplication.objects.filter(
            pk=application_id,
            status=LoanApplication.Status.QUEUE_FAILED,
        ).update(status=LoanApplication.Status.PENDING)
        entry.delete()
        logger.info("Outbox recovered dispatch for %s", application_id)
        recovered += 1

    exhausted = PipelineDispatchOutbox.objects.filter(
        attempts__gte=PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS
    ).count()
    if exhausted:
        logger.error(
            "Outbox has %d entries at or above max attempts — operator intervention required",
            exhausted,
        )

    return {"recovered": recovered, "failed": failed, "exhausted": exhausted}
