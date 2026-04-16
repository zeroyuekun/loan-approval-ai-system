import inspect

import numpy as np
import pandas as pd

from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine


class TestCounterfactualEngine:
    def _make_engine(self):
        from sklearn.ensemble import GradientBoostingClassifier

        rng = np.random.RandomState(42)
        n = 200
        X = pd.DataFrame(
            {
                "annual_income": rng.uniform(30000, 200000, n),
                "credit_score": rng.randint(300, 1200, n),
                "loan_amount": rng.uniform(5000, 500000, n),
                "loan_term_months": rng.choice([12, 24, 36, 48, 60], n),
                "debt_to_income": rng.uniform(1.0, 10.0, n),
                "employment_length": rng.randint(0, 30, n),
                "has_cosigner": rng.choice([0, 1], n),
                "monthly_expenses": rng.uniform(1000, 10000, n),
                "existing_credit_card_limit": rng.uniform(0, 50000, n),
            }
        )
        y = (X["credit_score"] > 600).astype(int)
        model = GradientBoostingClassifier(n_estimators=20, random_state=42)
        model.fit(X, y)
        return CounterfactualEngine(model=model, feature_cols=list(X.columns), training_data=X)

    def _denied_applicant(self):
        return pd.DataFrame(
            [
                {
                    "annual_income": 30000.0,
                    "credit_score": 400,
                    "loan_amount": 200000.0,
                    "loan_term_months": 36,
                    "debt_to_income": 8.0,
                    "employment_length": 1,
                    "has_cosigner": 0,
                    "monthly_expenses": 5000.0,
                    "existing_credit_card_limit": 20000.0,
                }
            ]
        )

    def test_returns_counterfactuals_for_denied_applicant(self):
        engine = self._make_engine()
        result = engine.generate(self._denied_applicant(), original_loan_amount=200000.0)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert len(result) <= 3

    def test_only_varies_permitted_features(self):
        engine = self._make_engine()
        result = engine.generate(self._denied_applicant(), original_loan_amount=200000.0)
        permitted = {"loan_amount", "loan_term_months", "has_cosigner"}
        for cf in result:
            for feature in cf["changes"]:
                assert feature in permitted, f"Unexpected feature varied: {feature}"

    def test_loan_amount_within_bounds(self):
        engine = self._make_engine()
        result = engine.generate(self._denied_applicant(), original_loan_amount=200000.0)
        for cf in result:
            if "loan_amount" in cf["changes"]:
                assert 5000 <= cf["changes"]["loan_amount"] <= 200000.0

    def test_loan_term_within_bounds(self):
        engine = self._make_engine()
        result = engine.generate(self._denied_applicant(), original_loan_amount=200000.0)
        for cf in result:
            if "loan_term_months" in cf["changes"]:
                assert 12 <= cf["changes"]["loan_term_months"] <= 60

    def test_has_statement_field(self):
        engine = self._make_engine()
        result = engine.generate(self._denied_applicant(), original_loan_amount=200000.0)
        for cf in result:
            assert "statement" in cf
            assert isinstance(cf["statement"], str)
            assert len(cf["statement"]) > 0

    def test_fallback_on_timeout(self):
        engine = self._make_engine()
        result = engine.generate(self._denied_applicant(), original_loan_amount=200000.0, timeout_seconds=0)
        assert isinstance(result, list)
        assert len(result) >= 1
        for cf in result:
            assert "statement" in cf

    def test_returns_empty_for_approved_applicant(self):
        engine = self._make_engine()
        approved = pd.DataFrame(
            [
                {
                    "annual_income": 200000.0,
                    "credit_score": 1100,
                    "loan_amount": 10000.0,
                    "loan_term_months": 60,
                    "debt_to_income": 1.5,
                    "employment_length": 20,
                    "has_cosigner": 1,
                    "monthly_expenses": 2000.0,
                    "existing_credit_card_limit": 5000.0,
                }
            ]
        )
        result = engine.generate(approved, original_loan_amount=10000.0)
        assert result == []


def test_generate_default_timeout_is_20_seconds():
    """B1: caller/callee timeout mismatch fix — generate() defaults to 20s."""
    from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine

    sig = inspect.signature(CounterfactualEngine.generate)
    param = sig.parameters["timeout_seconds"]
    assert param.default == 20, (
        f"generate() default timeout should be 20s after B1 fix; got {param.default}"
    )


def test_dice_total_cfs_is_three():
    """B1: total_CFs reduced 5→3 to cut DiCE wall time."""
    from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine

    src = inspect.getsource(CounterfactualEngine._dice_counterfactuals)
    assert "total_CFs=3" in src or "total_CFs = 3" in src, (
        "DiCE call should use total_CFs=3 after B1 fix"
    )
