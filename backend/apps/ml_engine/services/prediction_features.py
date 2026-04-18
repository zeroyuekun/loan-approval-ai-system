"""Build the model-ready feature dict from a `LoanApplication` at predict time.

Two functions carved out of `ModelPredictor.predict` so the predictor no
longer carries a 140-line inline feature-extraction block:

- `build_prediction_features(application, safe_get_state_fn, imputation_values)`
  — walks the LoanApplication ORM object, extracts every column the model
  expects, applies imputation for nullable fields, and returns a plain
  dict. The `safe_get_state_fn` lets the predictor pass in its own
  unmigrated-db-safe state getter without this module needing Django.

- `derive_underwriter_features(features)` — computes the underwriter-internal
  features (`hem_benchmark`, `hem_gap`, `lmi_premium`, `effective_loan_amount`)
  that mirror what the training-time `UnderwritingEngine` produces. These are
  exposed to the model so the scorecard can learn AU-lender-style HEM floors
  and LMI capitalisation policies. Mutates `features` in place.

Both functions are side-effect-free other than the in-place dict mutation
in `derive_underwriter_features`. They don't import from `predictor.py`
(no circular dependency).
"""

from __future__ import annotations

import logging

from apps.ml_engine.services.underwriting_engine import UnderwritingEngine

__all__ = ["build_prediction_features", "derive_underwriter_features"]

logger = logging.getLogger(__name__)


def build_prediction_features(
    application,
    *,
    safe_get_state_fn,
    imputation_values: dict,
) -> dict:
    """Flatten a LoanApplication into the model's feature dict.

    Uses `getattr(..., None)` for nullable fields so unmigrated databases
    don't crash; falls back to the `imputation_values` dict (training-time
    medians) or a hard-coded sensible default.
    """

    def _num(field, default, cast=float):
        val = getattr(application, field, None)
        if val is None:
            return cast(imputation_values.get(field, default))
        return cast(val)

    def _flag(field, default=False):
        return int(getattr(application, field, default))

    def _cat(field, default):
        return getattr(application, field, None) or default

    return {
        # Core application fields (always present)
        "annual_income": float(application.annual_income),
        "credit_score": application.credit_score,
        "loan_amount": float(application.loan_amount),
        "loan_term_months": application.loan_term_months,
        "debt_to_income": float(application.debt_to_income),
        "employment_length": application.employment_length,
        "has_cosigner": int(application.has_cosigner),
        "purpose": application.purpose,
        "home_ownership": application.home_ownership,
        "number_of_dependants": application.number_of_dependants,
        "employment_type": application.employment_type,
        "applicant_type": application.applicant_type,
        "has_hecs": _flag("has_hecs"),
        "has_bankruptcy": _flag("has_bankruptcy"),
        "state": safe_get_state_fn(application),
        "is_existing_customer": _flag("is_existing_customer"),
        "gambling_transaction_flag": _flag("gambling_transaction_flag"),
        # Nullable core fields
        "property_value": _num("property_value", 0),
        "deposit_amount": _num("deposit_amount", 0),
        "monthly_expenses": _num("monthly_expenses", 2500),
        "existing_credit_card_limit": _num("existing_credit_card_limit", 0),
        # Bureau features
        "num_credit_enquiries_6m": _num("num_credit_enquiries_6m", 1, int),
        "worst_arrears_months": _num("worst_arrears_months", 0, int),
        "num_defaults_5yr": _num("num_defaults_5yr", 0, int),
        "credit_history_months": _num("credit_history_months", 120, int),
        "total_open_accounts": _num("total_open_accounts", 3, int),
        "num_bnpl_accounts": _num("num_bnpl_accounts", 0, int),
        # Behavioural features
        "savings_balance": _num("savings_balance", 10000),
        "salary_credit_regularity": _num("salary_credit_regularity", 0.8),
        "num_dishonours_12m": _num("num_dishonours_12m", 0, int),
        "avg_monthly_savings_rate": _num("avg_monthly_savings_rate", 0.10),
        "days_in_overdraft_12m": _num("days_in_overdraft_12m", 0, int),
        # Macroeconomic context
        "rba_cash_rate": _num("rba_cash_rate", 4.10),
        "unemployment_rate": _num("unemployment_rate", 3.8),
        "property_growth_12m": _num("property_growth_12m", 5.0),
        "consumer_confidence": _num("consumer_confidence", 95.0),
        # Application integrity
        "income_verification_gap": _num("income_verification_gap", 1.0),
        "document_consistency_score": _num("document_consistency_score", 0.9),
        # Open Banking features
        "savings_trend_3m": _cat("savings_trend_3m", "flat"),
        "discretionary_spend_ratio": _num("discretionary_spend_ratio", 0.35),
        "bnpl_active_count": _num("bnpl_active_count", 0, int),
        "overdraft_frequency_90d": _num("overdraft_frequency_90d", 0, int),
        "income_verification_score": _num("income_verification_score", 0.85),
        # CCR features
        "num_late_payments_24m": _num("num_late_payments_24m", 0, int),
        "worst_late_payment_days": _num("worst_late_payment_days", 0, int),
        "total_credit_limit": _num("total_credit_limit", 20000.0),
        "credit_utilization_pct": _num("credit_utilization_pct", 0.30),
        "num_hardship_flags": _num("num_hardship_flags", 0, int),
        "months_since_last_default": _num("months_since_last_default", 999),
        "num_credit_providers": _num("num_credit_providers", 2, int),
        # BNPL-specific
        "bnpl_total_limit": _num("bnpl_total_limit", 0.0),
        "bnpl_utilization_pct": _num("bnpl_utilization_pct", 0.0),
        "bnpl_late_payments_12m": _num("bnpl_late_payments_12m", 0, int),
        "bnpl_monthly_commitment": _num("bnpl_monthly_commitment", 0.0),
        # CDR/Open Banking transaction features
        "income_source_count": _num("income_source_count", 1, int),
        "rent_payment_regularity": _num("rent_payment_regularity", 0.85),
        "utility_payment_regularity": _num("utility_payment_regularity", 0.90),
        "essential_to_total_spend": _num("essential_to_total_spend", 0.50),
        "subscription_burden": _num("subscription_burden", 0.05),
        "balance_before_payday": _num("balance_before_payday", 2000.0),
        "min_balance_30d": _num("min_balance_30d", 500.0),
        "days_negative_balance_90d": _num("days_negative_balance_90d", 0, int),
        # Geographic risk
        "postcode_default_rate": _num("postcode_default_rate", 0.015),
        "industry_risk_tier": _cat("industry_risk_tier", "medium"),
        # Training features not on LoanApplication — imputed at inference
        "industry_anzsic": _cat("industry_anzsic", "N"),
        "hecs_debt_balance": _num("hecs_debt_balance", 0.0),
        "existing_property_count": _num("existing_property_count", 0, int),
        "cash_advance_count_12m": _num("cash_advance_count_12m", 0, int),
        "monthly_rent": _num("monthly_rent", 0.0),
        "gambling_spend_ratio": _num("gambling_spend_ratio", 0.0),
        "help_repayment_monthly": _num("help_repayment_monthly", 0.0),
    }


