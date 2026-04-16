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
        Ordered feature column names the *model* was trained on. In production
        these are the fully-transformed columns (one-hot + engineered
        interactions), not the raw applicant input fields.
    training_data : pd.DataFrame
        Representative sample used by DiCE for range estimation. Treated as
        *raw* (pre-transform) features — the engine applies ``transform_fn``
        before handing rows to the model.
    threshold : float
        Probability threshold above which the model considers an application
        approved.  Defaults to 0.5.
    transform_fn : callable, optional
        Function mapping a raw-features DataFrame to the model's feature
        space (one-hot, scaling, engineered interactions). Defaults to
        identity, which is fine for unit tests that use a model trained
        directly on raw columns but wrong in production — the orchestrator
        MUST pass ``predictor._transform`` so candidate values are scored
        through the same pipeline as live predictions.
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
        prob = self._predict_prob(features_df)
        if prob >= self.threshold:
            return []

        # DiCE requires a model that predicts on the same feature space as
        # the Data object. When a transform_fn is supplied (production path),
        # the model's input space differs from the raw-features space DiCE
        # operates in — running DiCE would need a custom wrapper and is
        # deferred to a future spec. Skip straight to the fallback.
        if self._transform_fn is None:
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

    def _build_dice_dataset(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Return a training-like dataset DiCE can use to estimate feature
        distributions.

        If ``self.training_data`` already has enough rows (>= 50), use it with
        an appended ``_dice_outcome`` column. Otherwise synthesise 200 rows
        around the query by perturbing ``features_df`` and scoring with the
        live model — DiCE only needs the distribution, not ground-truth labels.
        """

        if self.training_data is not None and len(self.training_data) >= 50:
            df = self.training_data[self.feature_cols].copy()
        else:
            rng = np.random.default_rng(42)
            base = features_df[self.feature_cols].iloc[0]
            rows: list[dict] = []
            for _ in range(200):
                row: dict = {}
                for col in self.feature_cols:
                    val = base[col]
                    if col == "has_cosigner":
                        row[col] = int(rng.integers(0, 2))
                    elif col == "loan_term_months":
                        row[col] = int(rng.choice([12, 24, 36, 48, 60]))
                    elif isinstance(val, (int, float, np.integer, np.floating)):
                        # ±50% jitter around the current value; clamp to >= 0
                        jitter = rng.uniform(0.5, 1.5)
                        row[col] = max(0.0, float(val) * jitter)
                    else:
                        row[col] = val
                rows.append(row)
            df = pd.DataFrame(rows)

        # Label rows with the model's prediction so DiCE sees both classes.
        probs = self.model.predict_proba(df[self.feature_cols])[:, 1]
        df = df.copy()
        df["_dice_outcome"] = (probs >= self.threshold).astype(int)
        return df

    def _dice_counterfactuals(self, features_df: pd.DataFrame, original_loan_amount: float) -> list[dict]:
        import dice_ml

        # DiCE's Data object needs a distribution with an outcome column.
        # If training_data is too small (e.g. a single applicant row passed
        # from the orchestrator), synthesise one by perturbing the query.
        dice_df = self._build_dice_dataset(features_df)

        continuous_features = [c for c in self.feature_cols if c != "has_cosigner"]

        d = dice_ml.Data(
            dataframe=dice_df,
            continuous_features=continuous_features,
            outcome_name="_dice_outcome",
        )

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

    def _parse_dice_result(self, cf_result, features_df: pd.DataFrame, original_loan_amount: float) -> list[dict]:
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

    def _fallback_binary_search(self, features_df: pd.DataFrame, original_loan_amount: float) -> list[dict]:
        """Deterministic fallback: binary-search on loan_amount, then try
        loan_term extension and cosigner toggle.

        Reads raw feature values from features_df (not indexed by feature_cols,
        which may be the transformed model-input space that omits categorical
        string columns like state/purpose).
        """
        results: list[dict] = []
        # Read raw values directly — features_df is the applicant's raw row,
        # which has loan_amount / loan_term_months / has_cosigner even when
        # feature_cols describes the transformed model input space.
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
            # Ensure we have at least loan_amount reduction
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
        """Binary-search for the smallest value of *feature* that flips the
        prediction to approved."""
        flip_value = None
        for _ in range(iterations):
            mid = (low + high) / 2
            test_df = features_df.copy()
            test_df[feature] = mid
            try:
                prob = self._predict_prob(test_df)
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
            parts.append(f"Reduce your loan amount from ${orig:,.0f} to ${new:,.0f}")

        if "loan_term_months" in changes:
            orig = int(original["loan_term_months"])
            new = int(changes["loan_term_months"])
            parts.append(f"Extend your loan term from {orig} to {new} months")

        if "has_cosigner" in changes:
            parts.append("Add a co-signer to your application")

        return " and ".join(parts) if parts else ""
