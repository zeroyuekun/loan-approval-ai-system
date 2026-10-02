import logging
from datetime import timedelta

from celery import Task, shared_task
from django.core.cache import cache
from django.db import transaction

from apps.common.tasks import task_dedup_lock

logger = logging.getLogger("agents.tasks")


def _lock_key(application_id):
    """Single source of truth for the orchestrate dedup-lock cache key."""
    return f"orchestrate_lock:{application_id}"


class _OrchestrateTask(Task):
    """Custom Task base that releases the dedup lock on terminal failure.

    When ``autoretry_for`` retries are exhausted Celery calls ``on_failure``
    on the task instance.  At that point ``self.request.retries`` equals
    ``self.max_retries``, indicating terminal (non-recoverable) failure.

    The dedup lock is intentionally kept alive DURING retries (M22 — prevents
    a race between the retry and a duplicate orchestration).  Only the terminal
    failure path releases it here, so the lock is not held for the full TTL
    (~600 s) after the task gives up.
    """

    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # Celery calls on_failure only for a TERMINAL failure: a scheduled
        # autoretry goes through on_retry, so the lock stays held across
        # retries without a check here. A non-retryable error on retry 1 is
        # terminal too, so no retries >= max_retries guard (it used to leave
        # the application in PROCESSING).
        application_id = args[0] if args else kwargs.get("application_id")
        if application_id:
            # Reset the stuck-PROCESSING application (the helper logs and
            # swallows its own errors), then release the lock.
            _cleanup_stuck_application(application_id)
            cache.delete(_lock_key(application_id))
            logger.warning("Application %s: dedup lock released after terminal failure", application_id)
        # Explicit base-class call so unit tests can instantiate this class
        # directly without Celery's full task machinery.
        Task.on_failure(self, exc, task_id, args, kwargs, einfo)


# Redis dedup lock TTL — slightly longer than the task soft time limit
_DEDUP_LOCK_TTL = 600
# Infrastructure errors Celery retries (ConnectionError and TimeoutError are
# OSErrors). The orchestrate dedup lock is kept across them (M22).
_AUTORETRY = (OSError,)


_STUCK_RESET_REASON = "Pipeline task died or timed out mid-run; reset to pending so staff can re-run it"
_STUCK_AFTER_DELIVERY_REASON = (
    "Pipeline task died or timed out after the decision email was sent; the decision it announced was applied"
)


def _cleanup_stuck_application(application_id, clear_lock=False):
    """Reset a stuck-'processing' application to PENDING under a row lock.

    Unless the latest run already sent the decision email: then the decision
    that email announced is applied instead and the run is marked completed,
    because a re-run from PENDING would email the customer a second decision.

    PENDING, not REVIEW: the human review queue is only for bias flags, and a
    dead task is not a bias finding. PENDING is re-runnable (the batch
    orchestrate endpoint and a forced re-run both pick it up); the reason is
    recorded on the status_transition AuditLog and the failed AgentRun.

    No-ops if the application's latest AgentRun is COMPLETED
    (another actor owns the work), so the watchdog, the orchestrator
    stale-reset, and Celery autoretry cannot fight over the same state (L22).

    When ``clear_lock`` is True the Redis dedup lock is released too — used by
    the watchdog's revoke path so a legitimate retry isn't starved behind a
    still-held lock.
    """
    try:
        from apps.agents.models import AgentRun
        from apps.email_engine.models import GeneratedEmail
        from apps.loans.models import LoanApplication

        with transaction.atomic():
            # Lock by pk — never via a nullable profile join (FOR UPDATE caveat).
            app = (
                LoanApplication.objects.select_for_update()
                .filter(pk=application_id, status=LoanApplication.Status.PROCESSING)
                .first()
            )
            if app is None:
                return  # not stuck, or already moved on

            # Another actor owns the work if the latest run completed.
            latest = AgentRun.objects.only("status", "created_at").latest_for(application_id)
            if latest is not None and latest.status == AgentRun.Status.COMPLETED:
                logger.info("Application %s: cleanup skipped, a completed run owns it", application_id)
                return

            # The run died after it sent the decision email (in the NBO or
            # marketing follow-up): the customer has the decision, so apply it.
            # PENDING would let a re-run email them a second decision.
            delivered = None
            if latest is not None:
                delivered = (
                    GeneratedEmail.objects.filter(
                        application_id=application_id,
                        sent_at__isnull=False,
                        created_at__gte=latest.created_at,
                        decision__in=(LoanApplication.Status.APPROVED, LoanApplication.Status.DENIED),
                    )
                    .order_by("-sent_at")
                    .values_list("decision", flat=True)
                    .first()
                )
            if delivered:
                run_status, target, reason = AgentRun.Status.COMPLETED, delivered, _STUCK_AFTER_DELIVERY_REASON
            else:
                run_status, target, reason = AgentRun.Status.FAILED, LoanApplication.Status.PENDING, _STUCK_RESET_REASON

            AgentRun.objects.filter(
                application_id=application_id,
                status__in=(AgentRun.Status.PENDING, AgentRun.Status.RUNNING),
            ).update(status=run_status, error=reason)

            # processing -> pending/approved/denied are in ALLOWED_TRANSITIONS;
            # route through the state machine so the reset produces a
            # status_transition AuditLog.
            app.transition_to(target, details={"source": "stuck_cleanup", "reason": reason})

        if clear_lock:
            cache.delete(_lock_key(application_id))

        logger.warning("Application %s: cleaned up stuck processing status (now %s)", application_id, target)
    except Exception as e:
        logger.error("Application %s: cleanup failed: %s", application_id, e)


