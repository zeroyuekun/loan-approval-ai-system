import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('loan_approval')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.task_routes = {
    'apps.ml_engine.tasks.*': {'queue': 'ml'},
    'apps.email_engine.tasks.*': {'queue': 'email'},
    'apps.agents.tasks.*': {'queue': 'agents'},
}
