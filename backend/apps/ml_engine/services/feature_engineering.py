"""Shared feature engineering — single source of truth.

Both ModelTrainer and ModelPredictor import from here to eliminate
training/serving skew risk from duplicated feature computation.
"""

import numpy as np
import pandas as pd


# The 16 derived feature names that compute_derived_features adds
DERIVED_FEATURE_NAMES = [
    'lvr', 'loan_to_income', 'credit_card_burden', 'expense_to_income',
    'lvr_x_dti', 'income_credit_interaction', 'serviceability_ratio',
    'employment_stability', 'deposit_ratio', 'monthly_repayment_ratio',
    'net_monthly_surplus', 'income_per_dependant', 'credit_score_x_tenure',
    'enquiry_intensity', 'bureau_risk_score', 'rate_stress_buffer',
    # APRA stress test & Australian regulatory derived features
    'stressed_repayment', 'stressed_dsr', 'hem_surplus',
    'uncommitted_monthly_income',
    'savings_to_loan_ratio', 'debt_service_coverage', 'bnpl_to_income_ratio',
    'enquiry_to_account_ratio', 'stress_index',
    'log_annual_income', 'log_loan_amount',
]

# Default imputation values for optional/nullable fields.
# These are used when the model bundle doesn't have stored imputation values
# (e.g., for backward compatibility with older bundles).
DEFAULT_IMPUTATION_VALUES = {
    'monthly_expenses': 2500.0,
    'existing_credit_card_limit': 0.0,
    'property_value': 0.0,
    'deposit_amount': 0.0,
    'num_credit_enquiries_6m': 1.0,
    'worst_arrears_months': 0.0,
    'num_defaults_5yr': 0.0,
    'credit_history_months': 120.0,
    'total_open_accounts': 3.0,
    'num_bnpl_accounts': 0.0,
    'is_existing_customer': 0.0,
    'savings_balance': 10000.0,
    'salary_credit_regularity': 0.8,
    'num_dishonours_12m': 0.0,
    'avg_monthly_savings_rate': 0.10,
    'days_in_overdraft_12m': 0.0,
    'rba_cash_rate': 4.10,
    'unemployment_rate': 3.8,
    'property_growth_12m': 5.0,
    'consumer_confidence': 95.0,
    'income_verification_gap': 1.0,
    'document_consistency_score': 0.9,
    # Open Banking features
    'discretionary_spend_ratio': 0.35,
    'gambling_transaction_flag': 0,
    'bnpl_active_count': 0,
    'overdraft_frequency_90d': 0,
    'income_verification_score': 0.85,
    # CCR features
    'num_late_payments_24m': 0,
    'worst_late_payment_days': 0,
    'total_credit_limit': 20000.0,
    'credit_utilization_pct': 0.30,
    'num_hardship_flags': 0,
    'months_since_last_default': 999,
    'num_credit_providers': 2,
    # BNPL-specific
    'bnpl_total_limit': 0.0,
    'bnpl_utilization_pct': 0.0,
    'bnpl_late_payments_12m': 0,
    'bnpl_monthly_commitment': 0.0,
    # CDR/Open Banking transaction features
    'income_source_count': 1,
    'rent_payment_regularity': 0.85,
    'utility_payment_regularity': 0.90,
    'essential_to_total_spend': 0.50,
    'subscription_burden': 0.05,
    'balance_before_payday': 2000.0,
    'min_balance_30d': 500.0,
    'days_negative_balance_90d': 0,
    # Geographic risk
    'postcode_default_rate': 0.015,
    # Behavioral features
    'application_channel': 'digital',
    'optimism_bias_flag': 0,
    'financial_literacy_score': 0.5,
    'prepayment_buffer_months': 6.0,
    'negative_equity_flag': 0,
    'loan_trigger_event': 'other',
}


