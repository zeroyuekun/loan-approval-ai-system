"""Feature-preparation helpers + hard-bounds table extracted from predictor.py.

- `safe_get_state(application)` — return the applicant's state, falling back
  to NSW when the column is missing (pre-migration databases raise).
- `validate_input(features, feature_bounds, user_bounds=None)` — range-check
  numeric features against the service's hard bounds, optionally widened by
  training-data-driven user bounds. Raises `ApplicationValidationError` with
  all violations aggregated so the caller can show them in one error.
- `clip_to_training_range(features, reference_distribution, hard_bounds)` —
  for columns with no hard bound, clip a value outside the range the model
  was trained on back into it (for the model only) and report the clip.
- `FEATURE_BOUNDS` — canonical hard-bounds dict consumed by `validate_input`,
  the `external` adapters (open_banking, macro_data, credit_bureau), and
  regression tests. Lives here (with `validate_input`) so the constraint and
  its enforcer stay co-located; re-exported from `predictor`.
"""

from __future__ import annotations

import logging
import math

__all__ = [
    "ApplicationValidationError",
    "FEATURE_BOUNDS",
    "clip_to_training_range",
    "safe_get_state",
    "validate_input",
]

logger = logging.getLogger(__name__)


# Bounds for input validation: (min, max) inclusive.
# `effective_loan_amount` ceiling must cover max loan_amount (5M) + max
# LMI premium (3% * 5M = 150k) with headroom, otherwise large high-LVR
# home loans fail validation before reaching the model.
FEATURE_BOUNDS = {
    "annual_income": (0, 10_000_000),
    "credit_score": (0, 1200),  # Equifax Australia scale
    "loan_amount": (0, 5_000_000),  # Aligned with LoanApplication.loan_amount MaxValueValidator
    "loan_term_months": (1, 600),
    "debt_to_income": (0.0, 100.0),
    "employment_length": (0, 60),
    "has_cosigner": (0, 1),
    "property_value": (0, 100_000_000),
    "deposit_amount": (0, 5_000_000),  # Cannot exceed loan amount
    "monthly_expenses": (0, 1_000_000),
    "existing_credit_card_limit": (0, 10_000_000),
    "number_of_dependants": (0, 10),  # Aligned with LoanApplication.number_of_dependants MaxValueValidator
    "has_hecs": (0, 1),
    "has_bankruptcy": (0, 1),
    "num_credit_enquiries_6m": (0, 50),
    "worst_arrears_months": (0, 36),
    "num_defaults_5yr": (0, 20),
    "credit_history_months": (0, 600),
    "total_open_accounts": (0, 50),
    "num_bnpl_accounts": (0, 20),
    "savings_balance": (0, 10_000_000),
    "salary_credit_regularity": (0, 1),
    "num_dishonours_12m": (0, 100),
    "avg_monthly_savings_rate": (-1, 1),
    "days_in_overdraft_12m": (0, 365),
    "rba_cash_rate": (0, 20),
    "unemployment_rate": (0, 30),
    "property_growth_12m": (-50, 100),
    "consumer_confidence": (0, 200),
    "income_verification_gap": (0, 10),
    "document_consistency_score": (0, 1),
    # CCR features
    "num_late_payments_24m": (0, 50),
    "worst_late_payment_days": (0, 90),
    "total_credit_limit": (0, 5_000_000),
    "credit_utilization_pct": (0, 1),
    "num_hardship_flags": (0, 10),
    "months_since_last_default": (0, 999),
    "num_credit_providers": (0, 30),
    # BNPL-specific
    "bnpl_total_limit": (0, 100_000),
    "bnpl_utilization_pct": (0, 1),
    "bnpl_late_payments_12m": (0, 50),
    "bnpl_monthly_commitment": (0, 10_000),
    # CDR/Open Banking transaction features
    "income_source_count": (0, 20),
    "rent_payment_regularity": (0, 1),
    "utility_payment_regularity": (0, 1),
    "essential_to_total_spend": (0, 1),
    "subscription_burden": (0, 1),
    "balance_before_payday": (-10_000, 1_000_000),
    "min_balance_30d": (-10_000, 1_000_000),
    "days_negative_balance_90d": (0, 90),
    # Geographic risk
    "postcode_default_rate": (0, 1),
    # Behavioral features
    "financial_literacy_score": (0.0, 1.0),
    # prepayment_buffer_months and negative_equity_flag are POST_OUTCOME_FEATURES
    # (computed after approval/disbursement) and must never appear as model inputs
    # at inference time. Removed from FEATURE_BOUNDS to prevent accidental inclusion
    # in validation or feature-engineering pipelines. See data_generator.POST_OUTCOME_FEATURES.
    "optimism_bias_flag": (0, 1),
    # Underwriter-internal variables exposed as features.
    "hem_benchmark": (0, 20_000),
    "hem_gap": (-20_000, 20_000),
    "lmi_premium": (0, 200_000),
    "effective_loan_amount": (0, 5_200_000),
}


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
    User bounds may only WIDEN a hard bound — never narrow it — and never
    reject on their own: a column with no hard bound is only checked for
    being a finite number. A value beyond the training range is a reason to
    clip for the model (`clip_to_training_range`), not to refuse a decision.

    Missing keys pass silently. Non-numeric or nan/inf values are rejected.
    All violations are collected and reported together so the caller shows a
    single actionable error.
    """
    bounds: dict = {**feature_bounds}
    if user_bounds:
        for col, (data_lo, data_hi) in user_bounds.items():
            if bounds.get(col) is not None:
                hard_lo, hard_hi = bounds[col]
                bounds[col] = (min(hard_lo, data_lo), max(hard_hi, data_hi))
            else:
                bounds[col] = None  # finite-number check only

    errors: list[str] = []
    for col, limits in bounds.items():
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
        if limits is None:
            continue
        lo, hi = limits
        if val < lo or val > hi:
            errors.append(f"{col}: {val} is outside valid range [{lo}, {hi}]")

    if errors:
        raise ApplicationValidationError("Input validation failed: " + "; ".join(errors))


def clip_to_training_range(features: dict, reference_distribution: dict | None, *, hard_bounds: dict) -> list[dict]:
    """Clip, in place, values the model never saw in training; return what was clipped.

    Only columns WITHOUT a hard (policy) bound are clipped: those used to be
    rejected on the training 1st/99th percentiles alone. The range is the
    training min/max (`percentiles[0]` / `percentiles[-1]` of the reference
    distribution), so a tree model scores the value at the edge of what it
    learned. Each clip is returned as a warning entry for the prediction record.
    """
    clipped: list[dict] = []
    if not reference_distribution:
        return clipped
    for col, ref in reference_distribution.items():
        if col in hard_bounds or not isinstance(ref, dict) or features.get(col) is None:
            continue
        percentiles = ref.get("percentiles") or []
        if len(percentiles) < 2:
            continue
        try:
            val = float(features[col])
        except (TypeError, ValueError):
            continue
        lo, hi = float(percentiles[0]), float(percentiles[-1])
        if lo <= val <= hi:
            continue
        bound = lo if val < lo else hi
        features[col] = bound
        clipped.append(
            {
                "feature": col,
                "value": val,
                "clipped_to": bound,
                "severity": "warning",
                "message": (
                    f"{col} value ({val:,.2f}) is outside the training range "
                    f"[{lo:,.2f}, {hi:,.2f}]; scored as {bound:,.2f}"
                ),
            }
        )
    return clipped
