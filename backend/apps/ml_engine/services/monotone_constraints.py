"""Monotone constraint schedule for the XGBoost approval model.

Keeping this in one file (rather than buried in trainer.py) serves three audit
goals required by ASIC RG 209 responsible-lending guidance and APRA CPS 220
model-risk reviewers:

1. **Traceability.** Every signed feature has a documented rationale (see
   `RATIONALE`) so that a regulator can see why "higher credit_score → more
   approvable" is a hard monotone constraint rather than a learned fluke.

2. **Stability.** Tree ensembles are sensitive to training-data quirks; without
   monotonicity, a single bad bootstrap sample can produce spurious reversals
   (e.g. raising income slightly decreases predicted approval). Monotone
   constraints eliminate that failure mode for the signed features.

3. **Fair-lending robustness.** Non-monotone behaviour on protected
   correlates (income proxies, geography) is a disparate-impact liability.
   Forcing monotonicity on the obvious directions removes an entire class of
   defence-in-depth failure.

Constraints are applied symmetrically to original and log-transformed copies
of the same feature (e.g. `annual_income` and `log_annual_income` both get
+1), since a log is a monotone transform and leaving one unconstrained would
let the model route around the constraint on the other.

Features not in `MONOTONE_CONSTRAINTS` fall through to the default 0
(unconstrained) via `build_xgboost_monotone_spec`. Unconstrained features are
typically interactions, macro context, or quantities whose direction is
ambiguous (e.g. `loan_term_months` — longer lowers the monthly repayment but
extends rate-risk exposure).
"""

from typing import Iterable

# Sentinel values for monotone_constraints semantics.
POSITIVE = 1   # Higher value → more likely approved
NEGATIVE = -1  # Higher value → less likely approved
UNCONSTRAINED = 0


# The authoritative sign schedule. Every signed numeric feature the
# ModelTrainer exposes to XGBoost belongs here; unlisted features default to
# UNCONSTRAINED via build_xgboost_monotone_spec.
MONOTONE_CONSTRAINTS = {
    # --- POSITIVE: higher value increases approval probability ---
    "annual_income": POSITIVE,
    "log_annual_income": POSITIVE,
    "credit_score": POSITIVE,
    "employment_length": POSITIVE,
    "savings_balance": POSITIVE,
    "credit_history_months": POSITIVE,
    "salary_credit_regularity": POSITIVE,
    "income_verification_score": POSITIVE,
    "property_value": POSITIVE,
    "deposit_amount": POSITIVE,
    "deposit_ratio": POSITIVE,
    "has_cosigner": POSITIVE,
    "savings_to_loan_ratio": POSITIVE,
    "debt_service_coverage": POSITIVE,
    "rent_payment_regularity": POSITIVE,
    "utility_payment_regularity": POSITIVE,
    "avg_monthly_savings_rate": POSITIVE,
    "consumer_confidence": POSITIVE,
    "document_consistency_score": POSITIVE,
    "hem_surplus": POSITIVE,
    "uncommitted_monthly_income": POSITIVE,
    "net_monthly_surplus": POSITIVE,
    "income_source_count": POSITIVE,
    "financial_literacy_score": POSITIVE,
    "prepayment_buffer_months": POSITIVE,
    "months_since_last_default": POSITIVE,
    "is_existing_customer": POSITIVE,
    "income_per_dependant": POSITIVE,
    "serviceability_ratio": POSITIVE,

    # --- NEGATIVE: higher value decreases approval probability ---
    "debt_to_income": NEGATIVE,
    "loan_amount": NEGATIVE,
    "log_loan_amount": NEGATIVE,
    "loan_to_income": NEGATIVE,
    "num_defaults_5yr": NEGATIVE,
    "worst_arrears_months": NEGATIVE,
    "existing_credit_card_limit": NEGATIVE,
    "monthly_expenses": NEGATIVE,
    "num_credit_enquiries_6m": NEGATIVE,
    "bureau_risk_score": NEGATIVE,
    "stressed_dsr": NEGATIVE,
    "stressed_repayment": NEGATIVE,
    "has_bankruptcy": NEGATIVE,
    "num_dishonours_12m": NEGATIVE,
    "days_in_overdraft_12m": NEGATIVE,
    "number_of_dependants": NEGATIVE,
    "num_bnpl_accounts": NEGATIVE,
    "bnpl_active_count": NEGATIVE,
    "credit_card_burden": NEGATIVE,
    "expense_to_income": NEGATIVE,
    "lvr": NEGATIVE,
    "lvr_x_dti": NEGATIVE,
    "num_late_payments_24m": NEGATIVE,
    "worst_late_payment_days": NEGATIVE,
    "credit_utilization_pct": NEGATIVE,
    "num_hardship_flags": NEGATIVE,
    "bnpl_total_limit": NEGATIVE,
    "bnpl_utilization_pct": NEGATIVE,
    "bnpl_late_payments_12m": NEGATIVE,
    "bnpl_monthly_commitment": NEGATIVE,
    "essential_to_total_spend": NEGATIVE,
    "subscription_burden": NEGATIVE,
    "days_negative_balance_90d": NEGATIVE,
    "postcode_default_rate": NEGATIVE,
    "unemployment_rate": NEGATIVE,
    "income_verification_gap": NEGATIVE,
    "hem_gap": NEGATIVE,
    "gambling_transaction_flag": NEGATIVE,
    "enquiry_intensity": NEGATIVE,
    "cash_advance_count_12m": NEGATIVE,
    "help_repayment_monthly": NEGATIVE,
    "hecs_debt_balance": NEGATIVE,
    "gambling_spend_ratio": NEGATIVE,
    "monthly_rent": NEGATIVE,
    "lmi_premium": NEGATIVE,
    "effective_loan_amount": NEGATIVE,
    "overdraft_frequency_90d": NEGATIVE,
    "stress_index": NEGATIVE,
}


