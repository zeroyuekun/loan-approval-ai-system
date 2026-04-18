"""Post-probability decision-assembly helper.

Carved out of `ModelPredictor.predict()` during Arm C Phase 1. Given the
model's raw positive-class probability plus the context needed for threshold
resolution and pricing, returns all six decision-assembly fields in a single
dict so the caller doesn't have to thread six locals across the remainder of
`predict()`.

Assembly steps:

1. Resolve the approval threshold. `model_version.optimal_threshold` is
   authoritative; falling back to 0.5 logs a loud warning — a missing
   threshold means the model wasn't properly validated, which is a
   disparate-impact risk (APRA CPG 235).
2. Apply the per-employment-type group threshold if configured (EEOC
   80% rule compliance).
3. Derive the `approved`/`denied` label.
4. Flag borderline cases (within 10pp of the effective threshold) and
   drift=severe cases for human review.
5. Compute the D4 pricing tier. A pricing-tier decline overrides an
   otherwise-approved model result (PD above the top cutoff means the
   bank won't write the loan even if the model says approve).

Fail-open on pricing: a pricing-engine exception returns `{tier:
"unavailable", approved: True}` so the scoring pipeline continues.
"""

from __future__ import annotations

import logging

from apps.ml_engine.services.pricing_engine import get_tier

__all__ = ["assemble_decision"]

logger = logging.getLogger(__name__)


_BORDERLINE_MARGIN = 0.10


def assemble_decision(
    *,
    probability_positive: float,
    model_version,
    group_thresholds: dict | None,
    employment_type: str,
    drift_warnings: list,
    segment: str,
) -> dict:
    """Assemble the post-probability decision state.

    Returns a dict with keys: `probability`, `threshold`, `effective_threshold`,
    `prediction_label`, `requires_human_review`, `pricing_payload`.
    """
    threshold = model_version.optimal_threshold
    if threshold is None:
        threshold = 0.5
        logger.warning(
            "ModelVersion %s has no optimal_threshold set — falling back to 0.5. "
            "This may cause calibration drift and disparate-impact risk. "
            "Re-run validate_model to populate optimal_threshold.",
            model_version.id,
        )

    probability = round(float(probability_positive), 4)

    effective_threshold = threshold
    if group_thresholds and employment_type in group_thresholds:
        effective_threshold = group_thresholds[employment_type]

    prediction_label = "approved" if probability >= effective_threshold else "denied"

    requires_human_review = abs(probability - effective_threshold) <= _BORDERLINE_MARGIN
    if any(w.get("severity") == "drift" for w in drift_warnings):
        requires_human_review = True

    try:
        pricing_tier = get_tier(pd_score=1.0 - probability, segment=segment)
        pricing_payload = pricing_tier.to_dict()
        if not pricing_tier.approved and prediction_label == "approved":
            logger.info(
                "Pricing tier decline overrides model approve: PD=%.4f segment=%s",
                pricing_tier.pd_score,
                pricing_tier.segment,
            )
            prediction_label = "denied"
    except Exception:
        logger.warning("Pricing tier computation failed", exc_info=True)
        pricing_payload = {"tier": "unavailable", "approved": True}

    return {
        "probability": probability,
        "threshold": threshold,
        "effective_threshold": effective_threshold,
        "prediction_label": prediction_label,
        "requires_human_review": requires_human_review,
        "pricing_payload": pricing_payload,
    }
