import logging

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger('agents.tasks')

# Redis dedup lock TTL — slightly longer than the task soft time limit
_DEDUP_LOCK_TTL = 600


def _cleanup_stuck_application(application_id):
    """Reset application status if it's stuck at 'processing' after a task failure."""
    try:
        from apps.loans.models import LoanApplication
        from apps.agents.models import AgentRun

        LoanApplication.objects.filter(
            pk=application_id, status='processing',
        ).update(status='review')

        AgentRun.objects.filter(
            application_id=application_id, status__in=('pending', 'running'),
        ).update(status='failed', error='Task failed unexpectedly — application reset to review')

        logger.warning('Application %s: cleaned up stuck processing status', application_id)
    except Exception as e:
        logger.error('Application %s: cleanup failed: %s', application_id, e)


@shared_task(
    bind=True,
    name='apps.agents.tasks.orchestrate_pipeline_task',
    time_limit=600,
    soft_time_limit=540,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=3,
)
def orchestrate_pipeline_task(self, application_id):
    """Run the full loan processing pipeline."""
    from apps.agents.models import AgentRun
    from apps.agents.services.orchestrator import PipelineOrchestrator

    # Redis dedup lock: prevent concurrent runs for the same application
    lock_key = f'orchestrate_lock:{application_id}'
    acquired = cache.add(lock_key, self.request.id, _DEDUP_LOCK_TTL)
    if not acquired:
        logger.info('Application %s: dedup lock already held, skipping', application_id)
        return {'skipped': True, 'reason': 'dedup_lock_held'}

    try:
        orchestrator = PipelineOrchestrator()
        agent_run = orchestrator.orchestrate(application_id)
    except (ConnectionError, TimeoutError, OSError):
        # Let Celery's autoretry handle these — don't cleanup yet
        raise
    except Exception:
        _cleanup_stuck_application(application_id)
        raise
    finally:
        cache.delete(lock_key)

    return {
        'agent_run_id': str(agent_run.id),
        'status': agent_run.status,
        'total_time_ms': agent_run.total_time_ms,
        'num_steps': len(agent_run.steps),
    }


@shared_task(
    bind=True,
    name='apps.agents.tasks.resume_pipeline_task',
    time_limit=600,
    soft_time_limit=540,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=3,
)
def resume_pipeline_task(self, agent_run_id, reviewer='', note=''):
    """Resume an escalated pipeline after human approval."""
    from apps.agents.services.orchestrator import PipelineOrchestrator

    try:
        orchestrator = PipelineOrchestrator()
        agent_run = orchestrator.resume_after_review(agent_run_id, reviewer=reviewer, note=note)
    except (ConnectionError, TimeoutError, OSError):
        raise
    except Exception:
        # Try to find the application_id from the agent run for cleanup
        try:
            from apps.agents.models import AgentRun
            run = AgentRun.objects.get(pk=agent_run_id)
            _cleanup_stuck_application(str(run.application_id))
        except Exception:
            pass
        raise

    return {
        'agent_run_id': str(agent_run.id),
        'status': agent_run.status,
        'total_time_ms': agent_run.total_time_ms,
        'num_steps': len(agent_run.steps),
    }


@shared_task(name='apps.agents.tasks.compute_pipeline_sla')
def compute_pipeline_sla():
    """Weekly P50/P95/P99 computation from AgentRun step timing data."""
    import numpy as np
    from datetime import datetime, timedelta
    from django.utils import timezone
    from apps.agents.models import AgentRun

    week_ago = timezone.now() - timedelta(days=7)
    runs = AgentRun.objects.filter(
        created_at__gte=week_ago,
        status='completed',
        total_time_ms__isnull=False,
    )

    if not runs.exists():
        logger.info('No completed agent runs in the past week for SLA computation')
        return {'status': 'no_data'}

    total_times = list(runs.values_list('total_time_ms', flat=True))

    # Overall pipeline SLA
    p50 = int(np.percentile(total_times, 50))
    p95 = int(np.percentile(total_times, 95))
    p99 = int(np.percentile(total_times, 99))

    # Per-step timing
    step_timings = {}
    for run in runs.iterator():
        for step in (run.steps or []):
            name = step.get('step_name', 'unknown')
            if step.get('started_at') and step.get('completed_at'):
                try:
                    start = datetime.fromisoformat(step['started_at'])
                    end = datetime.fromisoformat(step['completed_at'])
                    duration_ms = int((end - start).total_seconds() * 1000)
                    step_timings.setdefault(name, []).append(duration_ms)
                except (ValueError, TypeError):
                    pass

    step_sla = {}
    for name, times in step_timings.items():
        step_sla[name] = {
            'p50': int(np.percentile(times, 50)),
            'p95': int(np.percentile(times, 95)),
            'count': len(times),
        }

    # SLA targets (ms): ML < 2000, email < 15000, bias < 20000, total < 60000
    sla_targets = {'ml_prediction': 2000, 'email_generation': 15000, 'bias_check': 20000}
    breaches = []
    for step_name, target_ms in sla_targets.items():
        if step_name in step_sla and step_sla[step_name]['p95'] > target_ms:
            breaches.append(f"{step_name} P95={step_sla[step_name]['p95']}ms > target={target_ms}ms")

    if breaches:
        logger.warning('Pipeline SLA breaches: %s', '; '.join(breaches))

    result = {
        'period': str(week_ago.date()),
        'total_runs': len(total_times),
        'overall': {'p50': p50, 'p95': p95, 'p99': p99},
        'per_step': step_sla,
        'sla_breaches': breaches,
    }

    logger.info('Pipeline SLA: P50=%dms P95=%dms P99=%dms (%d runs)', p50, p95, p99, len(total_times))
    return result
