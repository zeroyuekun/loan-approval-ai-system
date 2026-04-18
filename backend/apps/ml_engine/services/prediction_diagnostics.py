"""Per-application diagnostics used to decorate a single prediction.

Two pure functions carved out of `ModelPredictor` during the Arm C Phase 1
refactor:

- `check_feature_drift(features, reference_distribution)` — flags when a
  single applicant's feature values are outliers (|z| > 3) relative to the
  training-data moments recorded at fit time. This is **per application** —
  it tells the underwriter "don't trust this score, the model has never seen
  an input like this". For portfolio PSI/CSI/KS monitoring use
  `drift_monitor.py` instead.

- `run_stress_scenarios(...)` — APRA APS 110-flavoured stress test that
  shocks income (−15%), property value (−20%, with LVR-driven LMI recompute),
  credit score (−50), and the combined scenario. Returns probability and
  decision per scenario so the model's response to adverse conditions is
  visible on the prediction card.

Kept as free functions (no class state) so they can be unit-tested without
a model version, a DB, or the full `ModelPredictor` constructor. The
predictor's delegator methods are one-liners around these helpers.
"""

from __future__ import annotations

import logging

import pandas as pd

from apps.ml_engine.services.policy_recompute import (
    recompute_lvr_driven_policy_vars,
)

__all__ = ["check_feature_drift", "run_stress_scenarios"]

logger = logging.getLogger(__name__)


def check_feature_drift(features: dict, reference_distribution: dict | None) -> list[dict]:
    """Flag features whose applicant value is far from the training distribution.

    Returns a list of warning dicts with feature, value, z_score, severity,
    and human-readable message. Severity is "drift" (|z| > 4) or "warning"
    (|z| > 3). Features with std < 0.001 are skipped to avoid false positives
    from near-constant training columns.
    """
    warnings: list[dict] = []
    if not reference_distribution:
        return warnings

    for col, ref in reference_distribution.items():
        val = features.get(col)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue

        mean = ref.get("mean", 0)
        std = ref.get("std", 1)

        if std < 0.001:
            continue

        z_score = abs(val - mean) / std
        if z_score > 4.0:
            warnings.append(
                {
                    "feature": col,
                    "value": val,
                    "z_score": round(z_score, 2),
                    "training_mean": round(mean, 2),
                    "training_std": round(std, 2),
                    "severity": "drift",
                    "message": (
                        f"{col} value ({val:,.2f}) is {z_score:.1f} standard deviations "
                        f"from the training mean ({mean:,.2f}). The model may not "
                        f"be reliable for this input range."
                    ),
                }
            )
        elif z_score > 3.0:
            warnings.append(
                {
                    "feature": col,
                    "value": val,
                    "z_score": round(z_score, 2),
                    "training_mean": round(mean, 2),
                    "training_std": round(std, 2),
                    "severity": "warning",
                    "message": (
                        f"{col} value ({val:,.2f}) is {z_score:.1f} standard deviations "
                        f"from the training mean ({mean:,.2f}). This is unusual but "
                        f"within tolerance."
                    ),
                }
            )

    return warnings


def run_stress_scenarios(
    features: dict,
    threshold: float,
    *,
    model,
    transform_fn,
    feature_cols,
) -> dict:
    """Run 4 adverse scenarios to show model behavior under stress.

    Required under APRA APS 110 for stress testing. Shows that worse inputs
    produce lower approval probabilities (model degrades sensibly).

    Scenarios:
      1. Income −15% (re-derives DTI)
      2. Property value −20% (re-derives LMI via `recompute_lvr_driven_policy_vars`)
      3. Credit score −50 (floored at 300)
      4. Combined: all three shocks at once

    Fails open: if any step raises, logs and returns a result with
    `base_probability=None` and empty scenarios rather than propagating —
    the predict() caller should surface the main score even when stress
    testing fails.
    """
    scenarios: dict = {}
    base_prob = None

    try:
        df_base = pd.DataFrame([features])
        df_base = transform_fn(df_base)
        base_prob = float(model.predict_proba(df_base[feature_cols])[0][1])

        # Scenario 1: Income -15%
        stressed = features.copy()
        stressed["annual_income"] = float(stressed["annual_income"]) * 0.85
        if stressed["annual_income"] > 0:
            stressed["debt_to_income"] = float(stressed.get("loan_amount", 0)) / stressed["annual_income"]
        else:
            stressed["debt_to_income"] = 999.0  # Maximum DTI when income is zero
        df_s = pd.DataFrame([stressed])
        df_s = transform_fn(df_s)
        prob = float(model.predict_proba(df_s[feature_cols])[0][1])
        scenarios["income_minus_15pct"] = {
            "probability": round(prob, 4),
            "decision": "approved" if prob >= threshold else "denied",
            "change": round(prob - base_prob, 4),
        }

        # Scenario 2: Property value -20%
        stressed = features.copy()
        if float(stressed.get("property_value", 0)) > 0:
            stressed["property_value"] = float(stressed["property_value"]) * 0.80
            # Re-derive LVR-driven LMI features so stressed-LVR drives
            # stressed LMI — otherwise the model sees stale policy vars
            # and Scenario 2 looks optimistically low-risk at LVR ~0.80.
            recompute_lvr_driven_policy_vars(stressed)
        df_s = pd.DataFrame([stressed])
        df_s = transform_fn(df_s)
        prob = float(model.predict_proba(df_s[feature_cols])[0][1])
        scenarios["property_minus_20pct"] = {
            "probability": round(prob, 4),
            "decision": "approved" if prob >= threshold else "denied",
            "change": round(prob - base_prob, 4),
        }

        # Scenario 3: Credit score -50
        stressed = features.copy()
        stressed["credit_score"] = max(300, int(stressed["credit_score"]) - 50)
        df_s = pd.DataFrame([stressed])
        df_s = transform_fn(df_s)
        prob = float(model.predict_proba(df_s[feature_cols])[0][1])
        scenarios["credit_minus_50"] = {
            "probability": round(prob, 4),
            "decision": "approved" if prob >= threshold else "denied",
            "change": round(prob - base_prob, 4),
        }

        # Scenario 4: Combined stress (all three)
        stressed = features.copy()
        stressed["annual_income"] = float(stressed["annual_income"]) * 0.85
        if stressed["annual_income"] > 0:
            stressed["debt_to_income"] = float(stressed.get("loan_amount", 0)) / stressed["annual_income"]
        else:
            stressed["debt_to_income"] = 999.0  # Maximum DTI when income is zero
        if float(stressed.get("property_value", 0)) > 0:
            stressed["property_value"] = float(stressed["property_value"]) * 0.80
            recompute_lvr_driven_policy_vars(stressed)
        stressed["credit_score"] = max(300, int(stressed["credit_score"]) - 50)
        df_s = pd.DataFrame([stressed])
        df_s = transform_fn(df_s)
        prob = float(model.predict_proba(df_s[feature_cols])[0][1])
        scenarios["combined_stress"] = {
            "probability": round(prob, 4),
            "decision": "approved" if prob >= threshold else "denied",
            "change": round(prob - base_prob, 4),
        }
    except Exception:
        logger.warning("Stress test computation failed", exc_info=True)
        return {
            "base_probability": None,
            "scenarios": {},
        }

    return {
        "base_probability": round(base_prob, 4) if base_prob is not None else None,
        "scenarios": scenarios,
    }