# One-sentence justification for every signed feature, consumed by the MRM
# dossier generator (D7) and interview talking points. Keeping the rationale
# adjacent to the constraint prevents sign-flips from slipping through review.
RATIONALE = {
    # POSITIVE rationales
    "annual_income": "Higher income increases serviceability — core AU responsible-lending assumption.",
    "log_annual_income": "Log transform of annual_income; monotone transform, same sign as source.",
    "credit_score": "Higher Equifax score indicates lower historical default probability.",
    "employment_length": "Longer tenure proxies income stability; CBA/NAB scorecards apply length floors.",
    "savings_balance": "Larger liquid buffer lowers short-term default risk during shocks.",
    "credit_history_months": "More history = thicker file; thin files penalised across AU bureaux.",
    "salary_credit_regularity": "Regular salary credits confirm employment reality, reduce income-fabrication risk.",
    "income_verification_score": "CDR/Basiq-confirmed income is strictly safer than self-attested.",
    "property_value": "Higher collateral value reduces LGD for secured lending (APS 112).",
    "deposit_amount": "Larger deposit reduces LVR and demonstrates savings discipline.",
    "deposit_ratio": "deposit / loan_amount — direct proxy for equity skin-in-the-game.",
    "has_cosigner": "Guarantor increases recovery pool; monotonically safer.",
    "savings_to_loan_ratio": "More savings relative to loan = more shock-absorption capacity.",
    "debt_service_coverage": "DSCR > 1 means income covers repayments with buffer; linear in safety.",
    "rent_payment_regularity": "Consistent rent payments predict mortgage payment consistency.",
    "utility_payment_regularity": "Consistent utility payments are a cheap positive signal in thin files.",
    "avg_monthly_savings_rate": "Positive savings rate demonstrates cash-flow surplus.",
    "consumer_confidence": "Higher macro confidence lowers tail-event probability during loan term.",
    "document_consistency_score": "Consistent docs = lower fraud risk; monotone in data quality.",
    "hem_surplus": "Income − HEM floor; larger surplus = more serviceability headroom.",
    "uncommitted_monthly_income": "After fixed commitments; larger = more affordability buffer.",
    "net_monthly_surplus": "Income − expenses; foundational serviceability quantity.",
    "income_source_count": "Income diversification reduces concentration risk on a single employer.",
    "financial_literacy_score": "Higher literacy = better decision making; TMD-aligned protective factor.",
    "prepayment_buffer_months": "Months of repayments already paid ahead reduces imminent default risk.",
    "months_since_last_default": "Longer since default = more recovery evidence; monotone in safety.",
    "is_existing_customer": "Known customer behaviour is strictly more informative than acquired-unknown.",
    "income_per_dependant": "More income per dependant = more discretionary buffer.",
    "serviceability_ratio": "Aggregated serviceability score; direction matches individual drivers.",
    # NEGATIVE rationales
    "debt_to_income": "APRA limits above DTI=6; higher = less serviceability (APS 220 focus).",
    "loan_amount": "Larger loans = larger repayment shocks under stress.",
    "log_loan_amount": "Log transform of loan_amount; monotone transform, same sign.",
    "loan_to_income": "Higher LTI = less room for income shocks; NAB LTI cap 9×.",
    "num_defaults_5yr": "Historical defaults are the strongest negative signal in bureau scoring.",
    "worst_arrears_months": "More months in arrears = stronger recent negative evidence.",
    "existing_credit_card_limit": "More unused revolving limit inflates stressed serviceability commitments.",
    "monthly_expenses": "Higher declared expenses reduce serviceability surplus.",
    "num_credit_enquiries_6m": "Shopping intensity signals financial stress; > 6 enquiries is a red flag.",
    "bureau_risk_score": "Higher bureau risk score = more recently adverse activity.",
    "stressed_dsr": "DSR at stressed rate; higher = less buffer against RBA hikes (APS 220).",
    "stressed_repayment": "Repayment at assessed-rate; higher = more monthly burden under stress.",
    "has_bankruptcy": "Bankruptcy is a hard-fail predictor historically; monotone worse.",
    "num_dishonours_12m": "Dishonours indicate cash-flow failures; AFCA/Basiq flags these as leading indicators.",
    "days_in_overdraft_12m": "More days negative = tighter cash-flow margin; monotone worse.",
    "number_of_dependants": "More dependants = more baseline expenses (HEM scales with dependants).",
    "num_bnpl_accounts": "More BNPL accounts = more hidden commitments (CCR gap; 2024 ASIC concern).",
    "bnpl_active_count": "Active BNPL accounts duplicate num_bnpl_accounts signal; same sign.",
    "credit_card_burden": "Derived: card limits / income; same direction as limits.",
    "expense_to_income": "Mechanical ratio; more expense per dollar of income = less slack.",
    "lvr": "Key secured-lending risk variable; APRA flags LVR > 80% and LMI-required bands.",
    "lvr_x_dti": "Interaction of two negative drivers; sign is the product: negative.",
    "num_late_payments_24m": "CCR-era late payments directly predict future default.",
    "worst_late_payment_days": "Severity of worst late-payment episode; more days = worse.",
    "credit_utilization_pct": "Above 70% utilisation is a top-3 bureau-score negative in AU.",
    "num_hardship_flags": "AFCA/ASIC 2023 guidance: hardship history is materially negative.",
    "bnpl_total_limit": "Total BNPL exposure; larger = more hidden serviceability drag.",
    "bnpl_utilization_pct": "BNPL used ÷ limit; high use signals liquidity stress.",
    "bnpl_late_payments_12m": "BNPL late payments predict revolving-credit late payments.",
    "bnpl_monthly_commitment": "Monthly BNPL scheduled repayments; direct expense.",
    "essential_to_total_spend": "Higher essentials ratio = less discretionary buffer to cut.",
    "subscription_burden": "Sticky subscriptions reduce flex to cut expenses under stress.",
    "days_negative_balance_90d": "Recent days in negative balance = cashflow fragility.",
    "postcode_default_rate": "Geographic concentration risk; higher area default rate = worse tail.",
    "unemployment_rate": "Macro unemployment tail-risk correlates with individual default.",
    "income_verification_gap": "Mismatch between stated and verified income; higher = higher fraud risk.",
    "hem_gap": "Negative gap means HEM > income (hard-fail); magnitude monotonic in severity.",
    "gambling_transaction_flag": "AFCA 2023: gambling spend is a responsible-lending red flag.",
    "enquiry_intensity": "Enquiries per open account; high velocity = shopping-for-credit stress.",
    "cash_advance_count_12m": "Cash advances indicate short-term liquidity stress; high rate-cost.",
    "help_repayment_monthly": "HELP/HECS repayment reduces post-tax serviceability income.",
    "hecs_debt_balance": "HECS balance proxies future HELP repayment; higher = more drag.",
    "gambling_spend_ratio": "Gambling share of spend is a direct negative; mirrors AFCA guidance.",
    "monthly_rent": "Current rent is effectively baseline housing commitment; larger = less surplus.",
    "lmi_premium": "LMI charged only above 80% LVR; higher = higher-LVR loan = riskier.",
    "effective_loan_amount": "Loan + LMI (what actually appears on the mortgage); same direction as loan_amount.",
    "overdraft_frequency_90d": "Frequent overdraft = recurring cash-flow fragility.",
    "stress_index": "Aggregated stress score; direction matches its component drivers.",
}


