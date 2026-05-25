"""Unit tests for the pre-activation promotion gate mode dispatcher.

The dispatcher is pure-functional — it takes a `PromotionDecision` and a
mode string and returns a structured decision. These tests construct
`PromotionDecision` instances directly (no DB, no Django boot, no Celery)
and exercise the full mode matrix.

The integration of `model_selector.promote_if_eligible` with the
`SimpleNamespace` candidate stub is mechanical (build stub → call function);
existing `test_metrics_production_grade.py::promote_if_eligible — gate matrix`
tests already exercise the gate logic with DB.

Spec: docs/superpowers/specs/2026-05-07-ml-promotion-gate-mode-design.md
"""

from __future__ import annotations

import logging

import pytest

from apps.ml_engine.services.model_selector import PromotionDecision
from apps.ml_engine.services.governance.promotion_gate_mode import (
    DEFAULT_MODE,
    VALID_MODES,
    PromotionGateBlocked,
    evaluate_promotion_gates_for_activation,
    normalize_mode,
)

# ---------------------------------------------------------------------------
# PromotionDecision fixtures — keep these terse; the gate-by-gate evidence
# isn't material to the dispatcher's logic, only `promoted` and `reasons`.
# ---------------------------------------------------------------------------


def _promoted_decision() -> PromotionDecision:
    return PromotionDecision(
        promoted=True,
        candidate_id="cand-123",
        champion_id="champ-456",
        reasons=["All gates passed"],
        gates={"max_psi": {"passed": True}, "ece": {"passed": True}},
    )


def _rejected_decision() -> PromotionDecision:
    return PromotionDecision(
        promoted=False,
        candidate_id="cand-123",
        champion_id="champ-456",
        reasons=[
            "PSI gate failed: max feature PSI 0.3500 exceeds 0.25 ceiling",
            "Calibration gate failed: ECE 0.0612 exceeds 0.03 ceiling",
        ],
        gates={"max_psi": {"passed": False}, "ece": {"passed": False}},
    )


def _rejected_decision_no_reasons() -> PromotionDecision:
    """Edge case — rejected with empty reasons list."""
    return PromotionDecision(
        promoted=False,
        candidate_id="cand-123",
        champion_id="champ-456",
        reasons=[],
        gates={},
    )


# ---------------------------------------------------------------------------
# normalize_mode
# ---------------------------------------------------------------------------


def test_normalize_mode_accepts_valid_values():
    for mode in VALID_MODES:
        assert normalize_mode(mode) == mode


def test_normalize_mode_collapses_unknown_to_warn(caplog):
    with caplog.at_level(logging.WARNING):
        assert normalize_mode("bogus") == DEFAULT_MODE
    assert any("Unknown ML_PROMOTION_GATE_MODE" in r.message for r in caplog.records)


def test_normalize_mode_handles_none_silently():
    assert normalize_mode(None) == DEFAULT_MODE


# ---------------------------------------------------------------------------
# warn mode — preserves current behaviour byte-identically (gates were never
# invoked from production paths before this PR; warn just records the decision
# without acting on it).
# ---------------------------------------------------------------------------


def test_warn_mode_promoted_returns_activate():
    decision = _promoted_decision()
    out = evaluate_promotion_gates_for_activation(decision, "warn")
    assert out["action"] == "activate"
    assert out["mode"] == "warn"
    assert out["decision"] is decision


def test_warn_mode_rejected_still_returns_activate():
    """Regression guard for current behaviour — warn mode never blocks even
    when gates report regressions vs the incumbent champion."""
    decision = _rejected_decision()
    out = evaluate_promotion_gates_for_activation(decision, "warn")
    assert out["action"] == "activate"
    assert out["mode"] == "warn"
    assert out["decision"] is decision


# ---------------------------------------------------------------------------
# block mode — refuses activation on rejected promotion
# ---------------------------------------------------------------------------


def test_block_mode_promoted_returns_activate():
    decision = _promoted_decision()
    out = evaluate_promotion_gates_for_activation(decision, "block")
    assert out["action"] == "activate"
    assert out["mode"] == "block"
    assert out["decision"] is decision


def test_block_mode_rejected_raises_with_reasons():
    decision = _rejected_decision()
    with pytest.raises(PromotionGateBlocked) as excinfo:
        evaluate_promotion_gates_for_activation(decision, "block")
    msg = str(excinfo.value)
    assert "mode=block" in msg
    assert "PSI gate failed" in msg
    assert "Calibration gate failed" in msg


def test_block_mode_includes_remediation_hint_in_error():
    """Operators should see the override path in the error message."""
    decision = _rejected_decision()
    with pytest.raises(PromotionGateBlocked) as excinfo:
        evaluate_promotion_gates_for_activation(decision, "block")
    assert "ML_PROMOTION_GATE_MODE=warn" in str(excinfo.value)


def test_block_mode_rejected_without_reasons_still_raises():
    """Defensive — if a future PromotionDecision returns rejected with empty
    reasons, the dispatcher must still block (and surface a sensible message)."""
    decision = _rejected_decision_no_reasons()
    with pytest.raises(PromotionGateBlocked) as excinfo:
        evaluate_promotion_gates_for_activation(decision, "block")
    assert "mode=block" in str(excinfo.value)


# ---------------------------------------------------------------------------
# off mode — escape hatch
# ---------------------------------------------------------------------------


def test_off_mode_skips_check_for_promoted_decision():
    out = evaluate_promotion_gates_for_activation(_promoted_decision(), "off")
    assert out["action"] == "skip_check"
    assert out["decision"] is None
    assert out["mode"] == "off"


def test_off_mode_skips_check_for_rejected_decision():
    """Off mode must not block, must not record the decision."""
    out = evaluate_promotion_gates_for_activation(_rejected_decision(), "off")
    assert out["action"] == "skip_check"
    assert out["decision"] is None
    assert out["mode"] == "off"


# ---------------------------------------------------------------------------
# Unknown mode — coerced to warn (regression guard for misconfigured deployments)
# ---------------------------------------------------------------------------


def test_unknown_mode_falls_through_to_warn_for_rejected_decision():
    """A misconfigured deployment must never silently disable the gate."""
    out = evaluate_promotion_gates_for_activation(_rejected_decision(), "bogus")
    assert out["action"] == "activate"
    assert out["mode"] == "warn"


def test_unknown_mode_does_not_block_even_with_rejected_decision():
    """Even with the worst possible decision, unknown mode must not raise."""
    evaluate_promotion_gates_for_activation(_rejected_decision(), "totally-made-up")


# ---------------------------------------------------------------------------
# Exception subclass contract
# ---------------------------------------------------------------------------


def test_promotion_gate_blocked_is_runtime_error():
    """The outer train_model_task wrapper catches RuntimeError to release
    the training lock; PromotionGateBlocked must satisfy that contract."""
    assert issubclass(PromotionGateBlocked, RuntimeError)
