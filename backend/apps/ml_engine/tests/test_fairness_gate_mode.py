"""Unit tests for the pre-activation fairness gate mode dispatcher.

The dispatcher is pure-functional — it takes the mode as an argument and
returns a structured decision. These tests exercise the full decision matrix
without Django ORM / settings / Celery dependencies. The integration into
`train_model_task` is tested separately at the task level.

Spec: docs/superpowers/specs/2026-05-07-ml-fairness-gate-mode-design.md
"""

from __future__ import annotations

import logging

import pytest

from apps.ml_engine.services.fairness_gate_mode import (
    DEFAULT_MODE,
    VALID_MODES,
    FairnessGateBlocked,
    evaluate_fairness_gate_for_activation,
    normalize_mode,
)

# ---------------------------------------------------------------------------
# Fairness payload fixtures
# ---------------------------------------------------------------------------


def _passing_fairness() -> dict:
    """All protected attributes pass the EEOC 80% rule."""
    return {
        "gender": {"disparate_impact_ratio": 0.92},
        "age_group": {"disparate_impact_ratio": 0.88},
    }


def _failing_fairness() -> dict:
    """`age_group` falls below the 0.80 threshold."""
    return {
        "gender": {"disparate_impact_ratio": 0.92},
        "age_group": {"disparate_impact_ratio": 0.78},
    }


# ---------------------------------------------------------------------------
# normalize_mode — invalid values collapse to warn (with a log line)
# ---------------------------------------------------------------------------


def test_normalize_mode_accepts_valid_values():
    for mode in VALID_MODES:
        assert normalize_mode(mode) == mode


def test_normalize_mode_collapses_unknown_to_warn(caplog):
    with caplog.at_level(logging.WARNING):
        assert normalize_mode("bogus") == DEFAULT_MODE
    assert any("Unknown ML_FAIRNESS_GATE_MODE" in r.message for r in caplog.records)


def test_normalize_mode_handles_none_silently():
    # None means "unset env var" — fall through to default without a noisy log.
    assert normalize_mode(None) == DEFAULT_MODE


# ---------------------------------------------------------------------------
# warn mode — preserves current pre-PR-#162 behaviour byte-identically
# ---------------------------------------------------------------------------


def test_warn_mode_passing_fairness_returns_activate_with_passing_result():
    decision = evaluate_fairness_gate_for_activation(_passing_fairness(), "warn")
    assert decision["action"] == "activate"
    assert decision["mode"] == "warn"
    assert decision["gate_result"]["passed"] is True
    assert decision["gate_result"]["failing_attributes"] == []


def test_warn_mode_failing_fairness_still_returns_activate():
    """Regression guard for the current behaviour — warn mode never blocks."""
    decision = evaluate_fairness_gate_for_activation(_failing_fairness(), "warn")
    assert decision["action"] == "activate"
    assert decision["mode"] == "warn"
    assert decision["gate_result"]["passed"] is False
    assert "age_group" in decision["gate_result"]["failing_attributes"]


def test_warn_mode_missing_fairness_data_returns_activate_with_no_result():
    """Empty fairness payload in warn mode skips the check silently — preserves
    current behaviour where the existing `if fairness_data:` guard short-circuits."""
    decision = evaluate_fairness_gate_for_activation({}, "warn")
    assert decision["action"] == "activate"
    assert decision["gate_result"] is None
    assert decision["mode"] == "warn"


# ---------------------------------------------------------------------------
# block mode — refuses activation on failure or missing evidence
# ---------------------------------------------------------------------------


def test_block_mode_passing_fairness_returns_activate():
    decision = evaluate_fairness_gate_for_activation(_passing_fairness(), "block")
    assert decision["action"] == "activate"
    assert decision["mode"] == "block"
    assert decision["gate_result"]["passed"] is True