def derive_underwriter_features(features: dict) -> None:
    """Compute HEM benchmark/gap and LVR-driven LMI policy vars in place.

    Mirrors the training-time `UnderwritingEngine` so the served model sees
    the same policy-aware features it learned from. Falls back to a fixed
    HEM default if the engine lookup raises — inference must not fail.
    """
    try:
        _uw = UnderwritingEngine()
        features["hem_benchmark"] = float(
            _uw.get_hem(
                features["applicant_type"],
                int(features["number_of_dependants"]),
                float(features["annual_income"]),
                features["state"],
            )
        )
    except Exception:
        features["hem_benchmark"] = 2950.0

    features["hem_gap"] = round(
        float(features["monthly_expenses"]) - features["hem_benchmark"], 2
    )

    is_home = features["purpose"] in ("home", "investment")
    property_value = float(features.get("property_value", 0.0) or 0.0)
    lvr_ratio = (float(features["loan_amount"]) / property_value) if property_value > 0 else 0.0

    if lvr_ratio > 0.90:
        lmi_rate = 0.03
    elif lvr_ratio > 0.85:
        lmi_rate = 0.02
    elif lvr_ratio > 0.80:
        lmi_rate = 0.01
    else:
        lmi_rate = 0.0

    features["lmi_premium"] = round(
        float(features["loan_amount"]) * lmi_rate * (1 if is_home else 0), 2
    )
    features["effective_loan_amount"] = round(
        float(features["loan_amount"]) + features["lmi_premium"], 2
    )
