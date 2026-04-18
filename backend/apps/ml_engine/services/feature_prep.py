"""Feature-preparation helpers extracted from predictor.py.

Two focused helpers that the predictor orchestrator previously carried as
methods but that have no dependency on predictor state:

- `safe_get_state(application)` — return the applicant's state, falling back
  to NSW when the column is missing (pre-migration databases raise).
- `validate_input(features, feature_bounds, user_bounds=None)` — range-check
  numeric features against the service's hard bounds, optionally widened by
  training-data-driven user bounds. Raises `ApplicationValidationError` with
  all violations aggregated so the caller can show them in one error.

Extracted in Arm C Phase 1 so the predictor focuses on orchestration.
"""

from __future__ import annotations

import logging
import math

__all__ = [
    "ApplicationValidationError",
    "safe_get_state",
    "validate_input",
]

logger = logging.getLogger(__name__)


class ApplicationValidationError(ValueError):
    """Raised when an application's feature values fail basic sanity checks."""


def safe_get_state(application) -> str:
    """Return the application's state, defaulting to NSW if absent or unreadable.

    Databases that pre-date the `state` column raise on attribute access; we
    catch broadly and return the default so prediction can still proceed.
    """
    try:
        state = getattr(application, "state", None)
        if state:
            return state
    except Exception as e:  # noqa: BLE001 — unmigrated-db fallback is broad by design
        logger.debug("Could not read state from application, defaulting to NSW: %s", e)
    return "NSW"


def validate_input(
    features: dict,
    feature_bounds: dict,
    *,
    user_bounds: dict | None = None,
) -> None:
    """Range-check numeric features, raising `ApplicationValidationError` on violations.

    `feature_bounds` is the hard-coded service bounds map (min, max per field).
    `user_bounds` is an optional data-driven map (e.g. training-set quantiles).
    Per the v1.9 guarantee, user_bounds may only WIDEN hard bounds — never
    narrow them — so legitimate edge-case applicants (credit_score 620, 3-mo
    arrears, etc.) cannot be rejected by a too-tight training sample.

    Missing keys pass silently. Non-numeric or nan/inf values are rejected.
    All violations are collected and reported together so the caller shows a
    single actionable error.
    """
    bounds = {**feature_bounds}
    if user_bounds:
        for col, (data_lo, data_hi) in user_bounds.items():
            if col in bounds:
                hard_lo, hard_hi = bounds[col]
                bounds[col] = (min(hard_lo, data_lo), max(hard_hi, data_hi))
            else:
                bounds[col] = (data_lo, data_hi)

    errors: list[str] = []
    for col, (lo, hi) in bounds.items():
        val = features.get(col)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            errors.append(f"{col}: cannot convert {val!r} to number")
            continue
        if math.isnan(val) or math.isinf(val):
            errors.append(f"{col}: invalid value (nan/inf not allowed)")
            continue
        if val < lo or val > hi:
            errors.append(f"{col}: {val} is outside valid range [{lo}, {hi}]")

    if errors:
        raise ApplicationValidationError("Input validation failed: " + "; ".join(errors))
