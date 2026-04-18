"""CounterfactualEngine — binary-search counterfactual explanation generator.

Generates actionable "what-if" suggestions for denied loan applicants by
varying only applicant-controllable features (loan_amount, loan_term_months,
has_cosigner). Uses deterministic binary search on loan_amount with term
extension and cosigner toggling as secondary strategies.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

PERMITTED_FEATURES = ["loan_amount", "loan_term_months", "has_cosigner"]


class CounterfactualEngine:
    """Generate counterfactual explanations for denied loan applications.

    Parameters
    ----------
    model : sklearn-compatible classifier with ``predict_proba``
    feature_cols : list[str]
        Ordered feature column names the *model* was trained on. In production
        these are the fully-transformed columns (one-hot + engineered
        interactions), not the raw applicant input fields.
    training_data : pd.DataFrame
        Representative sample kept for API compatibility (the DiCE path used
        it; the binary-search path ignores it).
    threshold : float
        Probability threshold above which the model considers an application
        approved. Defaults to 0.5.
    transform_fn : callable, optional
        Function mapping a raw-features DataFrame to the model's feature
        space (one-hot, scaling, engineered interactions). Defaults to
        identity. The orchestrator passes ``predictor._transform`` so
        candidate values are scored through the same pipeline as live
        predictions.
    """

    def __init__(
        self,
        model: Any,
        feature_cols: list[str],
        training_data: pd.DataFrame,
        threshold: float = 0.5,
        transform_fn: Any = None,
    ) -> None:
        self.model = model
        self.feature_cols = feature_cols
        self.training_data = training_data.copy()
        self.threshold = threshold
        self._transform_fn = transform_fn

    def _predict_prob(self, raw_df: pd.DataFrame) -> float:
        """Predict approval probability for a single raw-features row.

        Applies ``transform_fn`` (if provided) before calling ``predict_proba``.
        """
        if self._transform_fn is not None:
            transformed = self._transform_fn(raw_df.copy())
        else:
            transformed = raw_df
        return float(self.model.predict_proba(transformed[self.feature_cols])[0][1])

    def generate(self, features_df: pd.DataFrame, original_loan_amount: float) -> list[dict]:
        """Return up to 3 counterfactual suggestions for a denied applicant.

        Returns ``[]`` if the applicant is already predicted as approved.
        """
        prob = self._predict_prob(features_df)
        if prob >= self.threshold:
            return []

        return self._fallback_binary_search(features_df, original_loan_amount)

    def _fallback_binary_search(self, features_df: pd.DataFrame, original_loan_amount: float) -> list[dict]:
        """Deterministic search: binary-search on loan_amount, then try
        loan_term extension and cosigner toggle.

        Reads raw feature values from features_df (not indexed by feature_cols,
        which may be the transformed model-input space that omits categorical
        string columns like state/purpose).
        """
        results: list[dict] = []
        original = features_df.iloc[0]

        # --- 1. Binary-search on loan_amount ---
        flip_amount = self._binary_search_feature(features_df, "loan_amount", 5000.0, original_loan_amount)
        if flip_amount is not None:
            changes = {"loan_amount": round(flip_amount, 2)}
            results.append(
                {
                    "changes": changes,
                    "statement": self._format_statement(changes, features_df),
                }
            )

        # --- 2. Extend loan term ---
        current_term = int(original["loan_term_months"])
        if current_term < 60:
            for candidate_term in [48, 60]:
                if candidate_term <= current_term:
                    continue
                test_df = features_df.copy()
                test_df["loan_term_months"] = candidate_term
                prob = self._predict_prob(test_df)
                if prob >= self.threshold:
                    changes = {"loan_term_months": candidate_term}
                    results.append(
                        {
                            "changes": changes,
                            "statement": self._format_statement(changes, features_df),
                        }
                    )
                    break

        # --- 3. Cosigner toggle ---
        if int(original["has_cosigner"]) == 0:
            test_df = features_df.copy()
            test_df["has_cosigner"] = 1
            prob = self._predict_prob(test_df)
            if prob >= self.threshold:
                changes = {"has_cosigner": 1}
                results.append(
                    {
                        "changes": changes,
                        "statement": self._format_statement(changes, features_df),
                    }
                )

        # --- 4. Combined: reduced amount + extended term ---
        if not results:
            for candidate_term in [48, 60]:
                flip_amount = self._binary_search_feature(
                    features_df.assign(loan_term_months=candidate_term),
                    "loan_amount",
                    5000.0,
                    original_loan_amount,
                )
                if flip_amount is not None:
                    changes: dict[str, Any] = {
                        "loan_amount": round(flip_amount, 2),
                    }
                    if candidate_term != current_term:
                        changes["loan_term_months"] = candidate_term
                    results.append(
                        {
                            "changes": changes,
                            "statement": self._format_statement(changes, features_df),
                        }
                    )
                    break

        # --- 5. Combined: reduced amount + cosigner ---
        if not results and int(original["has_cosigner"]) == 0:
            test_df = features_df.copy()
            test_df["has_cosigner"] = 1
            flip_amount = self._binary_search_feature(test_df, "loan_amount", 5000.0, original_loan_amount)
            if flip_amount is not None:
                changes = {
                    "loan_amount": round(flip_amount, 2),
                    "has_cosigner": 1,
                }
                results.append(
                    {
                        "changes": changes,
                        "statement": self._format_statement(changes, features_df),
                    }
                )

        # --- 6. Heuristic last resort ---
        # When no combination flips the model (e.g. dominant immutable feature),
        # still offer the best-effort combination so the applicant has guidance.
        if not results:
            best_changes: dict[str, Any] = {}
            current_amount = float(original["loan_amount"])
            if current_amount > 5000:
                best_changes["loan_amount"] = 5000.0
            if current_term < 60:
                best_changes["loan_term_months"] = 60
            if int(original["has_cosigner"]) == 0:
                best_changes["has_cosigner"] = 1
            if not best_changes and current_amount > 5000:
                best_changes["loan_amount"] = 5000.0
            if best_changes:
                results.append(
                    {
                        "changes": best_changes,
                        "statement": self._format_statement(best_changes, features_df),
                    }
                )

        return results[:3]

    def _binary_search_feature(
        self,
        features_df: pd.DataFrame,
        feature: str,
        low: float,
        high: float,
        iterations: int = 30,
    ) -> float | None:
        """Binary-search for the largest value of *feature* that still flips
        the prediction to approved (closest to the applicant's original)."""
        flip_value = None
        for _ in range(iterations):
            mid = (low + high) / 2
            test_df = features_df.copy()
            test_df[feature] = mid
            try:
                prob = self._predict_prob(test_df)
                if prob >= self.threshold:
                    flip_value = mid
                    low = mid
                else:
                    high = mid
            except Exception:
                break
        return flip_value

    def _format_statement(self, changes: dict, features_df: pd.DataFrame) -> str:
        """Produce a human-readable sentence describing the changes."""
        original = features_df.iloc[0]
        parts: list[str] = []

        if "loan_amount" in changes:
            orig = float(original["loan_amount"])
            new = float(changes["loan_amount"])
            parts.append(f"Reduce your loan amount from ${orig:,.0f} to ${new:,.0f}")

        if "loan_term_months" in changes:
            orig = int(original["loan_term_months"])
            new = int(changes["loan_term_months"])
            parts.append(f"Extend your loan term from {orig} to {new} months")

        if "has_cosigner" in changes:
            parts.append("Add a co-signer to your application")

        return " and ".join(parts) if parts else ""
