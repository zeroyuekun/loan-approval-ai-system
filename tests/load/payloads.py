"""Synthetic loan payloads for load testing.

Values are chosen from realistic AU ranges (matching ml_engine data_generator
distributions at a coarse level). Distributions are uniform — variance is not
the point here; throughput is.
"""
import random


def loan_application_payload() -> dict:
    """Payload matching LoanApplicationCreateSerializer fields (backend/apps/loans/serializers.py)."""
    annual_income = random.randint(45000, 180000)
    loan_amount = random.choice([10000, 25000, 50000, 100000, 250000, 500000])
    return {
        "loan_amount": loan_amount,
        "loan_term_months": random.choice([12, 24, 36, 60, 84, 120, 240, 360]),
        "purpose": random.choice(["home", "auto", "education", "personal", "business"]),
        "annual_income": annual_income,
        "employment_type": random.choice(
            ["payg_permanent", "payg_casual", "self_employed", "contract"]
        ),
        "employment_length": random.randint(0, 25),
        "credit_score": random.randint(400, 850),
        "debt_to_income": round(random.uniform(0.05, 0.45), 2),
        "monthly_expenses": random.randint(1500, 6000),
        "existing_credit_card_limit": random.choice([0, 5000, 10000, 20000]),
        "number_of_dependants": random.choice([0, 0, 1, 2, 3]),
        "home_ownership": random.choice(["rent", "mortgage", "own"]),
        "has_cosigner": False,
        "has_hecs": random.random() < 0.3,
        "has_bankruptcy": False,
        "state": random.choice(["NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"]),
        "property_value": 0,
        "deposit_amount": 0,
        "applicant_type": random.choice(["single", "couple"]),
    }
