from celery import shared_task


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

    orchestrator = PipelineOrchestrator()
    agent_run = orchestrator.orchestrate(application_id)

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

    orchestrator = PipelineOrchestrator()
    agent_run = orchestrator.resume_after_review(agent_run_id, reviewer=reviewer, note=note)

    return {
        'agent_run_id': str(agent_run.id),
        'status': agent_run.status,
        'total_time_ms': agent_run.total_time_ms,
        'num_steps': len(agent_run.steps),
    }
