import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='apps.loans.tasks.enforce_data_retention')
def enforce_data_retention():
    """Weekly task: enforce data retention policy per regulatory requirements."""
    from django.core.management import call_command

    output = call_command('enforce_retention')
    logger.info('Data retention enforcement completed: %s', output)
    return output