def build_xgboost_monotone_spec(feature_cols: Iterable[str]) -> tuple:
    """Return the monotone_constraints tuple XGBoost expects, in the order of feature_cols.

    XGBoost accepts `monotone_constraints` as a tuple/list of ints where each
    entry is -1, 0, or +1 matching the column order of the training DataFrame.
    Any feature not in `MONOTONE_CONSTRAINTS` defaults to 0 (unconstrained).

    One-hot-encoded columns (e.g. `purpose_home`) start with a known base
    feature name followed by an underscore; they are left unconstrained since
    categoricals rarely have a principled monotone direction.
    """
    return tuple(MONOTONE_CONSTRAINTS.get(col, UNCONSTRAINED) for col in feature_cols)


def constrained_feature_names() -> list:
    """Alphabetical list of features carrying a non-zero constraint, for audit dumps."""
    return sorted(MONOTONE_CONSTRAINTS.keys())


def assert_rationale_coverage() -> None:
    """Runtime-assertable sanity: every constrained feature must have a RATIONALE entry.

    Called from the module's own test suite; also exposed so trainer.py can
    fail-fast at startup if the registry and rationale drift apart.
    """
    missing = set(MONOTONE_CONSTRAINTS) - set(RATIONALE)
    if missing:
        raise AssertionError(
            f"Monotone constraints missing RATIONALE entries: {sorted(missing)}"
        )
    orphaned = set(RATIONALE) - set(MONOTONE_CONSTRAINTS)
    if orphaned:
        raise AssertionError(
            f"RATIONALE entries with no corresponding constraint: {sorted(orphaned)}"
        )
