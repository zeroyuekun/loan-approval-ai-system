"""Adverse Action Reason Codes — denial explanations aligned with international best practice.

Maps SHAP-based feature contributions to standardised, human-readable
reason codes. Aligned with:
- CFPB Circular 2022-03 (US): requires specific, accurate reasons for adverse action
- ASIC RG 209 (Australia): requires transparent assessment of "not unsuitable" criteria

Note: ASIC RG 209 does not mandate SHAP-based reason codes or a specific
number of reasons. Australian law requires lenders to disclose credit report
factors and demonstrate the loan was assessed as "not unsuitable" under the
NCCP Act. This implementation exceeds the minimum Australian requirements
by providing individualised explanations — a voluntary best practice.

Each denial includes the top 4 specific reasons, drawn from the features
that most negatively contributed to the decision.
"""

# Maps feature names to (reason_code, human-readable explanation)
REASON_CODE_MAP = {
    # Income & affordability
    "annual_income": ("R01", "Annual income insufficient for requested loan amount"),
    "loan_to_income": ("R02", "Loan-to-income ratio exceeds lending criteria"),
    "debt_to_income": ("R03", "Existing debt obligations too high relative to income"),
    "serviceability_ratio": ("R04", "Insufficient income buffer after monthly commitments"),
    "expense_to_income": ("R05", "Monthly expenses too high relative to income"),
    # Credit history
    "credit_score": ("R06", "Credit score below minimum lending threshold"),
    "income_credit_interaction": ("R07", "Combined income and credit profile does not meet criteria"),
    "has_bankruptcy": ("R08", "Bankruptcy record on file"),
    # Employment
    "employment_length": ("R09", "Insufficient employment tenure"),
    "employment_stability": ("R10", "Employment stability does not meet minimum requirements"),
    "employment_type_payg_permanent": ("R11", "Employment type assessed as higher risk"),
    "employment_type_self_employed": ("R11", "Employment type assessed as higher risk"),
    "employment_type_payg_casual": ("R11", "Employment type assessed as higher risk"),
    "employment_type_contract": ("R11", "Employment type assessed as higher risk"),
    # Loan structure
    "loan_amount": ("R12", "Requested loan amount exceeds assessed borrowing capacity"),
    "loan_term_months": ("R13", "Requested loan term outside acceptable range"),
    "lvr": ("R14", "Loan-to-value ratio exceeds maximum for this product"),
    "lvr_x_dti": ("R15", "Combined leverage and debt ratio exceeds risk tolerance"),
    # Other obligations
    "credit_card_burden": ("R16", "Existing credit card commitments too high"),
    "existing_credit_card_limit": ("R17", "Total available credit limits exceed policy"),
    "has_cosigner": ("R18", "Application assessed without co-signer support"),
    "number_of_dependants": ("R19", "Number of dependants affects assessed living expenses"),
    "has_hecs": ("R20", "HECS-HELP debt included in serviceability assessment"),
    # Bureau / credit report (Equifax/Illion)
    "num_credit_enquiries_6m": ("R21", "Too many credit enquiries in recent months"),
    "worst_arrears_months": ("R22", "History of overdue payments on credit accounts"),
    "num_defaults_5yr": ("R23", "Default records found in credit history"),
    "credit_history_months": ("R24", "Insufficient length of credit history"),
    "total_open_accounts": ("R25", "Number of open credit accounts exceeds policy"),
    "num_bnpl_accounts": ("R26", "Number of active buy-now-pay-later accounts noted"),
    # CCR (Comprehensive Credit Reporting)
    "num_late_payments_24m": ("R27", "Late payments recorded in the last 24 months"),
    "worst_late_payment_days": ("R28", "Severity of late payments exceeds threshold"),
    "credit_utilization_pct": ("R29", "Credit utilisation ratio too high"),
    "num_hardship_flags": ("R30", "Financial hardship indicators on credit file"),
    "months_since_last_default": ("R31", "Insufficient time since last default"),
    "total_credit_limit": ("R32", "Total credit exposure exceeds lending criteria"),
    "num_credit_providers": ("R33", "Number of credit providers exceeds policy"),
    # BNPL-specific
    "bnpl_total_limit": ("R34", "Total buy-now-pay-later exposure too high"),
    "bnpl_utilization_pct": ("R35", "Buy-now-pay-later utilisation too high"),
    "bnpl_late_payments_12m": ("R36", "Late payments on buy-now-pay-later accounts"),
    "bnpl_monthly_commitment": ("R37", "Buy-now-pay-later commitments reduce borrowing capacity"),
    "bnpl_to_income_ratio": ("R37", "Buy-now-pay-later commitments reduce borrowing capacity"),
    # Behavioural / internal data
    "num_dishonours_12m": ("R38", "Dishonoured transactions in the last 12 months"),
    "days_in_overdraft_12m": ("R39", "Excessive time in overdraft in the last 12 months"),
    "savings_balance": ("R40", "Savings balance below minimum for loan size"),
    "avg_monthly_savings_rate": ("R41", "Monthly savings pattern insufficient"),
    "salary_credit_regularity": ("R42", "Irregular salary credit pattern detected"),
    # CDR / Open Banking transaction features
    "balance_before_payday": ("R43", "Low account balance before payday"),
    "min_balance_30d": ("R44", "Minimum account balance too low in recent period"),
    "days_negative_balance_90d": ("R45", "Account in negative balance too frequently"),
    "subscription_burden": ("R46", "Recurring subscription commitments too high"),
    "essential_to_total_spend": ("R47", "High proportion of spending on essentials"),
    "discretionary_spend_ratio": ("R48", "Spending pattern indicates limited financial buffer"),
    "gambling_transaction_flag": ("R49", "Gambling transactions detected in account history"),
    "gambling_spend_ratio": ("R49", "Gambling transactions detected in account history"),
    "overdraft_frequency_90d": ("R50", "Frequent overdraft usage in recent months"),
    "rent_payment_regularity": ("R51", "Irregular rent payment pattern"),
    "utility_payment_regularity": ("R52", "Irregular utility payment pattern"),
    "income_source_count": ("R53", "Limited income sources identified"),
    # APRA stress test / serviceability
    "stressed_repayment": ("R54", "Loan repayments unaffordable under stress-test interest rate"),
    "stressed_dsr": ("R55", "Debt-service ratio exceeds limit under stress scenario"),
    "hem_surplus": ("R56", "Insufficient surplus after household expenditure measure applied"),
    "uncommitted_monthly_income": ("R57", "Uncommitted monthly income below minimum threshold"),
    # Application / document integrity
    "income_verification_gap": ("R58", "Discrepancy between stated and verified income"),
    "document_consistency_score": ("R59", "Application documents show inconsistencies"),
    "income_verification_score": ("R60", "Income verification confidence below threshold"),
    # Loan structure (additional)
    "deposit_ratio": ("R61", "Deposit contribution below minimum for loan type"),
    "monthly_repayment_ratio": ("R62", "Monthly repayments too high relative to income"),
    "net_monthly_surplus": ("R63", "Net monthly surplus insufficient after all commitments"),
    # Geographic risk
    "postcode_default_rate": ("R64", "Postcode-level default rate above threshold"),
    # Derived / interaction features
    "bureau_risk_score": ("R65", "Bureau-derived risk score exceeds threshold"),
    "enquiry_intensity": ("R66", "Intensity of recent credit enquiries too high"),
    "stress_index": ("R67", "Overall financial stress indicators elevated"),
    "enquiry_to_account_ratio": ("R68", "Ratio of enquiries to accounts suggests credit-seeking behaviour"),
    # Macroeconomic (contextual — used only as supporting factors)
    "hecs_debt_balance": ("R20", "HECS-HELP debt included in serviceability assessment"),
    "cash_advance_count_12m": ("R69", "Cash advance usage in the last 12 months"),
    "monthly_rent": ("R70", "Rental commitments reduce assessed borrowing capacity"),
    # Policy gates (deterministic, not ML features)
    "age_at_loan_maturity": (
        "R71",
        "Applicant age at loan maturity exceeds 67-year policy limit",
    ),
}


