"""Post-probability decision-assembly helper.

Carved out of `ModelPredictor.predict()` during Arm C Phase 1. Given the
model's raw positive-class probability plus the context needed for threshold
resolution and pricing, returns the decision-assembly fields in a single
dict so the caller doesn't have to thread them across the remainder of
`predict()`.

Assembly steps:

1. Resolve the approval threshold. `model_version.optimal_threshold` is
   authoritative; falling back to 0.5 logs a loud warning — a missing
   threshold means the model wasn't properly validated, which is a
   disparate-impact risk (APRA CPG 235).
   The same threshold applies to every applicant: there is no per-group
   (e.g. employment-type) threshold, and any `group_thresholds` left in an
   older model artefact are ignored.
2. Derive the `approved`/`denied` label.
3. Flag borderline cases (within 10pp of the effective threshold) and
   drift=severe cases for human review.
4. Compute the D4 pricing tier. A pricing-tier decline overrides an
   otherwise-approved model result (PD above the top cutoff means the
   bank won't write the loan even if the model says approve).

Fail-open on pricing: a pricing-engine exception returns `{tier:
"unavailable", approved: True}` so the scoring pipeline continues.
"""

from __future__ import annotations

import logging
import os

from apps.ml_engine.services.scoring.pricing_engine import get_tier

__all__ = ["assemble_decision"]

logger = logging.getLogger(__name__)


# Borderline margin: applications within this many probability points of the
# effective threshold are routed to human review. Default 0.05 (0.10 flagged
# ~20% of all applications, far too broad for operational use); override via
# ML_BORDERLINE_MARGIN to tune without a redeploy.
_BORDERLINE_MARGIN = float(os.environ.get("ML_BORDERLINE_MARGIN", "0.05"))


def assemble_decision(
    *,
    probability_positive: float,
    model_version,
    drift_warnings: list,
    segment: str,
) -> dict:
    """Assemble the post-probability decision state.

    Returns a dict with keys: `probability`, `threshold`,
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

    prediction_label = "approved" if probability >= threshold else "denied"

    requires_human_review = abs(probability - threshold) <= _BORDERLINE_MARGIN
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
        # Fail-safe: the pricing tier is a hard risk gate that can DECLINE a
        # model-approved application (PD above the bank's writeable cutoff). A
        # transient failure must NOT read as a clean approve — flag the decision
        # for human review and never report the gate as approved. (Routing here
        # mirrors how requires_human_review already handles drift/borderline; it
        # is not the bias-detection queue.)
        logger.warning("Pricing tier computation failed — flagging for human review (fail-safe)", exc_info=True)
        pricing_payload = {"tier": "unavailable", "approved": False}
        requires_human_review = True

    return {
        "probability": probability,
        "threshold": threshold,
        "prediction_label": prediction_label,
        "requires_human_review": requires_human_review,
        "pricing_payload": pricing_payload,
    }
