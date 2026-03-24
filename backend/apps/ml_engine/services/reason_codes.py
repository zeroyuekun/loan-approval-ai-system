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
    'annual_income': ('R01', 'Annual income insufficient for requested loan amount'),
    'loan_to_income': ('R02', 'Loan-to-income ratio exceeds lending criteria'),
    'debt_to_income': ('R03', 'Existing debt obligations too high relative to income'),
    'serviceability_ratio': ('R04', 'Insufficient income buffer after monthly commitments'),
    'expense_to_income': ('R05', 'Monthly expenses too high relative to income'),

    # Credit history
    'credit_score': ('R06', 'Credit score below minimum lending threshold'),
    'income_credit_interaction': ('R07', 'Combined income and credit profile does not meet criteria'),
    'has_bankruptcy': ('R08', 'Bankruptcy record on file'),

    # Employment
    'employment_length': ('R09', 'Insufficient employment tenure'),
    'employment_stability': ('R10', 'Employment stability does not meet minimum requirements'),
    'employment_type_payg_permanent': ('R11', 'Employment type assessed as higher risk'),
    'employment_type_self_employed': ('R11', 'Employment type assessed as higher risk'),
    'employment_type_payg_casual': ('R11', 'Employment type assessed as higher risk'),
    'employment_type_contract': ('R11', 'Employment type assessed as higher risk'),

    # Loan structure
    'loan_amount': ('R12', 'Requested loan amount exceeds assessed borrowing capacity'),
    'loan_term_months': ('R13', 'Requested loan term outside acceptable range'),
    'lvr': ('R14', 'Loan-to-value ratio exceeds maximum for this product'),
    'lvr_x_dti': ('R15', 'Combined leverage and debt ratio exceeds risk tolerance'),

    # Other
    'credit_card_burden': ('R16', 'Existing credit card commitments too high'),
    'existing_credit_card_limit': ('R17', 'Total available credit limits exceed policy'),
    'has_cosigner': ('R18', 'Application assessed without co-signer support'),
    'number_of_dependants': ('R19', 'Number of dependants affects assessed living expenses'),
    'has_hecs': ('R20', 'HECS-HELP debt included in serviceability assessment'),
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
    if prediction != 'denied' or not shap_values:
        return []

    # Sort by most negative SHAP value (biggest contributors to denial)
    negative_features = [
        (name, val) for name, val in shap_values.items()
        if val < 0
    ]
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

        reasons.append({
            'code': code,
            'reason': explanation,
            'feature': feature_name,
            'contribution': round(float(shap_val), 4),
        })

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
                targets.append({
                    'feature': cf.get('feature', ''),
                    'current_value': cf.get('current', ''),
                    'target_value': cf.get('target', ''),
                    'description': cf.get('description', ''),
                })

    # Estimate timeline based on what needs to change
    months = 3  # default
    for reason in adverse_reasons:
        code = reason.get('code', '')
        if code == 'R06':  # credit score
            months = max(months, 6)
        elif code == 'R09':  # employment tenure
            months = max(months, 12)
        elif code == 'R08':  # bankruptcy
            months = max(months, 24)
        elif code in ('R03', 'R05'):  # debt/expenses
            months = max(months, 6)

    return {
        'improvement_targets': targets,
        'estimated_review_months': months,
        'message': (
            f'Based on your application, we estimate you could be eligible for '
            f'reassessment in approximately {months} months if the areas identified '
            f'above are addressed.'
        ),
    }