def impute_missing_values(df, imputation_values=None):
    """Apply imputation to a DataFrame using the provided values dict.

    Args:
        df: DataFrame with raw features (may contain NaN).
        imputation_values: dict of {column_name: default_value}.
            If None, uses DEFAULT_IMPUTATION_VALUES.

    Returns:
        DataFrame with NaN values filled.
    """
    df = df.copy()
    values = imputation_values if imputation_values is not None else DEFAULT_IMPUTATION_VALUES

    # Priority columns: always fill these first with their specific values
    priority_cols = ['monthly_expenses', 'existing_credit_card_limit',
                     'property_value', 'deposit_amount']
    for col in priority_cols:
        if col in values and col in df.columns:
            df[col] = df[col].fillna(values[col])

    # Remaining columns: fillna if present, create with default if missing
    for col, default in values.items():
        if col in priority_cols:
            continue
        if col in df.columns:
            df[col] = df[col].fillna(default)
        else:
            df[col] = default

    return df


def compute_derived_features(df):
    """Compute all derived features from raw (already-imputed) features.

    This is a pure, stateless function. Input df must have NaN already
    handled for the columns used in computations.

    Returns df with 16 derived columns added.
    """
    df = df.copy()

    # Guard against zero/NaN income up front
    annual_income = df['annual_income'].replace(0, np.nan)
    monthly_income = annual_income / 12.0

    # --- Basic ratios ---

    # LVR: Loan-to-Value Ratio
    df['lvr'] = np.where(
        df['property_value'] > 0,
        df['loan_amount'] / df['property_value'],
        0.0,
    )

    # Loan to income ratio
    df['loan_to_income'] = np.where(
        annual_income.notna() & (annual_income > 0),
        df['loan_amount'] / annual_income,
        0.0,
    )

    # Credit card burden: 3% of limit as proportion of monthly income
    df['credit_card_burden'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        df['existing_credit_card_limit'] * 0.03 / monthly_income,
        0.0,
    )

    # Expense to income ratio
    df['expense_to_income'] = np.where(
        annual_income.notna() & (annual_income > 0),
        df['monthly_expenses'] * 12 / annual_income,
        0.0,
    )

    # --- Feature interactions ---

    # Leverage interaction: LVR x DTI — compounding risk
    df['lvr_x_dti'] = df['lvr'] * df['debt_to_income']

    # Capacity interaction: income-normalised credit score
    df['income_credit_interaction'] = (
        np.log1p(df['annual_income']) * df['credit_score'] / 1200
    )

    # Serviceability buffer
    monthly_commitments = (
        df['existing_credit_card_limit'] * 0.03
        + df['monthly_expenses']
    )
    df['serviceability_ratio'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        np.clip(1.0 - monthly_commitments / monthly_income, -1.0, 1.0),
        0.0,
    )

    # Employment stability score: type quality x tenure
    emp_type_weight = df.get('employment_type', pd.Series(dtype=str)).map({
        'payg_permanent': 1.0,
        'contract': 0.7,
        'self_employed': 0.6,
        'payg_casual': 0.4,
    }).fillna(0.5)
    df['employment_stability'] = emp_type_weight * np.log1p(df['employment_length'])

    # --- Additional features ---

    # Deposit quality ratio
    df['deposit_ratio'] = np.where(
        df['loan_amount'] > 0,
        df['deposit_amount'] / df['loan_amount'],
        0.0,
    )

    # Monthly repayment affordability (amortisation at 6.5% p.a. assessment rate)
    assessment_rate = 0.065 / 12  # monthly
    term = df['loan_term_months'].clip(lower=1)
    estimated_monthly = np.where(
        term > 0,
        df['loan_amount'] * assessment_rate * (1 + assessment_rate) ** term
        / ((1 + assessment_rate) ** term - 1),
        0.0,
    )
    df['monthly_repayment_ratio'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        estimated_monthly / monthly_income,
        0.0,
    )

    # Net monthly surplus after all commitments and estimated repayment
    df['net_monthly_surplus'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        np.clip(
            (monthly_income - df['monthly_expenses']
             - df['existing_credit_card_limit'] * 0.03 - estimated_monthly)
            / monthly_income,
            -2.0, 1.0,
        ),
        0.0,
    )

    # Income per dependant: disposable income capacity
    df['income_per_dependant'] = np.where(
        df['number_of_dependants'] > 0,
        np.log1p(df['annual_income'] / (df['number_of_dependants'] + 1)),
        np.log1p(df['annual_income']),
    )

    # Credit score x employment tenure
    df['credit_score_x_tenure'] = (
        (df['credit_score'] / 1200) * np.log1p(df['employment_length'])
    )

    # --- Bureau-derived features ---

    df['enquiry_intensity'] = (
        df['num_credit_enquiries_6m']
        / np.maximum(df['credit_history_months'] / 12, 1)
    )
    df['bureau_risk_score'] = (
        df['num_credit_enquiries_6m'] * 0.3
        + df['worst_arrears_months'] * 0.4
        + df['num_defaults_5yr'] * 0.2
        + df['num_bnpl_accounts'] * 0.1
    )

    # Macro-adjusted serviceability
    df['rate_stress_buffer'] = (
        df['rba_cash_rate'] / 100 * df['loan_amount'] / 12
        / np.maximum(df['annual_income'] / 12, 1)
    )

    # Ensure flag columns exist with defaults if missing from older datasets
    if 'has_hecs' not in df.columns:
        df['has_hecs'] = 0
    if 'has_bankruptcy' not in df.columns:
        df['has_bankruptcy'] = 0

    # --- APRA stress test & Australian regulatory derived features ---

    # Stressed repayment: monthly repayment at assessment rate + buffer
    stressed_rate = 0.095 / 12  # ~9.5% = base rate + 3% APRA buffer
    term_s = df['loan_term_months'].clip(lower=1)
    df['stressed_repayment'] = np.where(
        term_s > 0,
        df['loan_amount'] * stressed_rate * (1 + stressed_rate) ** term_s
        / ((1 + stressed_rate) ** term_s - 1),
        0.0,
    )

    # Stressed DSR: stressed repayment / monthly income
    df['stressed_dsr'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        df['stressed_repayment'] / monthly_income,
        0.0,
    )

    # HEM surplus: monthly income - monthly expenses - stressed repayment
    df['hem_surplus'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        monthly_income - df['monthly_expenses'] - df['stressed_repayment'],
        0.0,
    )

    # Uncommitted monthly income
    bnpl_commit = df['bnpl_monthly_commitment'] if 'bnpl_monthly_commitment' in df.columns else 0
    cc_commit = df['existing_credit_card_limit'] * 0.03
    df['uncommitted_monthly_income'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        monthly_income - df['monthly_expenses'] - cc_commit - bnpl_commit - df['stressed_repayment'],
        0.0,
    )

    # Savings to loan ratio
    savings = df['savings_balance'] if 'savings_balance' in df.columns else 0
    df['savings_to_loan_ratio'] = np.where(
        df['loan_amount'] > 0,
        savings / df['loan_amount'],
        0.0,
    )

    # Debt service coverage ratio
    total_debt_service = df['stressed_repayment'] + cc_commit + bnpl_commit
    df['debt_service_coverage'] = np.where(
        (total_debt_service > 0) & monthly_income.notna() & (monthly_income > 0),
        monthly_income / total_debt_service,
        np.where(total_debt_service > 0, 0.0, 10.0),  # 0 income => 0 coverage; no debt => 10
    )

    # BNPL to income ratio
    df['bnpl_to_income_ratio'] = np.where(
        monthly_income.notna() & (monthly_income > 0),
        bnpl_commit / monthly_income,
        0.0,
    )

    # Enquiry to account ratio
    enquiries = df['num_credit_enquiries_6m'] if 'num_credit_enquiries_6m' in df.columns else 0
    accounts = df['total_open_accounts'] if 'total_open_accounts' in df.columns else 1
    df['enquiry_to_account_ratio'] = np.where(
        accounts > 0,
        enquiries / np.maximum(accounts, 1),
        0.0,
    )

    # Stress index: composite financial stress signal (0-100)
    utilization = df['credit_utilization_pct'] if 'credit_utilization_pct' in df.columns else 0.3
    neg_days = df['days_negative_balance_90d'] if 'days_negative_balance_90d' in df.columns else 0
    overdraft = df['overdraft_frequency_90d'] if 'overdraft_frequency_90d' in df.columns else 0
    df['stress_index'] = np.clip(
        utilization * 30
        + neg_days * 1.5
        + overdraft * 3
        + df['stressed_dsr'] * 40,
        0, 100,
    )

    # Log transforms for skewed distributions
    df['log_annual_income'] = np.log1p(df['annual_income'])
    df['log_loan_amount'] = np.log1p(df['loan_amount'])

    return df
