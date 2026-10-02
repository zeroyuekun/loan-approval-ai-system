"""Optional maker/checker gate for high-value officer overturns.

Any officer-role user can overturn a denial to approved and trigger an
approval email. This optional gate adds a second control on high-value
overturns. It mirrors the warn/block/off dispatcher pattern of
``fairness_gate_mode.py``: pure-functional, takes the mode + facts as
arguments and returns a structured decision; only
``decision_review.apply_review_outcome`` reads the ``DECISION_OVERTURN_*``
settings and delegates here, so the API and the Django admin share the gate.

Default mode is ``off`` — behaviour is UNCHANGED until an operator sets
``DECISION_OVERTURN_GATE_MODE`` (safe, reversible). The gate only fires when
the loan amount meets or exceeds the configured threshold.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_MODES = ("off", "second_approver")
DEFAULT_MODE = "off"
# Two-factor authentication was removed. "2fa" maps to the stricter remaining
# mode so a deployment still configured with it keeps a gate.
_LEGACY_MODES = {"2fa": "second_approver"}


def normalize_overturn_mode(mode: str | None) -> str:
    """Coerce arbitrary input to a valid mode; unknown values collapse to off.

    A misconfigured deployment never silently enables a stricter gate than
    intended — unknown values fall back to the no-op ``off`` mode. The legacy
    ``2fa`` value is the exception: it maps to ``second_approver``.
    """
    if mode in _LEGACY_MODES:
        logger.warning(
            "DECISION_OVERTURN_GATE_MODE=%r is no longer supported; using %r",
            mode,
            _LEGACY_MODES[mode],
        )
        return _LEGACY_MODES[mode]
    if mode in VALID_MODES:
        return mode
    if mode is not None:
        logger.warning(
            "Unknown DECISION_OVERTURN_GATE_MODE=%r — defaulting to %r",
            mode,
            DEFAULT_MODE,
        )
    return DEFAULT_MODE


def evaluate_overturn_gate(amount, threshold, mode) -> dict:
    """Decide whether an officer overturn may proceed.

    Args:
        amount: The application loan amount (float).
        threshold: The amount at/above which the gate applies (float).
        mode: One of "off", "second_approver" (coerced via
            ``normalize_overturn_mode``).

    Returns:
        {"allowed": bool, "reason": str | None, "mode": str}
    """
    mode = normalize_overturn_mode(mode)

    if mode == "off":
        return {"allowed": True, "reason": None, "mode": mode}

    if amount < threshold:
        # Low-value overturns are not gated regardless of mode.
        return {"allowed": True, "reason": None, "mode": mode}

    if mode == "second_approver":
        # A second-approver workflow is not yet wired; in this mode high-value
        # overturns are blocked at the API and must be actioned through the
        # (out-of-band) dual-approval process.
        return {
            "allowed": False,
            "reason": (
                f"Overturning a denial of ${amount:,.0f} (>= ${threshold:,.0f}) requires a "
                "second approver. This overturn must be actioned via the dual-approval process."
            ),
            "mode": mode,
        }

    # Unreachable (normalize_overturn_mode guarantees a known mode), but fail safe.
    return {"allowed": True, "reason": None, "mode": mode}
