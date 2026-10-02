"""Signal handlers for ml_engine.

Currently only handles:
- ModelVersion post_save → enqueue MRM dossier generation.

Handlers are registered in `MlEngineConfig.ready()`.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.ml_engine.models import ModelVersion

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ModelVersion)
def enqueue_mrm_dossier(sender, instance: ModelVersion, created: bool, **kwargs):
    """Fire the Celery task that writes the MRM dossier for a new model.

    Only runs on initial create (not on subsequent save() calls that
    merely update metadata), and only once the creating transaction has
    committed. Failing to enqueue is not fatal — the dossier can always be
    regenerated with `manage.py generate_mrm_dossier`.

    Skipped when the `MRM_DOSSIER_AUTO_GENERATE` setting is False, so
    ModelVersion.save() can stay fast in unit tests that don't exercise the
    Celery path.
    """
    if not created:
        return
    if not getattr(settings, "MRM_DOSSIER_AUTO_GENERATE", True):
        return

    model_version_id = str(instance.pk)

    def _enqueue():
        try:
            from apps.ml_engine.tasks import generate_mrm_dossier_task

            generate_mrm_dossier_task.delay(model_version_id)
        except Exception as exc:  # broker offline, task unavailable, etc.
            logger.warning(
                "enqueue_mrm_dossier: failed to enqueue task for %s: %s",
                model_version_id,
                exc,
                exc_info=True,
            )

    # After commit: the training path creates the row, activates it and saves
    # the gate verdicts in one transaction; a worker reading earlier would find
    # no row, or a row without the gate record the dossier banner shows.
    transaction.on_commit(_enqueue)
