"""Weighted model selection for champion/challenger A/B testing."""

import logging
import random

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.segmentation import SEGMENT_UNIFIED

logger = logging.getLogger("ml_engine.model_selector")


def select_model_version(segment: str = SEGMENT_UNIFIED):
    """Select a model version using weighted random by traffic_percentage.

    Scoped to `segment` so per-segment A/B tests (e.g. two personal-loan
    challengers) don't interfere with mortgage models. When `segment` is
    non-unified and no active model exists in that segment, the call falls
    back to the unified segment — mirroring
    `segmentation.select_active_model_for_segment`.

    Single active model: returns it immediately (fast path).
    Multiple active models (same segment): weighted random selection.
    No active models in segment and no unified fallback: raises ValueError.
    """
    active_models = list(
        ModelVersion.objects.filter(
            is_active=True, traffic_percentage__gt=0, segment=segment
        ).order_by("-created_at")
    )

    if not active_models and segment != SEGMENT_UNIFIED:
        logger.info(
            "No active models for segment '%s' — falling back to unified",
            segment,
        )
        active_models = list(
            ModelVersion.objects.filter(
                is_active=True, traffic_percentage__gt=0, segment=SEGMENT_UNIFIED
            ).order_by("-created_at")
        )

    if not active_models:
        raise ValueError(
            f"No active model version found for segment '{segment}' (and no "
            "unified fallback available). Train a model first."
        )

    if len(active_models) == 1:
        return active_models[0]

    # Weighted random selection within the resolved segment pool.
    weights = [m.traffic_percentage for m in active_models]
    selected = random.choices(active_models, weights=weights, k=1)[0]  # noqa: S311
    logger.debug(
        "Champion/challenger (segment=%s): selected model %s (traffic=%d%%) from %d active models",
        selected.segment,
        selected.version,
        selected.traffic_percentage,
        len(active_models),
    )
    return selected
