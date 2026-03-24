"""Weighted model selection for champion/challenger A/B testing."""

import random
import logging

from apps.ml_engine.models import ModelVersion

logger = logging.getLogger('ml_engine.model_selector')


def select_model_version():
    """Select a model version using weighted random by traffic_percentage.

    Single active model: returns it immediately (fast path).
    Multiple active models: weighted random selection.
    No active models: raises ValueError.
    """
    active_models = list(
        ModelVersion.objects.filter(is_active=True, traffic_percentage__gt=0)
        .order_by('-created_at')
    )

    if not active_models:
        raise ValueError('No active model version found. Train a model first.')

    if len(active_models) == 1:
        return active_models[0]

    # Weighted random selection
    weights = [m.traffic_percentage for m in active_models]
    selected = random.choices(active_models, weights=weights, k=1)[0]
    logger.debug(
        'Champion/challenger: selected model %s (traffic=%d%%) from %d active models',
        selected.version, selected.traffic_percentage, len(active_models),
    )
    return selected
