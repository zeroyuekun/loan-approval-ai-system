"""CounterfactualEngine — DiCE-based counterfactual explanation generator.

Generates actionable "what-if" suggestions for denied loan applicants by
varying only applicant-controllable features (loan_amount, loan_term_months,
has_cosigner).  Falls back to binary-search when DiCE times out or returns
no valid counterfactuals.
"""

from __future__ import annotations

import logging
import platform
import signal
from contextlib import contextmanager
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Features the applicant can realistically change on a re-application
PERMITTED_FEATURES = ["loan_amount", "loan_term_months", "has_cosigner"]


# ---------------------------------------------------------------------------
# Timeout helper (cross-platform)
# ---------------------------------------------------------------------------


@contextmanager
def _timeout_ctx(seconds: int):
    """Context manager that raises TimeoutError after *seconds*.

    On Windows (no SIGALRM), if seconds <= 0 we raise immediately; otherwise
    we simply yield without enforcing a timeout — the Celery task-level
    time limit provides the safety net in production.
    """
    if seconds <= 0:
        raise TimeoutError("timeout_seconds <= 0: immediate timeout")

    if platform.system() != "Windows" and hasattr(signal, "SIGALRM"):
        def _handler(signum, frame):
            raise TimeoutError(f"Counterfactual generation exceeded {seconds}s")

        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # Windows — no SIGALRM; just yield
        yield


# ---------------------------------------------------------------------------
# CounterfactualEngine
# ---------------------------------------------------------------------------