def generate_adverse_action_reasons(shap_values: dict, prediction: str, max_reasons: int = 4) -> list[dict]:
    """Generate standardised adverse action reasons from SHAP values.

    For denied applications, returns the top N features that most negatively
    contributed to the decision, mapped to regulatory reason codes.

    Args:
        shap_values: dict of {feature_name: shap_value} from prediction
        prediction: 'approved' or 'denied'
        max_reasons: maximum number of reasons to return (ECOA standard: 4)

    Returns:
        List of dicts with code, reason, feature, and contribution.
    """
    if prediction != "denied" or not shap_values:
        return []

    # Sort by most negative SHAP value (biggest contributors to denial)
    negative_features = [(name, val) for name, val in shap_values.items() if val < 0]
    negative_features.sort(key=lambda x: x[1])

    reasons = []
    seen_codes = set()

    for feature_name, shap_val in negative_features:
        if len(reasons) >= max_reasons:
            break

        code_info = REASON_CODE_MAP.get(feature_name)
        if not code_info:
            continue

        code, explanation = code_info

        # Avoid duplicate reason codes (e.g., multiple employment_type_ columns)
        if code in seen_codes:
            continue
        seen_codes.add(code)

        reasons.append(
            {
                "code": code,
                "reason": explanation,
                "feature": feature_name,
                "contribution": round(float(shap_val), 4),
            }
        )

    return reasons


def generate_reapplication_guidance(counterfactuals: list, adverse_reasons: list) -> dict:
    """Generate actionable guidance for declined applicants.

    Combines counterfactual explanations with adverse action reasons to
    provide specific, achievable improvement targets.

    Returns dict with improvement_targets and estimated_timeline.
    """
    targets = []

    if counterfactuals:
        for cf in counterfactuals[:3]:
            if isinstance(cf, dict):
                targets.append(
                    {
                        "feature": cf.get("feature", ""),
                        "current_value": cf.get("current", ""),
                        "target_value": cf.get("target", ""),
                        "description": cf.get("description", ""),
                    }
                )

    # Estimate timeline based on what needs to change
    months = 3  # default
    for reason in adverse_reasons:
        code = reason.get("code", "")
        if code == "R06":  # credit score
            months = max(months, 6)
        elif code == "R09":  # employment tenure
            months = max(months, 12)
        elif code == "R08":  # bankruptcy
            months = max(months, 24)
        elif code in ("R03", "R05"):  # debt/expenses
            months = max(months, 6)

    return {
        "improvement_targets": targets,
        "estimated_review_months": months,
        "message": (
            f"Based on your application, we estimate you could be eligible for "
            f"reassessment in approximately {months} months if the areas identified "
            f"above are addressed."
        ),
    }
