from celery import shared_task


@shared_task(bind=True, name='apps.agents.tasks.orchestrate_pipeline_task')
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