def test_block_mode_failing_fairness_raises_with_attribute_names():
    with pytest.raises(FairnessGateBlocked) as excinfo:
        evaluate_fairness_gate_for_activation(_failing_fairness(), "block")
    msg = str(excinfo.value)
    assert "mode=block" in msg
    assert "age_group" in msg
    # Operators should see the remediation paths in the error message.
    assert "ML_FAIRNESS_GATE_MODE=warn" in msg


def test_block_mode_missing_fairness_data_raises_with_clear_wording():
    """Codex-finding-2 guarantee: missing fairness evidence is not a free pass.

    `check_fairness_gate({})` would return `{"passed": True}` because there are
    no failing attributes to enumerate. We must catch the empty case BEFORE
    delegating, otherwise an operator who forgot to enable the fairness
    evaluator could activate any model under block mode.
    """
    with pytest.raises(FairnessGateBlocked) as excinfo:
        evaluate_fairness_gate_for_activation({}, "block")
    msg = str(excinfo.value)
    assert "mode=block" in msg
    assert "no fairness data" in msg.lower()


def test_block_mode_does_not_call_check_fairness_gate_when_data_missing():
    """The empty-data raise must happen before any call into the gate logic.

    Patching `check_fairness_gate` and asserting it was not called proves the
    early-raise short-circuit is in place.
    """
    from unittest.mock import patch

    with patch("apps.ml_engine.services.fairness_gate_mode.check_fairness_gate") as mock_gate:
        with pytest.raises(FairnessGateBlocked):
            evaluate_fairness_gate_for_activation({}, "block")
    mock_gate.assert_not_called()


# ---------------------------------------------------------------------------
# off mode — escape hatch
# ---------------------------------------------------------------------------


def test_off_mode_skips_check_for_passing_data():
    decision = evaluate_fairness_gate_for_activation(_passing_fairness(), "off")
    assert decision["action"] == "skip_check"
    assert decision["gate_result"] is None
    assert decision["mode"] == "off"


def test_off_mode_skips_check_for_failing_data():
    """Off mode must not block, must not log a warning, must not record a result."""
    decision = evaluate_fairness_gate_for_activation(_failing_fairness(), "off")
    assert decision["action"] == "skip_check"
    assert decision["gate_result"] is None
    assert decision["mode"] == "off"


def test_off_mode_skips_check_for_missing_data():
    """Off mode must not raise even when no fairness data was recorded —
    that's the whole point of the escape hatch."""
    decision = evaluate_fairness_gate_for_activation({}, "off")
    assert decision["action"] == "skip_check"
    assert decision["gate_result"] is None
    assert decision["mode"] == "off"


def test_off_mode_does_not_call_check_fairness_gate():
    from unittest.mock import patch

    with patch("apps.ml_engine.services.fairness_gate_mode.check_fairness_gate") as mock_gate:
        evaluate_fairness_gate_for_activation(_failing_fairness(), "off")
    mock_gate.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown mode — coerced to warn (regression guard for misconfigured deployments)
# ---------------------------------------------------------------------------


def test_unknown_mode_falls_through_to_warn_for_failing_data():
    """A misconfigured deployment must never silently disable the gate. Unknown
    mode → warn → gate still runs, failure is recorded but activation proceeds."""
    decision = evaluate_fairness_gate_for_activation(_failing_fairness(), "bogus")
    assert decision["action"] == "activate"
    assert decision["mode"] == "warn"
    assert decision["gate_result"]["passed"] is False


def test_unknown_mode_does_not_block_even_with_failing_fairness():
    """Even with the worst fairness data, an unknown mode must not raise."""
    # No assertion needed beyond "this does not raise FairnessGateBlocked".
    evaluate_fairness_gate_for_activation(_failing_fairness(), "totally-made-up")


# ---------------------------------------------------------------------------
# FairnessGateBlocked is a RuntimeError subclass — operators / Celery / monitoring
# can catch it via the broader RuntimeError contract.
# ---------------------------------------------------------------------------


def test_fairness_gate_blocked_is_runtime_error():
    assert issubclass(FairnessGateBlocked, RuntimeError)
