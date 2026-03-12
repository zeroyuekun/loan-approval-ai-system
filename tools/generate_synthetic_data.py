#!/usr/bin/env python3
"""Generate synthetic loan application data for model training.

Creates realistic loan records with configurable count and distributions,
using a weighted scoring formula to determine approval decisions.

Usage:
    python tools/generate_synthetic_data.py
    python tools/generate_synthetic_data.py --num-records 50000
    python tools/generate_synthetic_data.py --output-path data/loans.csv --seed 123
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd


def generate_synthetic_data(num_records: int = 10000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic loan application records.

    Args:
        num_records: Number of records to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with loan application features and approval target.
    """
    np.random.seed(seed)
    print(f"Generating {num_records} records with random seed {seed}...")

    # --- Feature generation ---

    # Income: log-normal, median ~55k, range 30k-200k
    income = np.random.lognormal(mean=10.9, sigma=0.5, size=num_records)
    income = np.clip(income, 30000, 200000).round(2)

    # Credit score: normal, mean 680, std 80, range 300-850
    credit_score = np.random.normal(loc=680, scale=80, size=num_records)
    credit_score = np.clip(credit_score, 300, 850).astype(int)

    # Loan amount: log-normal, median ~25k, range 1k-500k
    loan_amount = np.random.lognormal(mean=10.1, sigma=0.8, size=num_records)
    loan_amount = np.clip(loan_amount, 1000, 500000).round(2)

    # Debt-to-income: beta distribution, skewed toward 0.2-0.4
    debt_to_income = np.random.beta(a=2, b=5, size=num_records)
    debt_to_income = np.clip(debt_to_income, 0.0, 1.0).round(4)

    # Employment length: exponential, most < 10 years, range 0-40
    employment_length = np.random.exponential(scale=5, size=num_records)
    employment_length = np.clip(employment_length, 0, 40).astype(int)

    # Purpose: weighted categorical
    purpose_choices = ["home", "auto", "education", "personal", "business"]
    purpose_weights = [0.30, 0.25, 0.15, 0.20, 0.10]
    purpose = np.random.choice(purpose_choices, size=num_records, p=purpose_weights)

    # Home ownership: weighted categorical
    ownership_choices = ["own", "rent", "mortgage"]
    ownership_weights = [0.20, 0.35, 0.45]
    home_ownership = np.random.choice(
        ownership_choices, size=num_records, p=ownership_weights
    )

    # Has cosigner: 15% True
    has_cosigner = np.random.random(size=num_records) < 0.15

    # Annual income is an alias for income
    annual_income = income.copy()

    # --- Approval scoring ---

    # Normalize credit score to 0-1
    credit_score_norm = (credit_score - 300) / 550.0

    # Income-to-loan ratio, capped at 1.0
    income_to_loan = np.minimum(income / loan_amount, 1.0)

    # Employment factor: min(years / 10, 1.0)
    employment_factor = np.minimum(employment_length / 10.0, 1.0)

    # Cosigner bonus
    cosigner_bonus = has_cosigner.astype(float)

    # Purpose factor
    purpose_factor_map = {
        "home": 0.8,
        "auto": 0.7,
        "education": 0.6,
        "business": 0.5,
        "personal": 0.4,
    }
    purpose_factor = np.array([purpose_factor_map[p] for p in purpose])

    # Weighted score
    score = (
        0.35 * credit_score_norm
        + 0.25 * (1 - debt_to_income)
        + 0.20 * income_to_loan
        + 0.10 * employment_factor
        + 0.05 * cosigner_bonus
        + 0.05 * purpose_factor
    )

    # Decision with noise
    threshold = 0.5
    noise = np.random.uniform(-0.05, 0.05, size=num_records)
    approved = (score > (threshold + noise)).astype(int)

    # --- Build DataFrame ---

    df = pd.DataFrame(
        {
            "income": income,
            "credit_score": credit_score,
            "loan_amount": loan_amount,
            "debt_to_income": debt_to_income,
            "employment_length": employment_length,
            "purpose": purpose,
            "home_ownership": home_ownership,
            "annual_income": annual_income,
            "has_cosigner": has_cosigner.astype(int),
            "approved": approved,
        }
    )

    return df


def validate_data(df: pd.DataFrame) -> None:
    """Validate the generated DataFrame for correctness.

    Args:
        df: Generated loan data DataFrame.

    Raises:
        ValueError: If validation checks fail.
    """
    # Check for nulls
    null_count = df.isnull().sum().sum()
    if null_count > 0:
        raise ValueError(f"Found {null_count} null values in generated data.")

    # Check value ranges
    assert df["income"].between(30000, 200000).all(), "Income out of range"
    assert df["credit_score"].between(300, 850).all(), "Credit score out of range"
    assert df["loan_amount"].between(1000, 500000).all(), "Loan amount out of range"
    assert df["debt_to_income"].between(0, 1).all(), "DTI out of range"
    assert df["employment_length"].between(0, 40).all(), "Employment length out of range"
    assert set(df["purpose"].unique()).issubset(
        {"home", "auto", "education", "personal", "business"}
    ), "Invalid purpose values"
    assert set(df["home_ownership"].unique()).issubset(
        {"own", "rent", "mortgage"}
    ), "Invalid home_ownership values"
    assert set(df["approved"].unique()).issubset({0, 1}), "Invalid approved values"

    # Check approval rate
    approval_rate = df["approved"].mean()
    print(f"Approval rate: {approval_rate:.1%}")
    if not 0.40 <= approval_rate <= 0.80:
        print(
            f"WARNING: Approval rate {approval_rate:.1%} is outside expected range (55-65%). "
            "Consider adjusting the scoring threshold."
        )


def main():
    """Parse arguments and generate synthetic data."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic loan application data for model training."
    )
    parser.add_argument(
        "--num-records",
        type=int,
        default=10000,
        help="Number of records to generate (default: 10000)",
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default=".tmp/synthetic_loans.csv",
        help="Output CSV file path (default: .tmp/synthetic_loans.csv)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()

    if args.num_records > 1000000:
        print(
            f"WARNING: Generating {args.num_records:,} records. "
            "This may use significant disk space."
        )

    # Generate data
    df = generate_synthetic_data(num_records=args.num_records, seed=args.seed)

    # Validate
    validate_data(df)

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Save
    df.to_csv(args.output_path, index=False)
    print(f"Saved {len(df)} records to {args.output_path}")
    print(f"File size: {os.path.getsize(args.output_path) / 1024:.1f} KB")
    print(f"\nColumn summary:\n{df.describe().round(2)}")


if __name__ == "__main__":
    main()
