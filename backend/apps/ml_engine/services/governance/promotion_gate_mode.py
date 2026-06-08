"""Mode dispatcher for the pre-activation champion-challenger promotion gate.

Wraps `apps.ml_engine.services.model_selector.promote_if_eligible` (KS, PSI,
ECE, AUC regression gates) with a three-mode policy: warn (gates run, decision
recorded, model activates regardless — current behaviour byte-identical since
the gates were never invoked from production paths before), block (refuse
activation when any gate fails; old segment models keep serving), off (skip
the check entirely).

The dispatcher itself is pure-functional and unit-testable without Django ORM
boot — it takes the mode as an argument and returns a structured decision.
Only `tasks.py` reads the `ML_PROMOTION_GATE_MODE` setting and delegates here.

Sibling to `fairness_gate_mode.py`. The two dispatchers are intentionally
parallel so operators learn one mode pattern that applies to both gates.

See `docs/superpowers/specs/2026-05-07-ml-promotion-gate-mode-design.md`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.ml_engine.services.model_selector import PromotionDecision

logger = logging.getLogger(__name__)


VALID_MODES = ("warn", "block", "off")
DEFAULT_MODE = "warn"


class PromotionGateBlocked(RuntimeError):
    """Raised in `block` mode when the champion-challenger promotion gates
    rejected the candidate. The error message includes the failed-gate reasons
    from the underlying `PromotionDecision` plus the override path
    (set ML_PROMOTION_GATE_MODE=warn after manual review)."""


def normalize_mode(mode: str | None) -> str:
    """Coerce arbitrary input to a valid mode; unknown values collapse to warn.

    Mirrors the pattern in `credit_policy.py:405` and
    `fairness_gate_mode.normalize_mode` — a misconfigured deployment never
    silently disables the gate.
    """
    if mode in VALID_MODES:
        return mode
    if mode is not None:
        logger.warning(
            "Unknown ML_PROMOTION_GATE_MODE=%r — defaulting to %r",
            mode,
            DEFAULT_MODE,
        )
    return DEFAULT_MODE


def evaluate_promotion_gates_for_activation(
    decision: PromotionDecision,
    mode: str,
) -> dict:
    """Decide whether activation should proceed given a promotion decision + mode.

    Args:
        decision: The `PromotionDecision` returned by
            `model_selector.promote_if_eligible(candidate_stub)`. Carries the
            promoted bool, gate-by-gate evidence, reasons, and champion id.
        mode: One of "warn", "block", or "off". Unknown values are coerced to
            "warn" via `normalize_mode`.

    Returns:
        {
            "action": "activate" | "skip_check",
            "decision": PromotionDecision | None,   # None when mode=="off"
            "mode": str,                            # normalized mode
        }

    Raises:
        PromotionGateBlocked: in `block` mode when `decision.promoted` is False.
            The caller (tasks.py) is responsible for ensuring this raise happens
            BEFORE any model-activation transaction so old segment models keep
            serving.
    """
    mode = normalize_mode(mode)

    if mode == "off":
        return {"action": "skip_check", "decision": None, "mode": "off"}

    if mode == "block" and not decision.promoted:
        reasons = "; ".join(decision.reasons) if decision.reasons else "(no reasons recorded)"
        raise PromotionGateBlocked(
            f"Activation blocked (mode=block): champion-challenger promotion "
            f"gates failed: {reasons}. Set ML_PROMOTION_GATE_MODE=warn after "
            "manual review, or fix the regression and retrain."
        )

    return {"action": "activate", "decision": decision, "mode": mode}
