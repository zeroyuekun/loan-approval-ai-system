"""Unit tests for the post-probability decision-assembly helper.

`assemble_decision` is the block carved out of `ModelPredictor.predict()`
during Arm C Phase 1. Given the model's raw positive-class probability, it:

- Resolves the approval threshold (model_version.optimal_threshold or 0.5
  fallback with a warning).
- Applies that one threshold to every applicant (no per-group thresholds).
- Derives the `approved`/`denied` label.
- Records borderline and severe-drift cases as refer reasons. They do not
  route to human review (that queue is only for bias flags); the model
  decision stands and the reason is kept on the decision record.
- Calls the D4 pricing engine, which may further decline an approved label
  when PD is above the top tier cutoff.

All output fields are returned as a single dict so the caller doesn't
have to thread them through its own locals.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.ml_engine.services.scoring.decision_assembly import PricingUnavailable, assemble_decision


def _mk_version(optimal_threshold=0.5, id_="mv-1"):
    return SimpleNamespace(id=id_, optimal_threshold=optimal_threshold)


def _patch_pricing(*, pd_score_out=None, approved=True, segment_out="personal", to_dict=None):
    """Make pricing_engine.get_tier return a canned `PricingTier`-shaped mock."""
    tier = MagicMock()
    tier.approved = approved
    tier.pd_score = pd_score_out if pd_score_out is not None else 0.1
    tier.segment = segment_out
    tier.to_dict.return_value = to_dict or {
        "tier": "A",
        "approved": approved,
        "segment": segment_out,
    }
    return patch(
        "apps.ml_engine.services.scoring.decision_assembly.get_tier",
        return_value=tier,
    )


class TestAssembleDecision:
    def test_approved_above_threshold(self):
        mv = _mk_version(optimal_threshold=0.6)
        with _patch_pricing(approved=True):
            result = assemble_decision(
                probability_positive=0.8,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "approved"
        assert result["probability"] == 0.8
        assert result["threshold"] == 0.6
        assert result["refer_reasons"] == []

    def test_denied_below_threshold(self):
        mv = _mk_version(optimal_threshold=0.6)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.3,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "denied"

    def test_missing_threshold_falls_back_to_half_with_warning(self):
        mv = _mk_version(optimal_threshold=None)
        with _patch_pricing(), patch("apps.ml_engine.services.scoring.decision_assembly.logger") as log:
            result = assemble_decision(
                probability_positive=0.7,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert result["threshold"] == 0.5
        log.warning.assert_called_once()
        assert "optimal_threshold" in log.warning.call_args.args[0]

    def test_borderline_within_5pp_is_a_refer_reason(self):
        # _BORDERLINE_MARGIN was reduced from 0.10 to 0.05 (M11).
        # Use 0.53 so |0.53 - 0.5| = 0.03 is clearly inside the 5pp window.
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.53,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        # |0.53 - 0.5| = 0.03 <= 0.05 → borderline: recorded, decision stands
        assert result["prediction_label"] == "approved"
        assert [r["code"] for r in result["refer_reasons"]] == ["BORDERLINE"]

    def test_drift_severity_is_a_refer_reason(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.90,  # well clear of threshold
                model_version=mv,
                drift_warnings=[{"severity": "drift"}],
                segment="personal",
            )

        # Not borderline, but drift severity is recorded; decision stands.
        assert result["prediction_label"] == "approved"
        assert [r["code"] for r in result["refer_reasons"]] == ["FEATURE_DRIFT"]

    def test_pricing_tier_can_override_approved_to_denied(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing(approved=False):
            result = assemble_decision(
                probability_positive=0.85,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        # Model approves (0.85 > 0.5) but pricing-tier disapproves → final denied.
        assert result["prediction_label"] == "denied"
        assert result["pricing_payload"]["approved"] is False

    def test_pricing_tier_does_not_override_already_denied(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing(approved=False):
            result = assemble_decision(
                probability_positive=0.2,  # model already denies
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "denied"

    def test_pricing_failure_on_an_approval_raises(self):
        """The pricing tier is a hard risk gate that can DECLINE a model
        approval. If it cannot be computed the approval must not ship
        unchecked, and it cannot go to human review (that queue is bias-only):
        raise, so the pipeline fails the prediction step and the application
        returns to PENDING for a re-run."""
        mv = _mk_version(optimal_threshold=0.5)
        with (
            patch(
                "apps.ml_engine.services.scoring.decision_assembly.get_tier",
                side_effect=RuntimeError("pricing engine broken"),
            ),
            pytest.raises(PricingUnavailable),
        ):
            assemble_decision(
                probability_positive=0.8,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

    def test_pricing_failure_on_a_denial_keeps_the_denial(self):
        """Pricing can only turn an approval into a decline, so a denial does
        not depend on it: the denial stands and the gap is recorded."""
        mv = _mk_version(optimal_threshold=0.5)
        with patch(
            "apps.ml_engine.services.scoring.decision_assembly.get_tier",
            side_effect=RuntimeError("pricing engine broken"),
        ):
            result = assemble_decision(
                probability_positive=0.2,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "denied"
        assert result["pricing_payload"] == {"tier": "unavailable", "approved": False}
        assert [r["code"] for r in result["refer_reasons"]] == ["PRICING_UNAVAILABLE"]

    def test_probability_rounded_to_four_places(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.123456789,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert result["probability"] == 0.1235

    def test_result_keys_stable(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.5,
                model_version=mv,
                drift_warnings=[],
                segment="personal",
            )

        assert set(result.keys()) == {
            "probability",
            "threshold",
            "prediction_label",
            "refer_reasons",
            "pricing_payload",
        }


class TestDeclineOverrides:
    """A denial made by a rule over a model approval carries the rule's code,
    so the waterfall and the denial email do not present it as the model's."""

    def test_pricing_decline_of_a_model_approval_is_marked(self):
        # Real pricing table: home PD 0.15 is above the 0.10 cutoff -> Decline.
        result = assemble_decision(
            probability_positive=0.85, model_version=_mk_version(0.5), drift_warnings=[], segment="home"
        )

        assert result["prediction_label"] == "denied"
        assert result["pricing_payload"].get("declined_model_approval") is True

    def test_pricing_decline_reports_its_reason_code(self):
        from apps.ml_engine.services.scoring.decision_assembly import decline_overrides

        result = assemble_decision(
            probability_positive=0.85, model_version=_mk_version(0.5), drift_warnings=[], segment="home"
        )
        overrides = decline_overrides(
            {"prediction": result["prediction_label"], "pricing_tier": result["pricing_payload"]}
        )

        assert [o["code"] for o in overrides] == ["PRICING_TIER_DECLINE"]
        assert overrides[0]["detail"]

    def test_a_model_denial_has_no_override(self):
        from apps.ml_engine.services.scoring.decision_assembly import decline_overrides

        result = assemble_decision(
            probability_positive=0.3, model_version=_mk_version(0.5), drift_warnings=[], segment="home"
        )

        assert result["pricing_payload"]["declined_model_approval"] is False
        assert decline_overrides({"prediction": "denied", "pricing_tier": result["pricing_payload"]}) == []

    def test_enforce_policy_hard_fails_report_policy_codes(self):
        from apps.ml_engine.services.scoring.decision_assembly import decline_overrides

        policy = {
            "mode": "enforce",
            "changed_model_decision": True,
            "hard_fails": ["P03"],
            "rationale_by_code": {"P03": "Undischarged bankrupt"},
        }

        assert decline_overrides({"prediction": "denied", "policy_decision": policy}) == [
            {"code": "POLICY_DECLINE_P03", "detail": "Undischarged bankrupt"}
        ]

    def test_shadow_policy_never_reports_a_decline(self):
        from apps.ml_engine.services.scoring.decision_assembly import decline_overrides

        policy = {"mode": "shadow", "changed_model_decision": False, "hard_fails": ["P03"]}

        assert decline_overrides({"prediction": "denied", "policy_decision": policy}) == []
