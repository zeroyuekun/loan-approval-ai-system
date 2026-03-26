import os

from celery import Celery, signals
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('loan_approval')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@signals.before_task_publish.connect
def _propagate_correlation_id(headers=None, **kwargs):
    """Forward the request's correlation ID into the Celery task headers."""
    if headers is None:
        return
    from config.middleware import get_correlation_id
    cid = get_correlation_id()
    if cid:
        headers['correlation_id'] = cid


@signals.task_prerun.connect
def _restore_correlation_id(task=None, **kwargs):
    """Restore the correlation ID inside the Celery worker so that all
    log records emitted during task execution carry the originating
    request's ID."""
    import threading
    from config.middleware import _correlation_id
    cid = getattr(task.request, 'correlation_id', None)
    if cid:
        _correlation_id.value = cid


@signals.task_postrun.connect
def _clear_correlation_id(**kwargs):
    """Clear the correlation ID after task execution."""
    from config.middleware import _correlation_id
    _correlation_id.value = None

app.conf.task_routes = {
    'apps.ml_engine.tasks.*': {'queue': 'ml'},
    'apps.email_engine.tasks.*': {'queue': 'email'},
    'apps.agents.tasks.orchestrate_pipeline_task': {
        'queue': 'agents',
        'rate_limit': '60/m',
    },
    'apps.agents.tasks.*': {'queue': 'agents'},
}

app.conf.beat_schedule = {
    'weekly-drift-report': {
        'task': 'apps.ml_engine.tasks.compute_weekly_drift_report',
        'schedule': crontab(hour=2, minute=0, day_of_week='monday'),
    },
    'weekly-guardrail-analytics': {
        'task': 'apps.email_engine.tasks.compute_guardrail_analytics',
        'schedule': crontab(hour=3, minute=0, day_of_week='monday'),
    },
    'weekly-pipeline-sla': {
        'task': 'apps.agents.tasks.compute_pipeline_sla',
        'schedule': crontab(hour=4, minute=0, day_of_week='monday'),
    },
    'weekly-fairness-check': {
        'task': 'apps.ml_engine.tasks.check_fairness_violations',
        'schedule': crontab(hour=5, minute=0, day_of_week='monday'),
    },
}
