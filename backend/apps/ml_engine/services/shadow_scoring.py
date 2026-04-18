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

from apps.ml_engine.models import ModelVersion, PredictionLog

__all__ = ["score_challengers_shadow"]

logger = logging.getLogger(__name__)


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
    """
    try:
        challengers = ModelVersion.objects.filter(
            is_active=False,
            traffic_percentage__gt=0,
            traffic_percentage__lt=100,
        ).exclude(pk=champion_version.pk)

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
