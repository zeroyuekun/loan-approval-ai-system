#!/usr/bin/env python3
"""Generate synthetic loan application data for model training.

Creates realistic loan records using Australian lending standards (APRA 2026,
Big 4 bank criteria, HEM benchmarks, LVR thresholds, income shading).

Usage:
    python tools/generate_synthetic_data.py
    python tools/generate_synthetic_data.py --num-records 50000
    python tools/generate_synthetic_data.py --output-path data/loans.csv --seed 123
"""

import argparse
import os
import sys

# Add backend to path so we can import the Django service
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import numpy as np
import pandas as pd


def generate_synthetic_data(num_records: int = 10000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic loan application records using Australian lending standards.

    Uses the same DataGenerator service as the Django backend to ensure
    consistency between standalone generation and API-based generation.

    Args:
        num_records: Number of records to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with loan application features and approval target.
    """
    print(f"Generating {num_records} records with random seed {seed}...")

    try:
        from apps.ml_engine.services.data_generator import DataGenerator
        generator = DataGenerator()
        return generator.generate(num_records=num_records, random_seed=seed)
    except ImportError:
        print("Could not import Django DataGenerator, using standalone implementation...")
        return _generate_standalone(num_records, seed)


def _generate_standalone(num_records: int, seed: int) -> pd.DataFrame:
    """Standalone generation matching the Django DataGenerator logic."""
    np.random.seed(seed)
    n = num_records

    # Australian income distribution (ABS median ~$65k)
    annual_income = np.random.lognormal(mean=np.log(70000), sigma=0.55, size=n).round(2)
    annual_income = np.clip(annual_income, 25000, 500000)

    # Equifax Australia credit score (0-1200, national average ~846)
    credit_score = np.clip(np.random.normal(loc=846, scale=150, size=n).astype(int), 0, 1200)

    # Loan amounts
    loan_amount = np.random.lognormal(mean=np.log(350000), sigma=0.7, size=n).round(2)
    loan_amount = np.clip(loan_amount, 5000, 3000000)

    loan_term_months = np.random.choice(
        [60, 120, 180, 240, 300, 360], size=n,
        p=[0.05, 0.10, 0.15, 0.20, 0.25, 0.25]
    )

    debt_to_income = np.clip(np.random.beta(a=2.5, b=4, size=n) * 10, 0.1, 12.0).round(2)
    employment_length = np.clip(np.random.exponential(scale=6, size=n).astype(int), 0, 40)

    purposes = ['home', 'auto', 'education', 'personal', 'business']
    purpose = np.random.choice(purposes, size=n, p=[0.35, 0.20, 0.15, 0.20, 0.10])

    ownerships = ['own', 'rent', 'mortgage']
    home_ownership = np.random.choice(ownerships, size=n, p=[0.20, 0.35, 0.45])

    has_cosigner = np.random.choice([0, 1], size=n, p=[0.92, 0.08])

    emp_types = ['payg_permanent', 'payg_casual', 'self_employed', 'contract']
    employment_type = np.random.choice(emp_types, size=n, p=[0.55, 0.15, 0.20, 0.10])

    app_types = ['single', 'couple']
    applicant_type = np.random.choice(app_types, size=n, p=[0.45, 0.55])

    number_of_dependants = np.random.choice([0, 1, 2, 3, 4], size=n, p=[0.35, 0.25, 0.25, 0.10, 0.05])

    is_home = purpose == 'home'
    property_value = np.zeros(n)
    lvr_targets = np.clip(np.random.normal(0.82, 0.08, size=n), 0.60, 0.98)
    property_value[is_home] = (loan_amount[is_home] / lvr_targets[is_home]).round(2)
    property_value = np.clip(property_value, 0, 5000000)

    deposit_amount = np.zeros(n)
    deposit_amount[is_home] = (property_value[is_home] - loan_amount[is_home]).round(2)
    deposit_amount = np.clip(deposit_amount, 0, 2000000)

    monthly_expenses = np.clip(
        np.random.lognormal(mean=np.log(2500), sigma=0.4, size=n).round(2), 800, 10000
    )

    existing_credit_card_limit = np.where(
        np.random.random(n) < 0.70,
        np.clip(np.random.lognormal(mean=np.log(8000), sigma=0.6, size=n), 0, 50000).round(2),
        0
    )

    df = pd.DataFrame({
        'annual_income': annual_income,
        'credit_score': credit_score,
        'loan_amount': loan_amount,
        'loan_term_months': loan_term_months,
        'debt_to_income': debt_to_income,
        'employment_length': employment_length,
        'purpose': purpose,
        'home_ownership': home_ownership,
        'has_cosigner': has_cosigner,
        'property_value': property_value,
        'deposit_amount': deposit_amount,
        'monthly_expenses': monthly_expenses,
        'existing_credit_card_limit': existing_credit_card_limit,
        'number_of_dependants': number_of_dependants,
        'employment_type': employment_type,
        'applicant_type': applicant_type,
    })

    # Simplified approval logic (see DataGenerator._compute_approval for full version)
    approved = np.ones(n, dtype=int)

    # Hard cutoffs
    approved[debt_to_income >= 6.0] = 0
    approved[credit_score < 500] = 0

    # Serviceability (simplified)
    monthly_rate = 0.095 / 12  # 9.5% assessment rate
    monthly_repayment = (
        loan_amount * monthly_rate * (1 + monthly_rate) ** loan_term_months
        / ((1 + monthly_rate) ** loan_term_months - 1)
    )
    monthly_income = annual_income / 12
    surplus = monthly_income * 0.75 - monthly_expenses - monthly_repayment
    approved[surplus < 0] = 0

    # DSR check
    dsr = monthly_repayment / monthly_income
    approved[dsr > 0.35] = 0

    # Composite scoring
    credit_norm = np.clip((credit_score - 500) / 700, 0, 1)
    dti_score = np.clip(1 - (debt_to_income / 6.0), 0, 1)
    composite = 0.30 * credit_norm + 0.30 * dti_score + 0.20 * np.clip(surplus / 3000, 0, 1) + 0.20 * np.clip(annual_income / 150000, 0, 1)
    noise = np.random.normal(0, 0.04, size=n)
    approved[composite + noise < 0.35] = 0

    df['approved'] = approved
    return df


def validate_data(df: pd.DataFrame) -> None:
    """Validate the generated DataFrame for correctness."""
    null_count = df.isnull().sum().sum()
    if null_count > 0:
        raise ValueError(f"Found {null_count} null values in generated data.")

    assert df["annual_income"].between(25000, 500000).all(), "Income out of range"
    assert df["credit_score"].between(0, 1200).all(), "Credit score out of range"
    assert df["loan_amount"].between(5000, 3000000).all(), "Loan amount out of range"
    assert df["debt_to_income"].between(0, 12.1).all(), "DTI out of range"
    assert df["employment_length"].between(0, 40).all(), "Employment length out of range"
    assert set(df["purpose"].unique()).issubset(
        {"home", "auto", "education", "personal", "business"}
    ), "Invalid purpose values"
    assert set(df["approved"].unique()).issubset({0, 1}), "Invalid approved values"

    approval_rate = df["approved"].mean()
    print(f"Approval rate: {approval_rate:.1%}")
    if not 0.25 <= approval_rate <= 0.45:
        print(
            f"WARNING: Approval rate {approval_rate:.1%} is outside expected range (25-45%). "
            "Consider adjusting parameters."
        )


def main():
    """Parse arguments and generate synthetic data."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic loan application data for model training."
    )
    parser.add_argument(
        "--num-records", type=int, default=10000,
        help="Number of records to generate (default: 10000)",
    )
    parser.add_argument(
        "--output-path", type=str, default=".tmp/synthetic_loans.csv",
        help="Output CSV file path (default: .tmp/synthetic_loans.csv)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()

    if args.num_records > 1000000:
        print(f"WARNING: Generating {args.num_records:,} records. This may use significant disk space.")

    df = generate_synthetic_data(num_records=args.num_records, seed=args.seed)
    validate_data(df)

    output_dir = os.path.dirname(args.output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    df.to_csv(args.output_path, index=False)
    print(f"Saved {len(df)} records to {args.output_path}")
    print(f"File size: {os.path.getsize(args.output_path) / 1024:.1f} KB")
    print(f"Columns: {list(df.columns)}")
    print(f"\nColumn summary:\n{df.describe().round(2)}")


if __name__ == "__main__":
    main()
