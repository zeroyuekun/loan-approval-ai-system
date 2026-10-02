"""D3 credit-policy overlay glue + D6 referral-audit trail.

Carved out of `ModelPredictor.predict()` during Arm C Phase 1. Wraps the
`credit_policy` module's pure evaluation functions in the predictor-side
behaviour:

1. Evaluate the policy overlay once, regardless of mode, so shadow-mode logs
   capture the enforce hypothetical for every request.
2. In shadow mode, emit a `credit_policy_shadow_disagreement` warning when
   the enforce-mode overlay would have changed the model decision.
3. Referrals never change the decision or route it to human review (that
   queue is only for bias flags); the caller records enforce-mode refer codes
   as refer reasons on the decision.
4. Write D6 audit-trail fields (`referral_status`, `referral_codes`,
   `referral_rationale`) on the `LoanApplication` when the policy refers,
   wrapped in its own try/except so persistence failures can't break scoring.
5. Failure: in `shadow`/`off` mode the overlay cannot change the decision,
   so an exception returns the unchanged label and a `{passed: None, mode:
   "off", error: ...}` payload. In `enforce` mode it can decline (bankruptcy,
   DTI, LVR), so an exception raises `PolicyOverlayUnavailable`: the pipeline
   fails the prediction step and the application returns to PENDING.
"""

from __future__ import annotations

import logging

from apps.ml_engine.services.scoring import credit_policy as _policy

__all__ = ["PolicyOverlayUnavailable", "apply_policy_overlay"]

logger = logging.getLogger(__name__)


class PolicyOverlayUnavailable(RuntimeError):
    """The enforce-mode credit-policy overlay could not be evaluated."""


def apply_policy_overlay(
    *,
    application,
    model_version,
    prediction_label: str,
) -> tuple[str, dict]:
    """Evaluate the D3 overlay and return the post-overlay decision deltas.

    Args:
        application: `LoanApplication` row. `None` is tolerated (D6 audit-trail
            write is simply skipped) so callers scoring raw feature dicts still
            benefit from the overlay.
        model_version: `ModelVersion` row — used only for logging metadata
            (the `model_version` extra field on shadow-disagreement warnings).
        prediction_label: The champion model's raw decision before the overlay.

    Returns:
        `(final_prediction_label, policy_payload)`. The payload carries the
        mode and the refer codes.

    Raises:
        PolicyOverlayUnavailable: in enforce mode, when evaluation fails.
    """
    policy_mode = _policy.current_mode()
    try:
        policy_result = _policy.evaluate(application)
        final_prediction = _policy.apply_overlay_to_decision(prediction_label, policy_result, policy_mode)

        if policy_mode == _policy.OVERLAY_MODE_SHADOW and not policy_result.passed:
            hypothetical = _policy.apply_overlay_to_decision(
                prediction_label, policy_result, _policy.OVERLAY_MODE_ENFORCE
            )
            if hypothetical != prediction_label:
                logger.warning(
                    "credit_policy_shadow_disagreement",
                    extra={
                        "model_version": str(getattr(model_version, "id", "")),
                        "model_decision": prediction_label,
                        "policy_hypothetical": hypothetical,
                        "hard_fails": policy_result.hard_fails,
                        "refers": policy_result.refers,
                    },
                )

        policy_payload = {
            **policy_result.to_dict(),
            "mode": policy_mode,
            "changed_model_decision": final_prediction != prediction_label,
        }

        if policy_result.has_refer and application is not None:
            try:
                application.referral_status = application.ReferralStatus.REFERRED
                application.referral_codes = list(policy_result.refers)
                application.referral_rationale = {
                    code: policy_result.rationale_by_code.get(code, "") for code in policy_result.refers
                }
                application.save(
                    update_fields=["referral_status", "referral_codes", "referral_rationale"],
                )
            except Exception:
                logger.warning(
                    "referral_audit_save_failed",
                    exc_info=True,
                    extra={
                        "application_id": str(getattr(application, "id", None)),
                        "refers": list(policy_result.refers),
                    },
                )

        return final_prediction, policy_payload

    except Exception as exc:
        if policy_mode == _policy.OVERLAY_MODE_ENFORCE:
            logger.error("credit_policy_evaluate_failed in enforce mode — failing closed", exc_info=True)
            raise PolicyOverlayUnavailable(f"Credit policy overlay could not be evaluated: {exc}") from exc
        logger.warning("credit_policy_evaluate_failed", exc_info=True)
        return (
            prediction_label,
            {
                "passed": None,
                "mode": "off",
                "error": str(exc),
            },
        )
