import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.loans.tasks.enforce_data_retention")
def enforce_data_retention():
    """Weekly task: enforce data retention policy per regulatory requirements."""
    import io

    from django.core.management import call_command

    out = io.StringIO()
    try:
        call_command("enforce_retention", stdout=out)
        logger.info("data_retention_cleanup completed: %s", out.getvalue().strip())
    except Exception:
        logger.exception("data_retention_cleanup task failed")
        raise


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

        # Only delete the durable row once the app DEMONSTRABLY left QUEUE_FAILED.
        # .delay() not raising doesn't prove the broker enqueued the task, so we
        # condition the delete on the guarded transition actually matching a row.
        rows = LoanApplication.objects.filter(
            pk=application_id,
            status=LoanApplication.Status.QUEUE_FAILED,
        ).update(status=LoanApplication.Status.PENDING)

        if rows == 1:
            entry.delete()
            logger.info("Outbox recovered dispatch for %s", application_id)
            recovered += 1
        else:
            # App was not in QUEUE_FAILED (already moved, or the dispatch did not
            # take) — keep the durable row and count it as a non-recovery so the
            # exhausted-alert path can still eventually fire (L23).
            entry.attempts += 1
            entry.last_error = "Dispatch returned but application did not leave QUEUE_FAILED"
            entry.last_attempt_at = timezone.now()
            entry.save(update_fields=["attempts", "last_error", "last_attempt_at"])
            logger.warning("Outbox kept row for %s — status did not transition", application_id)
            failed += 1

    exhausted = PipelineDispatchOutbox.objects.filter(
        attempts__gte=PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS
    ).count()
    if exhausted:
        logger.error(
            "Outbox has %d entries at or above max attempts — operator intervention required",
            exhausted,
        )

    return {"recovered": recovered, "failed": failed, "exhausted": exhausted}
