"""Signal handlers for ml_engine.

Currently only handles:
- ModelVersion post_save → enqueue MRM dossier generation (D7).

Handlers are registered in `MlEngineConfig.ready()`.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.ml_engine.models import ModelVersion

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ModelVersion)
def enqueue_mrm_dossier(sender, instance: ModelVersion, created: bool, **kwargs):
    """Fire the Celery task that writes the MRM dossier for a new model.

    Only runs on initial create (not on subsequent save() calls that
    merely update metadata). Failing to enqueue is not fatal — the
    dossier can always be regenerated with `manage.py generate_mrm_dossier`.

    Skipped in tests (DEBUG + TESTING flag) and when
    `MRM_DOSSIER_AUTO_GENERATE` setting is explicitly False so that
    ModelVersion.save() stays fast in unit tests that don't exercise the
    Celery path.
    """
    if not created:
        return
    if not getattr(settings, "MRM_DOSSIER_AUTO_GENERATE", True):
        return

    try:
        from apps.ml_engine.tasks import generate_mrm_dossier_task

        generate_mrm_dossier_task.delay(str(instance.pk))
    except Exception as exc:  # broker offline, task unavailable, etc.
        logger.warning(
            "enqueue_mrm_dossier: failed to enqueue task for %s: %s",
            instance.pk,
            exc,
            exc_info=True,
        )
