"""Per-application explanation helpers used to decorate a single prediction.

Two pure functions carved out of `ModelPredictor` during the Arm C Phase 1
refactor:

- `compute_conformal_interval(probability, conformal_scores, alpha)` — split
  conformal prediction interval with the Small Sample Beta Correction (SSBC,
  arxiv.org/abs/2509.15349) for calibration sets smaller than 500. Returns a
  finite-sample coverage-guaranteed interval around the predicted probability.

- `search_counterfactuals(...)` — inline binary-search counterfactual
  generator used when DiCE is unavailable or too slow. For each of the top-3
  feature importances with known bounds, binary-searches the value that
  flips the model's decision. Distinct from the production DiCE-based
  `counterfactual_engine.py`.

Both functions are pure — no Django, no module state — so tests hit them
directly without standing up a full predictor.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

__all__ = ["compute_conformal_interval", "search_counterfactuals"]

logger = logging.getLogger(__name__)


# Feature bounds for the binary-search counterfactual scan. Kept at module
# scope so the search surface is visible alongside the search itself.
_COUNTERFACTUAL_FEATURE_BOUNDS = {
    "credit_score": (300, 1200),
    "annual_income": (20000, 2000000),
    "debt_to_income": (0, 10),
    "employment_length": (0, 50),
    "loan_amount": (5000, 5000000),
    "monthly_expenses": (500, 50000),
    "existing_credit_card_limit": (0, 200000),
}


# Features where DECREASING the value is the direction that improves the
# decision (e.g. lowering DTI, loan amount, expenses). All other features in
# `_COUNTERFACTUAL_FEATURE_BOUNDS` are "increase improves".
_DECREASE_IS_BETTER = frozenset(
    {
        "debt_to_income",
        "monthly_expenses",
        "loan_amount",
        "existing_credit_card_limit",
    }
)


def compute_conformal_interval(
    probability: float,
    conformal_scores,
    alpha: float = 0.05,
) -> dict:
    """Compute a split-conformal prediction interval around `probability`.

    `conformal_scores` is a 1-D array of nonconformity scores computed on a
    held-out validation set at training time. The (1-alpha)-quantile of those
    scores gives `q` such that [prob - q, prob + q] has coverage ≥ 1-alpha.

    For small calibration sets (n < 500) the finite-sample SSBC correction
    tightens alpha so `P(coverage >= 1-alpha) >= 0.9`.
    """
    conformal_scores = np.asarray(conformal_scores)
    if len(conformal_scores) == 0:
        return {
            "lower": round(probability, 4),
            "upper": round(probability, 4),
            "confidence_level": 1 - alpha,
            "available": False,
        }

    n = len(conformal_scores)
    sorted_scores = np.sort(conformal_scores)

    ssbc_applied = False
    if n < 500:
        try:
            from scipy.stats import beta as beta_dist

            adjusted_alpha = alpha
            for candidate_alpha in np.arange(alpha * 0.5, alpha, 0.001):
                k = int(np.ceil((1 - candidate_alpha) * (n + 1))) - 1
                k = min(k, n - 1)
                coverage_prob = 1 - beta_dist.cdf(1 - alpha, n - k, k + 1)
                if coverage_prob >= 0.9:
                    adjusted_alpha = candidate_alpha
                    break

            if adjusted_alpha != alpha:
                logger.info(
                    "SSBC: adjusted alpha from %.3f to %.3f (n=%d, target coverage=0.9)",
                    alpha,
                    adjusted_alpha,
                    n,
                )
                alpha = adjusted_alpha
                ssbc_applied = True
        except ImportError:
            logger.debug("scipy not available for SSBC correction")

    q_idx = int(np.ceil((1 - alpha) * (n + 1))) - 1
    q_idx = min(max(q_idx, 0), n - 1)
    q = float(sorted_scores[q_idx])

    lower = max(0.0, probability - q)
    upper = min(1.0, probability + q)

    return {
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "width": round(upper - lower, 4),
        "confidence_level": 1 - alpha,
        "ssbc_applied": ssbc_applied,
        "available": True,
    }


def search_counterfactuals(
    features_df: pd.DataFrame,
    feature_importances: dict,
    model_bundle: dict,
    *,
    transform_fn,
    feature_cols,
) -> list[dict]:
    """Binary-search for actionable counterfactuals on the top-3 features.

    For each of the top-3 features (by SHAP importance) with known search
    bounds, binary-searches the value that flips the model's decision.
    Returns a list of statements like
    `"Increasing annual income from $50,000 to $75,000 would change the outcome"`.

    Failing silently per-feature is intentional: one feature's flip-search
    blowing up should not block the others.
    """
    counterfactuals: list[dict] = []
    if not feature_importances:
        return counterfactuals

    model = model_bundle["model"]
    threshold = model_bundle.get("threshold", 0.5)

    sorted_features = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:3]

    for feature_name, _importance in sorted_features:
        if feature_name not in features_df.columns:
            continue

        bounds = _COUNTERFACTUAL_FEATURE_BOUNDS.get(feature_name)
        if bounds is None:
            continue

        current_value = features_df[feature_name].iloc[0]
        decrease_is_better = feature_name in _DECREASE_IS_BETTER

        if decrease_is_better:
            low, high = bounds[0], float(current_value)
        else:
            low, high = float(current_value), bounds[1]

        flip_value = None
        for _ in range(30):
            mid = (low + high) / 2
            test_df = features_df.copy()
            test_df[feature_name] = mid

            try:
                transformed_df = transform_fn(test_df)
                prob = model.predict_proba(transformed_df[feature_cols])[0][1]

                if prob >= threshold:
                    flip_value = mid
                    if decrease_is_better:
                        low = mid
                    else:
                        high = mid
                else:
                    if decrease_is_better:
                        high = mid
                    else:
                        low = mid
            except Exception as e:
                logger.debug("Counterfactual binary search step failed: %s", e)
                break

        if flip_value is None:
            continue

        readable_name = feature_name.replace("_", " ").title()

        if feature_name in ("annual_income", "loan_amount", "monthly_expenses", "existing_credit_card_limit"):
            current_fmt = f"${current_value:,.0f}"
            target_fmt = f"${flip_value:,.0f}"
        elif feature_name == "credit_score":
            current_fmt = f"{int(current_value)}"
            target_fmt = f"{int(flip_value)}"
        elif feature_name == "debt_to_income":
            current_fmt = f"{current_value:.1f}x"
            target_fmt = f"{flip_value:.1f}x"
        else:
            current_fmt = f"{current_value:.1f}"
            target_fmt = f"{flip_value:.1f}"

        direction = "Reducing" if decrease_is_better else "Increasing"
        counterfactuals.append(
            {
                "feature": feature_name,
                "current_value": float(current_value),
                "target_value": round(float(flip_value), 2),
                "statement": (
                    f"{direction} {readable_name.lower()} from {current_fmt} to {target_fmt} would change the outcome"
                ),
            }
        )

    return counterfactuals
