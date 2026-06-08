"""Champion/challenger shadow-scoring helper.

Carved out of `ModelPredictor.predict()` during Arm C Phase 1. Runs the
challenger model(s) alongside the champion for passive evaluation: predictions
are recorded as `PredictionLog` rows but never fed back into the customer-facing
decision.

Safety contract:

1. The helper accepts a plain `score_fn` callable so it doesn't need to import
   `ModelPredictor` (which would create a circular import). The caller passes
   the scoring capability in from the predictor's lexical scope.
2. Per-challenger exceptions are caught and logged — one broken challenger
   cannot stop another. Catching the outer ORM query too means a missing
   `PredictionLog` table (unmigrated DB) does not break the hot path.
3. No mutations of the champion decision path. The helper's only side effect
   is writing `PredictionLog` rows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd
from django.core.cache import cache

from apps.ml_engine.models import ModelVersion, PredictionLog

__all__ = ["score_challengers_shadow"]

logger = logging.getLogger(__name__)

# TTL for the cached challenger list.  30 s is short enough to pick up model
# promotions quickly while still amortising the ORM round-trip across many
# concurrent requests on the hot prediction path.
_CHALLENGER_CACHE_KEY = "ml:challenger_models"
_CHALLENGER_CACHE_TTL = 30  # seconds


def _get_challenger_models(champion_pk) -> list:
    """Return active challenger ModelVersions, cached for _CHALLENGER_CACHE_TTL seconds.

    We cache the full queryset result (a plain Python list) rather than a
    lazy QuerySet so the cache hit is a single dict lookup with no DB round-trip.
    The cache key does NOT encode champion_pk — the champion exclusion is applied
    after retrieval so a single cached list is shared across all champions.
    """
    cached = cache.get(_CHALLENGER_CACHE_KEY)
    if cached is not None:
        return [c for c in cached if c.pk != champion_pk]
    challengers = list(
        ModelVersion.objects.filter(
            is_active=False,
            traffic_percentage__gt=0,
            traffic_percentage__lt=100,
        ).select_related()
    )
    cache.set(_CHALLENGER_CACHE_KEY, challengers, timeout=_CHALLENGER_CACHE_TTL)
    return [c for c in challengers if c.pk != champion_pk]


ScoreFn = Callable[[ModelVersion, pd.DataFrame], "tuple[float, str]"]


def score_challengers_shadow(
    *,
    application,
    champion_version,
    champion_probability: float,
    champion_prediction_label: str,
    features_df: pd.DataFrame,
    score_fn: ScoreFn,
    max_challengers: int = 2,
) -> None:
    """Score up to `max_challengers` challenger `ModelVersion`s in shadow mode.

    Args:
        application: The `LoanApplication` being scored (used only to link the
            `PredictionLog` row; never mutated).
        champion_version: Active `ModelVersion` — excluded by pk from the
            challenger set.
        champion_probability / champion_prediction_label: Champion output, used
            for the informational log comparison only.
        features_df: Raw (untransformed) feature dict, single-row DataFrame.
            `score_fn` is expected to run its own transform pipeline.
        score_fn: Callable `(model_version, features_df) -> (prob, label)`.
            Encapsulates the challenger's transform + predict_proba + threshold.
        max_challengers: Cap the number of challengers evaluated per request
            (default 2) so shadow scoring never dominates the hot-path latency.

    The challenger list is cached for _CHALLENGER_CACHE_TTL seconds to avoid
    an N+1 ORM query on the hot prediction path.
    """
    try:
        challengers = _get_challenger_models(champion_version.pk)

        for challenger in challengers[:max_challengers]:
            try:
                challenger_prob, challenger_pred = score_fn(challenger, features_df.copy())

                PredictionLog.objects.create(
                    model_version=challenger,
                    application=application,
                    prediction=challenger_pred,
                    probability=challenger_prob,
                    feature_importances={},
                    processing_time_ms=0,
                )

                logger.info(
                    "Shadow score: challenger %s predicted %s (%.3f) vs champion %s (%.3f)",
                    challenger.version,
                    challenger_pred,
                    challenger_prob,
                    champion_prediction_label,
                    champion_probability,
                )
            except Exception as e:
                logger.warning(
                    "Shadow scoring failed for challenger %s: %s",
                    challenger.version,
                    e,
                )
    except Exception as e:
        logger.debug("Shadow scoring check skipped: %s", e)