@shared_task(
    bind=True,
    base=_OrchestrateTask,
    name="apps.agents.tasks.orchestrate_pipeline_task",
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
    autoretry_for=_AUTORETRY,
    retry_backoff=True,
    max_retries=3,
)
def orchestrate_pipeline_task(self, application_id, force=False):
    """Run the full loan processing pipeline."""
    from apps.agents.models import AgentRun
    from apps.agents.services.orchestrator import PipelineOrchestrator
    from apps.agents.services.step_tracker import pipeline_deadline

    # Idempotency: skip if the latest run completed (unless force re-run).
    if not force:
        latest = AgentRun.objects.only("status").latest_for(application_id)
        if latest is not None and latest.status == AgentRun.Status.COMPLETED:
            # A completed run owns this application — delegate the idempotent,
            # audited status restore to the orchestrator service (L16). The
            # task stays a thin dispatcher.
            try:
                PipelineOrchestrator().restore_status_from_decision(application_id)
            except Exception as e:
                logger.warning("Application %s: failed to restore status: %s", application_id, e)
            return {"status": "already_completed", "application_id": str(application_id)}

    # Redis dedup lock: prevent concurrent runs for the same application. It is
    # kept across infrastructure-error retries, so a duplicate orchestration
    # cannot start before the retry fires (M22); a terminal failure after the
    # last retry releases it in _OrchestrateTask.on_failure.
    with task_dedup_lock(_lock_key(application_id), self.request.id, _DEDUP_LOCK_TTL, keep_on=_AUTORETRY) as held:
        if not held:
            logger.info("Application %s: dedup lock already held, skipping", application_id)
            return {"skipped": True, "reason": "dedup_lock_held"}
        try:
            orchestrator = PipelineOrchestrator()
            with pipeline_deadline(self.soft_time_limit or _DEDUP_LOCK_TTL):
                agent_run = orchestrator.orchestrate(application_id)
        except _AUTORETRY:
            raise
        except Exception as e:
            # Non-retriable failure: reset the application; the lock is
            # released on the way out so future attempts can run.
            _cleanup_stuck_application(application_id)
            try:
                from apps.loans.models import AuditLog

                AuditLog.objects.create(
                    action="pipeline_failed",
                    resource_type="LoanApplication",
                    resource_id=str(application_id),
                    details={"error": str(e)},
                )
            except Exception:
                logger.warning("Failed to create audit log for pipeline failure on %s", application_id)
            raise

    try:
        from apps.loans.models import AuditLog

        AuditLog.objects.create(
            action="pipeline_completed",
            resource_type="LoanApplication",
            resource_id=str(application_id),
            details={"status": agent_run.status, "agent_run_id": str(agent_run.id)},
        )
    except Exception:
        logger.warning("Failed to create audit log for pipeline completion on %s", application_id)

    return {
        "agent_run_id": str(agent_run.id),
        "status": agent_run.status,
        "total_time_ms": agent_run.total_time_ms,
        "num_steps": len(agent_run.steps),
    }


