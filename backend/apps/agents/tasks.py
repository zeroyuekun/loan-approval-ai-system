import logging

from celery import shared_task

logger = logging.getLogger('agents.tasks')


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
    from apps.agents.services.orchestrator import PipelineOrchestrator

    try:
        orchestrator = PipelineOrchestrator()
        agent_run = orchestrator.orchestrate(application_id)
    except (ConnectionError, TimeoutError, OSError):
        # Let Celery's autoretry handle these — don't cleanup yet
        raise
    except Exception:
        _cleanup_stuck_application(application_id)
        raise

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
