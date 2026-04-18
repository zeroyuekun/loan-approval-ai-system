"""Unit tests for the post-probability decision-assembly helper.

`assemble_decision` is the block carved out of `ModelPredictor.predict()`
during Arm C Phase 1. Given the model's raw positive-class probability, it:

- Resolves the approval threshold (model_version.optimal_threshold or 0.5
  fallback with a warning).
- Applies the per-employment-type group threshold if configured
  (EEOC 80% rule compliance).
- Derives the `approved`/`denied` label.
- Flags borderline cases + drift=severe cases for human review.
- Calls the D4 pricing engine, which may further decline an approved label
  when PD is above the top tier cutoff.

All six output fields are returned as a single dict so the caller doesn't
have to thread them through its own locals.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.ml_engine.services.decision_assembly import assemble_decision


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
        "apps.ml_engine.services.decision_assembly.get_tier",
        return_value=tier,
    )


class TestAssembleDecision:
    def test_approved_above_threshold(self):
        mv = _mk_version(optimal_threshold=0.6)
        with _patch_pricing(approved=True):
            result = assemble_decision(
                probability_positive=0.8,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "approved"
        assert result["probability"] == 0.8
        assert result["threshold"] == 0.6
        assert result["effective_threshold"] == 0.6
        assert result["requires_human_review"] is False

    def test_denied_below_threshold(self):
        mv = _mk_version(optimal_threshold=0.6)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.3,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "denied"

    def test_missing_threshold_falls_back_to_half_with_warning(self):
        mv = _mk_version(optimal_threshold=None)
        with _patch_pricing(), patch("apps.ml_engine.services.decision_assembly.logger") as log:
            result = assemble_decision(
                probability_positive=0.7,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        assert result["threshold"] == 0.5
        log.warning.assert_called_once()
        assert "optimal_threshold" in log.warning.call_args.args[0]

    def test_group_threshold_overrides_default(self):
        mv = _mk_version(optimal_threshold=0.6)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.55,
                model_version=mv,
                group_thresholds={"casual": 0.4},
                employment_type="casual",
                drift_warnings=[],
                segment="personal",
            )

        # Default threshold would deny at 0.55 < 0.6; casual group threshold 0.4 approves.
        assert result["effective_threshold"] == 0.4
        assert result["prediction_label"] == "approved"

    def test_borderline_within_10pp_flags_review(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.55,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        # |0.55 - 0.5| = 0.05 <= 0.10 → borderline
        assert result["requires_human_review"] is True

    def test_drift_severity_escalates_review(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.90,  # well clear of threshold
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[{"severity": "drift"}],
                segment="personal",
            )

        # Not borderline, but drift severity forces review.
        assert result["requires_human_review"] is True

    def test_pricing_tier_can_override_approved_to_denied(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing(approved=False):
            result = assemble_decision(
                probability_positive=0.85,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
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
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        assert result["prediction_label"] == "denied"

    def test_pricing_failure_returns_unavailable_payload_without_crashing(self):
        mv = _mk_version(optimal_threshold=0.5)
        with patch(
            "apps.ml_engine.services.decision_assembly.get_tier",
            side_effect=RuntimeError("pricing engine broken"),
        ):
            result = assemble_decision(
                probability_positive=0.8,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        # Model approves; pricing failed fail-open so label stays approved.
        assert result["prediction_label"] == "approved"
        assert result["pricing_payload"] == {"tier": "unavailable", "approved": True}

    def test_probability_rounded_to_four_places(self):
        mv = _mk_version(optimal_threshold=0.5)
        with _patch_pricing():
            result = assemble_decision(
                probability_positive=0.123456789,
                model_version=mv,
                group_thresholds=None,
                employment_type="full_time",
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
                group_thresholds=None,
                employment_type="full_time",
                drift_warnings=[],
                segment="personal",
            )

        assert set(result.keys()) == {
            "probability",
            "threshold",
            "effective_threshold",
            "prediction_label",
            "requires_human_review",
            "pricing_payload",
        }