@shared_task(
    bind=True,
    name="apps.agents.tasks.resume_pipeline_task",
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
    autoretry_for=_AUTORETRY,
    retry_backoff=True,
    max_retries=3,
)
def resume_pipeline_task(self, agent_run_id, reviewer="", note="", action="approve", reviewer_id=None):
    """Resume an escalated pipeline after a human-review approve or deny.

    ``action="deny"``: the view has already recorded the denial on the
    LoanDecision; the resume issues the bias-checked denial email.
    ``reviewer_id`` is recorded as the user on the decision's status transition.
    """
    from apps.agents.services.orchestrator import PipelineOrchestrator
    from apps.agents.services.step_tracker import pipeline_deadline

    try:
        orchestrator = PipelineOrchestrator()
        with pipeline_deadline(self.soft_time_limit or _DEDUP_LOCK_TTL):
            agent_run = orchestrator.resume_after_review(
                agent_run_id, reviewer=reviewer, note=note, action=action, reviewer_id=reviewer_id
            )
    except _AUTORETRY:
        raise  # autoretried; the resume accepts the claimed run again
    except Exception as exc:
        _return_claimed_run_to_review(agent_run_id, f"Resume failed: {exc}")
        raise

    return {
        "agent_run_id": str(agent_run.id),
        "status": agent_run.status,
        "total_time_ms": agent_run.total_time_ms,
        "num_steps": len(agent_run.steps),
    }


def _return_claimed_run_to_review(agent_run_id, error):
    """Put a claimed (RUNNING) review run back in the queue as ESCALATED.

    The review view claims the run before dispatching the resume. If the
    resume then dies, the application is still REVIEW but no ESCALATED run
    lists it, so nothing could act on it. No-op once the resume has moved
    the application on, or if the run is no longer the claimed one.
    """
    try:
        from apps.agents.models import AgentRun
        from apps.loans.models import LoanApplication

        with transaction.atomic():
            run = AgentRun.objects.select_for_update().filter(pk=agent_run_id).first()
            if run is None or run.status != AgentRun.Status.RUNNING:
                return
            in_review = (
                LoanApplication.objects.select_for_update()
                .filter(pk=run.application_id, status=LoanApplication.Status.REVIEW)
                .exists()
            )
            if not in_review:
                return
            run.status = AgentRun.Status.ESCALATED
            run.error = str(error)[:2000]
            run.save(update_fields=["status", "error", "updated_at"])
        logger.warning("Agent run %s: resume failed, returned to the review queue", agent_run_id)
    except Exception:
        logger.exception("resume_return_to_review_failed", extra={"agent_run_id": str(agent_run_id)})


# A run that is still PROCESSING this long after it was last touched cannot
# be alive: the orchestrate task is hard-killed at 600 s.
_STUCK_PROCESSING_AFTER = timedelta(minutes=15)


