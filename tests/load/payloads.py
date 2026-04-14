"""Synthetic loan payloads for load testing.

Values are chosen from realistic AU ranges (matching ml_engine data_generator
distributions at a coarse level). Distributions are uniform — variance is not
the point here; throughput is.
"""
import random
import uuid


def loan_application_payload() -> dict:
    """A minimal-but-valid LoanApplication payload. Adjust to match serializer."""
    return {
        "loan_amount": random.choice([10000, 25000, 50000, 100000, 250000, 500000]),
        "loan_term_months": random.choice([12, 24, 36, 60, 84, 120, 240, 360]),
        "loan_purpose": random.choice(["car", "home", "personal", "debt_consolidation"]),
        "annual_income": random.randint(45000, 180000),
        "employment_type": random.choice(
            ["payg_permanent", "payg_casual", "self_employed", "contract"]
        ),
        "employment_length": random.randint(0, 25),
        "credit_score": random.randint(400, 850),
        "monthly_expenses": random.randint(1500, 6000),
        "existing_credit_card_limit": random.choice([0, 5000, 10000, 20000]),
        "number_of_dependants": random.choice([0, 0, 1, 2, 3]),
        "home_ownership": random.choice(["rent", "mortgage", "own"]),
        "state": random.choice(["NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"]),
        # Idempotency / uniqueness marker
        "client_ref": f"load-{uuid.uuid4().hex[:12]}",
    }
