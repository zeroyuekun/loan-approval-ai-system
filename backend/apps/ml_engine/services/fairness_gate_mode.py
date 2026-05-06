"""Mode dispatcher for the pre-activation fairness gate.

Wraps `apps.ml_engine.services.fairness_gate.check_fairness_gate` with a
three-mode policy: warn (current behaviour — log + flag, leave active),
block (refuse activation; old segment models keep serving), off (skip the
check entirely). The dispatcher itself is pure-functional and unit-testable
without Django ORM / settings boot — it takes the mode as an argument and
returns a structured decision; only `tasks.py` reads the
`ML_FAIRNESS_GATE_MODE` setting and delegates here.

See `docs/superpowers/specs/2026-05-07-ml-fairness-gate-mode-design.md`.
"""

from __future__ import annotations

import logging

from apps.ml_engine.services.fairness_gate import check_fairness_gate

logger = logging.getLogger(__name__)


VALID_MODES = ("warn", "block", "off")
DEFAULT_MODE = "warn"


class FairnessGateBlocked(RuntimeError):
    """Raised in `block` mode when activation should be refused.

    The error message is structured for operator visibility — it names the
    failing protected attributes (or the missing-evidence case) and the
    remediation paths (set ML_FAIRNESS_GATE_MODE=warn after manual review,
    or fix training distribution and retrain).
    """


def normalize_mode(mode: str | None) -> str:
    """Coerce arbitrary input to a valid mode; unknown values collapse to warn.

    Mirrors the pattern in `credit_policy.py:405` for unknown overlay modes —
    a misconfigured deployment never silently disables the gate.
    """
    if mode in VALID_MODES:
        return mode
    if mode is not None:
        logger.warning(
            "Unknown ML_FAIRNESS_GATE_MODE=%r — defaulting to %r",
            mode,
            DEFAULT_MODE,
        )
    return DEFAULT_MODE


def evaluate_fairness_gate_for_activation(fairness_data: dict, mode: str) -> dict:
    """Decide whether activation should proceed given fairness data + mode.

    Args:
        fairness_data: The `metrics["fairness"]` payload from the trainer —
            a dict keyed by protected attribute name with `disparate_impact_ratio`
            etc. Empty dict means the trainer recorded no fairness evidence.
        mode: One of "warn", "block", or "off". Unknown values are coerced to
            "warn" via `normalize_mode`.

    Returns:
        {
            "action": "activate" | "skip_check",
            "gate_result": dict | None,   # check_fairness_gate output, or None
                                          # for off mode / no-data warn mode
            "mode": str,                  # normalized mode that was applied
        }

    Raises:
        FairnessGateBlocked: in `block` mode when fairness evidence is missing
            or the gate failed. The caller (tasks.py) is responsible for
            ensuring this raise happens BEFORE any model-activation transaction
            so old segment models keep serving.
    """
    mode = normalize_mode(mode)

    if mode == "off":
        return {"action": "skip_check", "gate_result": None, "mode": "off"}

    if not fairness_data:
        if mode == "block":
            raise FairnessGateBlocked(
                "Activation blocked (mode=block): no fairness data recorded. "
                "Re-run training with the fairness evaluator enabled, or set "
                "ML_FAIRNESS_GATE_MODE=warn after manual review."
            )
        # warn mode + no data — preserve current behaviour: skip silently,
        # don't store a gate result, don't flag for review.
        return {"action": "activate", "gate_result": None, "mode": mode}

    gate_result = check_fairness_gate(fairness_data)

    if mode == "block" and not gate_result["passed"]:
        raise FairnessGateBlocked(
            f"Activation blocked (mode=block): failing protected attributes "
            f"{gate_result['failing_attributes']} (min DIR="
            f"{gate_result['minimum_dir']}). Set ML_FAIRNESS_GATE_MODE=warn "
            "after manual review, or fix training distribution and retrain."
        )

    return {"action": "activate", "gate_result": gate_result, "mode": mode}
