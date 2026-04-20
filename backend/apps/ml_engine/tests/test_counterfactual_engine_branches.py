"""Branch coverage tests for CounterfactualEngine.

Integration tests in test_counterfactual_engine.py use a real sklearn
classifier, which can't deterministically reach every branch in
``_fallback_binary_search``. These tests drive a controllable mock model so
each step of the fallback cascade is exercised:

- Step 1: binary search on loan_amount success (lines 95-96, 218-219)
- Step 2: term-extension ``continue`` on candidate <= current (line 108)
- Step 2: term-extension flip (lines 113-120)
- Step 3: cosigner toggle flip (lines 128-129)
- Step 4: combined amount + term flip (lines 146-157)
- Step 5: combined amount + cosigner flip (lines 165-169)
- Binary search exception handling (lines 222-223)
- _format_statement empty-changes branch
- transform_fn invocation path
"""

import numpy as np
import pandas as pd

from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine


class _PredictFnModel:
    """sklearn-compatible mock backed by a user-supplied probability function.

    ``predict_fn(row: pd.Series) -> float in [0, 1]`` returns p(approved).
    """

    def __init__(self, predict_fn):
        self.predict_fn = predict_fn

    def predict_proba(self, X):
        p_approve = float(self.predict_fn(X.iloc[0]))
        return np.array([[1.0 - p_approve, p_approve]])


_FEATURE_COLS = ["loan_amount", "loan_term_months", "has_cosigner"]


def _row(loan_amount=200_000.0, term=36, has_cosigner=0):
    return pd.DataFrame(
        [
            {
                "loan_amount": float(loan_amount),
                "loan_term_months": int(term),
                "has_cosigner": int(has_cosigner),
            }
        ]
    )


class TestBinarySearchStep1:
    """Step 1: binary search on loan_amount."""

    def test_binary_search_finds_flip_on_loan_amount(self):
        """When a lower loan_amount flips the model, step 1 produces a result."""
        model = _PredictFnModel(lambda r: 0.8 if r["loan_amount"] <= 100_000 else 0.1)
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        result = engine.generate(_row(loan_amount=500_000.0), original_loan_amount=500_000.0)

        assert len(result) >= 1
        first = result[0]["changes"]
        assert "loan_amount" in first
        # Binary search converges just under 100k
        assert first["loan_amount"] <= 100_000


class TestTermExtension:
    """Step 2: extend loan_term_months."""

    def test_continue_skips_candidate_not_greater_than_current(self):
        """current_term=48 means candidate=48 hits `continue` before candidate=60 is tested."""
        model = _PredictFnModel(lambda r: 0.1)  # always deny
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        # Should not raise; the continue path is exercised on candidate=48.
        result = engine.generate(_row(term=48), original_loan_amount=200_000.0)
        assert isinstance(result, list)

    def test_term_extension_to_48_succeeds(self):
        """When term>=48 flips the model, step 2 succeeds with candidate=48 and breaks."""
        model = _PredictFnModel(lambda r: 0.8 if r["loan_term_months"] >= 48 else 0.1)
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        result = engine.generate(_row(term=36), original_loan_amount=200_000.0)

        assert any("loan_term_months" in cf["changes"] for cf in result)
        first_term_cf = next(cf for cf in result if "loan_term_months" in cf["changes"])
        # 48 is tried first and breaks on success — don't cascade to 60.
        assert first_term_cf["changes"]["loan_term_months"] == 48


class TestCosignerToggle:
    """Step 3: has_cosigner 0 -> 1."""

    def test_cosigner_toggle_creates_result(self):
        model = _PredictFnModel(lambda r: 0.8 if int(r["has_cosigner"]) == 1 else 0.1)
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        result = engine.generate(_row(has_cosigner=0), original_loan_amount=200_000.0)

        assert any(cf["changes"].get("has_cosigner") == 1 for cf in result)


