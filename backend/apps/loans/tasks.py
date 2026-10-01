import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def dispatch_pipeline_or_queue_failed(application, *, source: str) -> None:
    """Enqueue the orchestrator for a new application, with an outbox fallback.

    Registered via ``transaction.on_commit`` by both the API (``perform_create``)
    and the Django admin, so it must never raise: there is no recovery path
    after the response. On a broker failure the application is recorded in
    PipelineDispatchOutbox (drained by ``retry_failed_dispatches``) and flipped
    to QUEUE_FAILED so the dashboard surfaces it. The outbox write and the
    status flip each get their own try/except so a failure in one (e.g. a DB
    lock on the outbox table) doesn't prevent the other.
    """
    # Call-time import: tests patch apps.agents.tasks.orchestrate_pipeline_task.
    from apps.agents.tasks import orchestrate_pipeline_task
    from apps.loans.models import LoanApplication, PipelineDispatchOutbox

    try:
        orchestrate_pipeline_task.delay(str(application.pk))
        logger.info("Pipeline dispatched (%s) for application %s", source, application.pk)
        return
    except Exception as exc:
        logger.error(
            "Failed to dispatch pipeline (%s) for %s: %s — queued to outbox",
            source,
            application.pk,
            exc,
        )
        error = str(exc)[:1000]

    try:
        PipelineDispatchOutbox.objects.get_or_create(application=application, defaults={"last_error": error})
    except Exception as outbox_exc:
        logger.exception("Failed to record PipelineDispatchOutbox row for %s: %s", application.pk, outbox_exc)
    try:
        LoanApplication.objects.filter(pk=application.pk).update(status=LoanApplication.Status.QUEUE_FAILED)
    except Exception as status_exc:
        logger.exception("Failed to flip status to QUEUE_FAILED for %s: %s", application.pk, status_exc)


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
    PENDING. On failure the attempt count is incremented and the error is
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
            # exhausted-alert path can still eventually fire.
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
