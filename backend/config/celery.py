import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('loan_approval')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.task_routes = {
    'apps.ml_engine.tasks.*': {'queue': 'ml'},
    'apps.email_engine.tasks.*': {'queue': 'email'},
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
}
