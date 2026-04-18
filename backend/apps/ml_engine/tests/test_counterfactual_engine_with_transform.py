"""Regression test for the production bug where CounterfactualEngine failed
with ``KeyError: 'state_NSW', 'purpose_home', ... not in index`` because the
raw features_df doesn't include one-hot / engineered columns the real model
expects.

The fix: pass ``transform_fn`` so the engine applies the same pipeline the
predictor uses before scoring candidate values. This test reproduces the
production shape (raw features in, transformed features for prediction).
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine


def _make_transforming_model():
    """Return (model, feature_cols, transform_fn) mimicking a real predictor.

    Training data has one-hot + engineered columns the model sees, but the
    CF engine receives raw features (loan_amount, loan_term_months,
    has_cosigner, purpose, state) and must apply transform_fn before predict.
    """
    rng = np.random.RandomState(0)
    n = 300
    raw = pd.DataFrame(
        {
            "loan_amount": rng.uniform(5000, 500000, n),
            "loan_term_months": rng.choice([12, 24, 36, 48, 60], n),
            "has_cosigner": rng.choice([0, 1], n),
            "annual_income": rng.uniform(20000, 200000, n),
            "credit_score": rng.randint(300, 1200, n),
            "purpose": rng.choice(["home", "auto", "personal"], n),
            "state": rng.choice(["NSW", "VIC", "QLD"], n),
        }
    )

    def transform_fn(df: pd.DataFrame) -> pd.DataFrame:
        """One-hot encode categoricals and add an engineered interaction."""
        out = df.copy()
        for purpose in ("home", "auto", "personal"):
            out[f"purpose_{purpose}"] = (out["purpose"] == purpose).astype(int)
        for state in ("NSW", "VIC", "QLD"):
            out[f"state_{state}"] = (out["state"] == state).astype(int)
        out["loan_to_income"] = out["loan_amount"] / out["annual_income"].clip(lower=1)
        return out

    transformed = transform_fn(raw)
    feature_cols = [
        "loan_amount",
        "loan_term_months",
        "has_cosigner",
        "annual_income",
        "credit_score",
        "purpose_home",
        "purpose_auto",
        "purpose_personal",
        "state_NSW",
        "state_VIC",
        "state_QLD",
        "loan_to_income",
    ]

    # Label: approve if good credit and manageable loan-to-income
    y = ((transformed["credit_score"] > 600) & (transformed["loan_to_income"] < 3.5)).astype(int)
    model = GradientBoostingClassifier(n_estimators=30, random_state=0)
    model.fit(transformed[feature_cols], y)

    return model, feature_cols, transform_fn


def test_engine_runs_against_transforming_model():
    """Regression: the CF engine must work when the model's feature_cols
    include columns not present in the raw applicant features_df."""
    model, feature_cols, transform_fn = _make_transforming_model()

    # Raw features for a denied applicant — note these columns are a
    # strict subset of what the model expects.
    raw_query = pd.DataFrame(
        [
            {
                "loan_amount": 300000.0,
                "loan_term_months": 36,
                "has_cosigner": 0,
                "annual_income": 40000.0,
                "credit_score": 450,
                "purpose": "home",
                "state": "NSW",
            }
        ]
    )

    engine = CounterfactualEngine(
        model=model,
        feature_cols=feature_cols,
        training_data=raw_query,  # small — triggers synthetic-dataset path
        threshold=0.5,
        transform_fn=transform_fn,
    )

    # Must not raise. Previously would raise
    # ``KeyError: '[purpose_home, ..., state_QLD] not in index'``.
    results = engine.generate(raw_query, original_loan_amount=300000.0)

    # Binary-search fallback should produce at least one suggestion
    assert isinstance(results, list)
    assert len(results) >= 1
    for cf in results:
        assert "changes" in cf
        assert "statement" in cf
        # Only the allowed features should be varied
        for feat in cf["changes"]:
            assert feat in {"loan_amount", "loan_term_months", "has_cosigner"}


def test_engine_without_transform_still_works():
    """Backwards compat: calling the engine without transform_fn uses the
    model directly (the old test pattern). Verify that path still works."""
    rng = np.random.RandomState(42)
    n = 200
    X = pd.DataFrame(
        {
            "loan_amount": rng.uniform(5000, 500000, n),
            "loan_term_months": rng.choice([12, 24, 36, 48, 60], n),
            "has_cosigner": rng.choice([0, 1], n),
            "credit_score": rng.randint(300, 1200, n),
        }
    )
    y = (X["credit_score"] > 600).astype(int)
    model = GradientBoostingClassifier(n_estimators=20, random_state=42)
    model.fit(X, y)

    query = pd.DataFrame(
        [
            {
                "loan_amount": 250000.0,
                "loan_term_months": 36,
                "has_cosigner": 0,
                "credit_score": 450,
            }
        ]
    )

    engine = CounterfactualEngine(
        model=model,
        feature_cols=list(X.columns),
        training_data=X,
        threshold=0.5,
        # No transform_fn — identity path
    )
    results = engine.generate(query, original_loan_amount=250000.0)
    assert isinstance(results, list)
    assert len(results) >= 1