class CounterfactualEngine:
    """Generate counterfactual explanations for denied loan applications.

    Parameters
    ----------
    model : sklearn-compatible classifier with ``predict_proba``
    feature_cols : list[str]
        Ordered feature column names the model was trained on.
    training_data : pd.DataFrame
        Representative sample of training data (used by DiCE for ranges).
    threshold : float
        Probability threshold above which the model considers an application
        approved.  Defaults to 0.5.
    """

    def __init__(
        self,
        model: Any,
        feature_cols: list[str],
        training_data: pd.DataFrame,
        threshold: float = 0.5,
    ) -> None:
        self.model = model
        self.feature_cols = feature_cols
        self.training_data = training_data.copy()
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        features_df: pd.DataFrame,
        original_loan_amount: float,
        timeout_seconds: int = 15,
    ) -> list[dict]:
        """Return up to 3 counterfactual suggestions for a denied applicant.

        Returns ``[]`` if the applicant is already predicted as approved.
        """
        # Check if already approved — nothing to explain
        prob = self.model.predict_proba(features_df[self.feature_cols])[0][1]
        if prob >= self.threshold:
            return []

        # Try DiCE first, fall back to binary-search
        try:
            with _timeout_ctx(timeout_seconds):
                cfs = self._dice_counterfactuals(features_df, original_loan_amount)
                if cfs:
                    return cfs
        except (TimeoutError, Exception) as exc:
            logger.info("DiCE counterfactuals failed/timed-out: %s — using fallback", exc)

        return self._fallback_binary_search(features_df, original_loan_amount)

    # ------------------------------------------------------------------
    # DiCE approach
    # ------------------------------------------------------------------

    def _dice_counterfactuals(
        self, features_df: pd.DataFrame, original_loan_amount: float
    ) -> list[dict]:
        import dice_ml

        # Build DiCE data object
        d = dice_ml.Data(
            dataframe=self.training_data,
            continuous_features=[
                c for c in self.feature_cols if c != "has_cosigner"
            ],
            outcome_name=None,  # no outcome column in training_data
        )

        # Build DiCE model wrapper
        m = dice_ml.Model(model=self.model, backend="sklearn")

        exp = dice_ml.Dice(d, m, method="genetic")

        # Permitted ranges for the features we allow to vary
        permitted_range = {
            "loan_amount": [5000.0, original_loan_amount],
            "loan_term_months": [12, 60],
            "has_cosigner": [0, 1],
        }

        # Features to keep frozen (everything except permitted)
        features_to_vary = PERMITTED_FEATURES

        query = features_df[self.feature_cols].copy()

        cf_result = exp.generate_counterfactuals(
            query,
            total_CFs=5,
            desired_class="opposite",
            features_to_vary=features_to_vary,
            permitted_range=permitted_range,
        )

        return self._parse_dice_result(cf_result, features_df, original_loan_amount)

    def _parse_dice_result(
        self, cf_result, features_df: pd.DataFrame, original_loan_amount: float
    ) -> list[dict]:
        """Extract the top-3-smallest-change CFs from a DiCE result."""
        if cf_result.cf_examples_list is None or len(cf_result.cf_examples_list) == 0:
            return []

        cf_df = cf_result.cf_examples_list[0].final_cfs_df
        if cf_df is None or cf_df.empty:
            return []

        original = features_df[self.feature_cols].iloc[0]
        scored: list[tuple[float, dict]] = []

        for _, row in cf_df.iterrows():
            changes: dict[str, Any] = {}
            total_change = 0.0

            for feat in PERMITTED_FEATURES:
                orig_val = original[feat]
                new_val = row[feat]

                if feat == "has_cosigner":
                    if int(new_val) != int(orig_val):
                        changes[feat] = int(new_val)
                        total_change += 1.0
                elif feat == "loan_amount":
                    new_val = float(new_val)
                    new_val = max(5000.0, min(new_val, original_loan_amount))
                    if abs(new_val - float(orig_val)) > 1.0:
                        changes[feat] = round(new_val, 2)
                        total_change += abs(new_val - float(orig_val)) / max(float(orig_val), 1.0)
                elif feat == "loan_term_months":
                    new_val = int(round(float(new_val)))
                    new_val = max(12, min(new_val, 60))
                    if new_val != int(orig_val):
                        changes[feat] = new_val
                        total_change += abs(new_val - int(orig_val)) / 60.0

            if changes:
                statement = self._format_statement(changes, features_df)
                scored.append((total_change, {"changes": changes, "statement": statement}))

        # Sort by smallest total change, take top 3
        scored.sort(key=lambda x: x[0])
        return [item[1] for item in scored[:3]]

    # ------------------------------------------------------------------
    # Binary-search fallback
    # ------------------------------------------------------------------

    def _fallback_binary_search(
        self, features_df: pd.DataFrame, original_loan_amount: float
    ) -> list[dict]:
        """Deterministic fallback: binary-search on loan_amount, then try
        loan_term extension and cosigner toggle."""
        results: list[dict] = []
        original = features_df[self.feature_cols].iloc[0]

        # --- 1. Binary-search on loan_amount ---
        flip_amount = self._binary_search_feature(
            features_df, "loan_amount", 5000.0, original_loan_amount
        )
        if flip_amount is not None:
            changes = {"loan_amount": round(flip_amount, 2)}
            results.append({
                "changes": changes,
                "statement": self._format_statement(changes, features_df),
            })

        # --- 2. Extend loan term ---
        current_term = int(original["loan_term_months"])
        if current_term < 60:
            for candidate_term in [48, 60]:
                if candidate_term <= current_term:
                    continue
                test_df = features_df.copy()
                test_df["loan_term_months"] = candidate_term
                prob = self.model.predict_proba(test_df[self.feature_cols])[0][1]
                if prob >= self.threshold:
                    changes = {"loan_term_months": candidate_term}
                    results.append({
                        "changes": changes,
                        "statement": self._format_statement(changes, features_df),
                    })
                    break

        # --- 3. Cosigner toggle ---
        if int(original["has_cosigner"]) == 0:
            test_df = features_df.copy()
            test_df["has_cosigner"] = 1
            prob = self.model.predict_proba(test_df[self.feature_cols])[0][1]
            if prob >= self.threshold:
                changes = {"has_cosigner": 1}
                results.append({
                    "changes": changes,
                    "statement": self._format_statement(changes, features_df),
                })

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
                    results.append({
                        "changes": changes,
                        "statement": self._format_statement(changes, features_df),
                    })
                    break

        # --- 5. Combined: reduced amount + cosigner ---
        if not results and int(original["has_cosigner"]) == 0:
            test_df = features_df.copy()
            test_df["has_cosigner"] = 1
            flip_amount = self._binary_search_feature(
                test_df, "loan_amount", 5000.0, original_loan_amount
            )
            if flip_amount is not None:
                changes = {
                    "loan_amount": round(flip_amount, 2),
                    "has_cosigner": 1,
                }
                results.append({
                    "changes": changes,
                    "statement": self._format_statement(changes, features_df),
                })

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
            # Ensure we have at least loan_amount reduction
            if not best_changes and current_amount > 5000:
                best_changes["loan_amount"] = 5000.0
            if best_changes:
                results.append({
                    "changes": best_changes,
                    "statement": self._format_statement(best_changes, features_df),
                })

        return results[:3]

    def _binary_search_feature(
        self,
        features_df: pd.DataFrame,
        feature: str,
        low: float,
        high: float,
        iterations: int = 30,
    ) -> float | None:
        """Binary-search for the smallest value of *feature* that flips the
        prediction to approved."""
        flip_value = None
        for _ in range(iterations):
            mid = (low + high) / 2
            test_df = features_df.copy()
            test_df[feature] = mid
            try:
                prob = self.model.predict_proba(test_df[self.feature_cols])[0][1]
                if prob >= self.threshold:
                    flip_value = mid
                    # We want the *largest* value that still flips (closest
                    # to original), so move low upward
                    low = mid
                else:
                    high = mid
            except Exception:
                break
        return flip_value

    # ------------------------------------------------------------------
    # Statement formatting
    # ------------------------------------------------------------------

    def _format_statement(self, changes: dict, features_df: pd.DataFrame) -> str:
        """Produce a human-readable sentence describing the changes."""
        original = features_df.iloc[0]
        parts: list[str] = []

        if "loan_amount" in changes:
            orig = float(original["loan_amount"])
            new = float(changes["loan_amount"])
            parts.append(
                f"Reduce your loan amount from ${orig:,.0f} to ${new:,.0f}"
            )

        if "loan_term_months" in changes:
            orig = int(original["loan_term_months"])
            new = int(changes["loan_term_months"])
            parts.append(
                f"Extend your loan term from {orig} to {new} months"
            )

        if "has_cosigner" in changes:
            parts.append("Add a co-signer to your application")

        return " and ".join(parts) if parts else ""