@shared_task(name="apps.agents.tasks.recover_stuck_processing_applications", time_limit=120, soft_time_limit=100)
def recover_stuck_processing_applications():
    """Beat sweep: reset applications a hard-killed task left in PROCESSING.

    A hard time-limit kill terminates the worker child, so neither the task's
    own except arm nor Task.on_failure runs, and nothing else watches the
    application. Anything PROCESSING past ``_STUCK_PROCESSING_AFTER`` with no
    dedup lock held is reset via the same audited cleanup the task uses.
    """
    from django.utils import timezone

    from apps.loans.models import LoanApplication

    cutoff = timezone.now() - _STUCK_PROCESSING_AFTER
    recovered = []
    stuck_ids = LoanApplication.objects.filter(
        status=LoanApplication.Status.PROCESSING, updated_at__lt=cutoff
    ).values_list("pk", flat=True)[:100]
    for application_id in stuck_ids:
        if cache.get(_lock_key(application_id)) is not None:
            continue  # a task still owns it
        _cleanup_stuck_application(application_id)
        if not LoanApplication.objects.filter(pk=application_id, status=LoanApplication.Status.PROCESSING).exists():
            recovered.append(str(application_id))
    if recovered:
        logger.warning("Recovered %d application(s) stuck in processing: %s", len(recovered), recovered)

    # A hard-killed resume skips its except arm too: its claimed run stays
    # RUNNING on a REVIEW application, so return it to the review queue.
    from apps.agents.models import AgentRun

    requeued = []
    dead_resume_ids = AgentRun.objects.filter(
        status=AgentRun.Status.RUNNING,
        application__status=LoanApplication.Status.REVIEW,
        updated_at__lt=cutoff,
    ).values_list("pk", flat=True)[:100]
    for run_id in dead_resume_ids:
        _return_claimed_run_to_review(run_id, "Resume task died or timed out; returned to the review queue")
        if AgentRun.objects.filter(pk=run_id, status=AgentRun.Status.ESCALATED).exists():
            requeued.append(str(run_id))
    if requeued:
        logger.warning("Returned %d dead review resume(s) to the queue: %s", len(requeued), requeued)
    return {"recovered": recovered, "requeued": requeued}


@shared_task(name="apps.agents.tasks.compute_pipeline_sla", time_limit=300, soft_time_limit=270)
def compute_pipeline_sla():
    """Weekly P50/P95/P99 computation from AgentRun step timing data."""
    from datetime import datetime, timedelta

    import numpy as np
    from django.utils import timezone

    from apps.agents.models import AgentRun

    week_ago = timezone.now() - timedelta(days=7)
    runs = AgentRun.objects.filter(
        created_at__gte=week_ago,
        status=AgentRun.Status.COMPLETED,
        total_time_ms__isnull=False,
    )

    if not runs.exists():
        logger.info("No completed agent runs in the past week for SLA computation")
        return {"status": "no_data"}

    total_times = list(runs.values_list("total_time_ms", flat=True))

    # Overall pipeline SLA
    p50 = int(np.percentile(total_times, 50))
    p95 = int(np.percentile(total_times, 95))
    p99 = int(np.percentile(total_times, 99))

    # Per-step timing
    step_timings = {}
    for run in runs.only("steps").iterator(chunk_size=500):
        for step in run.steps or []:
            name = step.get("step_name", "unknown")
            if step.get("started_at") and step.get("completed_at"):
                try:
                    start = datetime.fromisoformat(step["started_at"])
                    end = datetime.fromisoformat(step["completed_at"])
                    duration_ms = int((end - start).total_seconds() * 1000)
                    step_timings.setdefault(name, []).append(duration_ms)
                except (ValueError, TypeError) as exc:
                    logger.debug(
                        "sla_step_timing_parse_failed",
                        extra={"step_name": name, "error": str(exc)},
                    )

    step_sla = {}
    for name, times in step_timings.items():
        step_sla[name] = {
            "p50": int(np.percentile(times, 50)),
            "p95": int(np.percentile(times, 95)),
            "count": len(times),
        }

    # SLA targets (ms): ML < 2000, email < 15000, bias < 20000, total < 60000
    sla_targets = {"ml_prediction": 2000, "email_generation": 15000, "bias_check": 20000}
    breaches = []
    for step_name, target_ms in sla_targets.items():
        if step_name in step_sla and step_sla[step_name]["p95"] > target_ms:
            breaches.append(f"{step_name} P95={step_sla[step_name]['p95']}ms > target={target_ms}ms")

    if breaches:
        logger.warning("Pipeline SLA breaches: %s", "; ".join(breaches))

    result = {
        "period": str(week_ago.date()),
        "total_runs": len(total_times),
        "overall": {"p50": p50, "p95": p95, "p99": p99},
        "per_step": step_sla,
        "sla_breaches": breaches,
    }

    logger.info("Pipeline SLA: P50=%dms P95=%dms P99=%dms (%d runs)", p50, p95, p99, len(total_times))
    return result