class TestCombinedStrategies:
    """Steps 4 and 5: combined changes."""

    def test_combined_amount_plus_term_succeeds(self):
        """Step 4: only amount + extended term together flip the model.

        cosigner=1 skips step 3 so step 4 is the only path that can succeed.
        """

        def predict(r):
            return 0.8 if (r["loan_amount"] < 50_000 and r["loan_term_months"] >= 48) else 0.1

        model = _PredictFnModel(predict)
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        result = engine.generate(_row(term=36, has_cosigner=1), original_loan_amount=200_000.0)

        assert len(result) == 1
        combo = result[0]["changes"]
        # Binary search settles near 50_000 (rounded to 2dp); may land on exactly 50_000.0.
        assert combo.get("loan_amount", float("inf")) <= 50_000
        # 48 tried first in step 4, breaks on success.
        assert combo.get("loan_term_months") == 48

    def test_combined_amount_plus_cosigner_succeeds(self):
        """Step 5: amount reduction + cosigner together flip the model.

        term=60 disables step 2; cosigner=0 activates step 5 (after step 4 fails).
        """

        def predict(r):
            return 0.8 if (r["loan_amount"] < 50_000 and int(r["has_cosigner"]) == 1) else 0.1

        model = _PredictFnModel(predict)
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        result = engine.generate(_row(term=60, has_cosigner=0), original_loan_amount=200_000.0)

        assert len(result) == 1
        combo = result[0]["changes"]
        assert combo.get("has_cosigner") == 1
        assert combo.get("loan_amount", float("inf")) <= 50_000


class TestHeuristicFallback:
    """Step 6: heuristic last-resort when nothing flips the model."""

    def test_heuristic_returns_all_three_levers(self):
        model = _PredictFnModel(lambda r: 0.1)  # nothing ever flips
        engine = CounterfactualEngine(model=model, feature_cols=_FEATURE_COLS, training_data=_row())

        result = engine.generate(
            _row(loan_amount=200_000.0, term=36, has_cosigner=0),
            original_loan_amount=200_000.0,
        )

        assert len(result) == 1
        changes = result[0]["changes"]
        assert changes.get("loan_amount") == 5000.0
        assert changes.get("loan_term_months") == 60
        assert changes.get("has_cosigner") == 1


class TestBinarySearchExceptionHandling:
    def test_break_on_predict_exception(self):
        """Binary search catches predict_proba failures and breaks cleanly."""
        calls = {"n": 0}

        class RaiseOnSecondCall:
            def predict_proba(self, X):
                calls["n"] += 1
                # Call 1 is generate's initial prediction — must succeed.
                # Call 2 is binary search iter 1 — raise to trigger the except/break.
                if calls["n"] == 2:
                    raise RuntimeError("predict boom")
                return np.array([[0.9, 0.1]])  # deny

        engine = CounterfactualEngine(model=RaiseOnSecondCall(), feature_cols=_FEATURE_COLS, training_data=_row())

        # Must not raise — binary search breaks, downstream steps return deny,
        # heuristic fallback produces the final suggestion.
        result = engine.generate(_row(), original_loan_amount=200_000.0)

        assert calls["n"] >= 2
        assert len(result) >= 1


class TestFormatStatement:
    def test_empty_changes_returns_empty_string(self):
        engine = CounterfactualEngine(
            model=_PredictFnModel(lambda r: 0.1),
            feature_cols=_FEATURE_COLS,
            training_data=_row(),
        )
        assert engine._format_statement({}, _row()) == ""

    def test_all_three_levers_in_statement(self):
        engine = CounterfactualEngine(
            model=_PredictFnModel(lambda r: 0.1),
            feature_cols=_FEATURE_COLS,
            training_data=_row(),
        )

        statement = engine._format_statement(
            {"loan_amount": 50_000.0, "loan_term_months": 60, "has_cosigner": 1},
            _row(loan_amount=200_000.0, term=36, has_cosigner=0),
        )

        assert "Reduce your loan amount" in statement
        assert "Extend your loan term" in statement
        assert "Add a co-signer" in statement


class TestTransformFnPath:
    def test_transform_fn_invoked_before_predict(self):
        captured = []

        def transform(df):
            captured.append(df.copy())
            return df

        engine = CounterfactualEngine(
            model=_PredictFnModel(lambda r: 0.1),
            feature_cols=_FEATURE_COLS,
            training_data=_row(),
            transform_fn=transform,
        )
        engine.generate(_row(), original_loan_amount=200_000.0)

        assert len(captured) >= 1
