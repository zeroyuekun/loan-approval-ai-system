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
3. Record refer reasons: borderline cases (within `_BORDERLINE_MARGIN` of
   the threshold) and severe feature drift. A refer reason does NOT change
   the decision or route it to human review — that queue is only for bias
   flags. It is kept on the decision record so the decision stays
   explainable.
4. Compute the D4 pricing tier. A pricing-tier decline overrides an
   otherwise-approved model result (PD above the top cutoff means the
   bank won't write the loan even if the model says approve).

A decline by a rule rather than by the model (the pricing tier here, an
enforce-mode credit-policy hard fail in the predictor) is marked on its
payload; `decline_overrides` turns those payloads into reason codes, so the
waterfall and the denial email name the rule instead of presenting the
denial as the model's.

Pricing failure: the tier can only turn an approval into a decline, so on an
approval a pricing-engine exception raises `PricingUnavailable` (the pipeline
fails the prediction step and the application returns to PENDING for a
re-run); on a denial the denial stands and the gap is a refer reason.
"""

from __future__ import annotations

import logging
import os

from apps.ml_engine.services.scoring.pricing_engine import get_tier

__all__ = [
    "POLICY_DECLINE_PREFIX",
    "PRICING_TIER_DECLINE",
    "PricingUnavailable",
    "assemble_decision",
    "decline_overrides",
]

logger = logging.getLogger(__name__)


# Borderline margin: applications within this many probability points of the
# threshold are recorded with a BORDERLINE refer reason. Default 0.05 (0.10 flagged
# ~20% of all applications, far too broad for operational use); override via
# ML_BORDERLINE_MARGIN to tune without a redeploy.
_BORDERLINE_MARGIN = float(os.environ.get("ML_BORDERLINE_MARGIN", "0.05"))


# Reason codes for a denial a rule made over a model approval.
PRICING_TIER_DECLINE = "PRICING_TIER_DECLINE"
POLICY_DECLINE_PREFIX = "POLICY_DECLINE_"


class PricingUnavailable(RuntimeError):
    """The pricing gate could not be evaluated for a model approval."""


def assemble_decision(
    *,
    probability_positive: float,
    model_version,
    drift_warnings: list,
    segment: str,
) -> dict:
    """Assemble the post-probability decision state.

    Returns a dict with keys: `probability`, `threshold`,
    `prediction_label`, `refer_reasons` (list of `{code, detail}`),
    `pricing_payload`.
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

    refer_reasons: list[dict] = []
    if abs(probability - threshold) <= _BORDERLINE_MARGIN:
        refer_reasons.append(
            {
                "code": "BORDERLINE",
                "detail": (
                    f"Probability {probability:.4f} is within {_BORDERLINE_MARGIN:.2f} "
                    f"of the {threshold:.4f} approval threshold"
                ),
            }
        )
    drifted = [w.get("feature") for w in drift_warnings if w.get("severity") == "drift"]
    if drifted:
        refer_reasons.append(
            {
                "code": "FEATURE_DRIFT",
                "detail": "Outside the training distribution (|z| > 4): " + ", ".join(str(f) for f in drifted),
            }
        )

    try:
        pricing_tier = get_tier(pd_score=1.0 - probability, segment=segment)
    except Exception as exc:
        if prediction_label == "approved":
            # Fail closed: the pricing tier is a hard risk gate that can
            # DECLINE a model approval, so an approval it could not check must
            # not ship. Raised to the pipeline, which returns the application
            # to PENDING for a re-run.
            raise PricingUnavailable(f"Pricing tier could not be computed for an approval: {exc}") from exc
        logger.warning("Pricing tier computation failed on a denial — denial stands", exc_info=True)
        pricing_payload = {"tier": "unavailable", "approved": False}
        refer_reasons.append({"code": "PRICING_UNAVAILABLE", "detail": f"Pricing tier could not be computed: {exc}"})
    else:
        pricing_payload = pricing_tier.to_dict()
        pricing_payload["declined_model_approval"] = False
        if not pricing_tier.approved and prediction_label == "approved":
            logger.info(
                "Pricing tier decline overrides model approve: PD=%.4f segment=%s",
                pricing_tier.pd_score,
                pricing_tier.segment,
            )
            prediction_label = "denied"
            pricing_payload["declined_model_approval"] = True

    return {
        "probability": probability,
        "threshold": threshold,
        "prediction_label": prediction_label,
        "refer_reasons": refer_reasons,
        "pricing_payload": pricing_payload,
    }


def decline_overrides(prediction_result: dict) -> list[dict]:
    """The rules that declined an application the model approved, as ``{code, detail}``.

    Empty when the decision is not a denial or the model itself denied. Read
    from the result's ``pricing_tier`` and ``policy_decision`` payloads:
    ``PRICING_TIER_DECLINE`` when the PD is above the segment's top pricing
    cutoff, ``POLICY_DECLINE_<rule>`` for each enforce-mode policy hard fail
    (they decline only an approval, so they count when the model approved).
    """
    if prediction_result.get("prediction") != "denied":
        return []
    pricing = prediction_result.get("pricing_tier") or {}
    policy = prediction_result.get("policy_decision") or {}
    pricing_declined = bool(pricing.get("declined_model_approval"))
    model_approved = pricing_declined or bool(policy.get("changed_model_decision"))
    if not model_approved:
        return []

    overrides = []
    if pricing_declined:
        overrides.append({"code": PRICING_TIER_DECLINE, "detail": pricing.get("rationale") or ""})
    if policy.get("mode") == "enforce":
        rationale = policy.get("rationale_by_code") or {}
        for code in policy.get("hard_fails") or []:
            overrides.append({"code": f"{POLICY_DECLINE_PREFIX}{code}", "detail": rationale.get(code, "")})
    return overrides
