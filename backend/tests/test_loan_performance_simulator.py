"""Unit tests for LoanPerformanceSimulator.

Markov-chain simulation is non-deterministic; tests focus on output shape,
column contracts, and risk-adjustment direction (riskier inputs should
produce >= default rate, not strict equality).
"""

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.loan_performance_simulator import LoanPerformanceSimulator


@pytest.fixture
def simulator():
    return LoanPerformanceSimulator()


def _make_input_df(n=20, approved=True, application_date="2024-06-01"):
    return pd.DataFrame(
        {
            "loan_amount": [200_000] * n,
            "loan_term_months": [360] * n,
            "interest_rate": [6.0] * n,
            "credit_score": [720] * n,
            "approved": [int(approved)] * n,
            "application_date": [application_date] * n,
            "debt_to_income": [4.0] * n,
            "lvr": [0.70] * n,
            "cash_rate": [4.35] * n,
            "employment_type": ["payg_permanent"] * n,
        }
    )


class TestOutputShape:
    def test_returns_dataframe(self, simulator):
        out = simulator.simulate_loan_performance(_make_input_df(5))
        assert isinstance(out, pd.DataFrame)

    def test_no_rows_lost(self, simulator):
        out = simulator.simulate_loan_performance(_make_input_df(20))
        assert len(out) == 20

    def test_adds_expected_columns(self, simulator):
        out = simulator.simulate_loan_performance(_make_input_df(5))
        for col in ("months_on_book", "ever_30dpd", "ever_90dpd", "default_flag", "prepaid_flag", "current_status"):
            assert col in out.columns

    def test_months_on_book_non_negative(self, simulator):
        out = simulator.simulate_loan_performance(_make_input_df(10))
        assert (out["months_on_book"] >= 0).all()

    def test_flags_are_binary(self, simulator):
        out = simulator.simulate_loan_performance(_make_input_df(20))
        for col in ("ever_30dpd", "ever_90dpd", "default_flag", "prepaid_flag"):
            assert set(out[col].unique()).issubset({0, 1})


class TestApprovedVsDenied:
    def test_denied_loans_have_status_denied(self, simulator):
        out = simulator.simulate_loan_performance(_make_input_df(5, approved=False))
        assert (out["current_status"] == "denied").all()
        assert (out["months_on_book"] == 0).all()

    def test_approved_loans_have_real_status(self, simulator):
        np.random.seed(42)
        out = simulator.simulate_loan_performance(_make_input_df(20, approved=True))
        valid_states = {"performing", "30dpd", "60dpd", "90dpd", "default", "prepaid"}
        assert set(out["current_status"].unique()).issubset(valid_states)


class TestRiskAdjustment:
    def test_higher_dti_higher_or_equal_default_rate(self, simulator):
        np.random.seed(42)
        low = _make_input_df(200)
        low["debt_to_income"] = 2.0
        high = _make_input_df(200)
        high["debt_to_income"] = 8.0

        out_low = simulator.simulate_loan_performance(low)
        np.random.seed(42)
        out_high = simulator.simulate_loan_performance(high)

        # Higher DTI raises risk_multiplier — default rate should be >=
        assert out_high["default_flag"].mean() >= out_low["default_flag"].mean()

    def test_zero_months_on_book_marked_performing(self, simulator):
        df = _make_input_df(5, application_date="2025-12-01")
        out = simulator.simulate_loan_performance(df)
        # Reference date in code is 2025-12-31, so MOB ~0
        for status in out.loc[out["months_on_book"] == 0, "current_status"]:
            assert status == "performing"


class TestEmptyInput:
    def test_empty_input_returns_empty_output(self, simulator):
        empty = pd.DataFrame(
            columns=[
                "loan_amount",
                "loan_term_months",
                "interest_rate",
                "credit_score",
                "approved",
                "application_date",
                "debt_to_income",
                "lvr",
                "cash_rate",
                "employment_type",
            ]
        )
        out = simulator.simulate_loan_performance(empty)
        assert len(out) == 0
        assert "months_on_book" in out.columns
