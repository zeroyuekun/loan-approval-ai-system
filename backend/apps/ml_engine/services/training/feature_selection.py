"""Weight of Evidence (WOE) and Information Value (IV) feature selection.

Industry-standard credit scoring feature selection method.
IV thresholds (standard):
  < 0.02: Not useful — exclude
  0.02-0.10: Weak predictor
  0.10-0.30: Medium predictor
  0.30-0.50: Strong predictor
  > 0.50: Suspicious — possible data leakage
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_woe_iv(df, feature, target, bins=10):
    """Compute WOE and IV for a single feature.

    Args:
        df: DataFrame with feature and target columns
        feature: column name
        target: binary target column name (0/1)
        bins: number of bins for continuous features

    Returns:
        dict with 'iv', 'woe_table' (DataFrame), 'feature'
    """
    data = df[[feature, target]].copy().dropna()

    if data[feature].nunique() <= bins:
        # Categorical or low-cardinality: use actual values
        data["bin"] = data[feature]
    else:
        # Continuous: equal-frequency binning
        try:
            data["bin"] = pd.qcut(data[feature], q=bins, duplicates="drop")
        except ValueError:
            data["bin"] = pd.cut(data[feature], bins=min(bins, data[feature].nunique()), duplicates="drop")

    grouped = data.groupby("bin", observed=True)[target].agg(["count", "sum"])
    grouped.columns = ["total", "events"]
    grouped["non_events"] = grouped["total"] - grouped["events"]

    total_events = grouped["events"].sum()
    total_non_events = grouped["non_events"].sum()

    if total_events == 0 or total_non_events == 0:
        return {"feature": feature, "iv": 0.0, "woe_table": grouped}

    # Add small epsilon to avoid log(0)
    eps = 0.5
    grouped["dist_events"] = (grouped["events"] + eps) / (total_events + eps * len(grouped))
    grouped["dist_non_events"] = (grouped["non_events"] + eps) / (total_non_events + eps * len(grouped))
    grouped["woe"] = np.log(grouped["dist_non_events"] / grouped["dist_events"])
    grouped["iv_component"] = (grouped["dist_non_events"] - grouped["dist_events"]) * grouped["woe"]

    iv = grouped["iv_component"].sum()

    return {"feature": feature, "iv": round(iv, 4), "woe_table": grouped}


def select_features_by_iv(df, features, target, iv_min=0.02, iv_max=0.5, bins=10, leakage_warn_threshold=0.5):
    """Select features based on Information Value thresholds.

    Args:
        df: DataFrame
        features: list of feature column names
        target: binary target column name
        iv_min: minimum IV to keep (default 0.02)
        iv_max: maximum IV — above this is suspicious leakage (default 0.5)
        bins: number of bins for WOE computation

    Returns:
        dict with 'selected_features', 'excluded_features', 'iv_table'
    """
    results = []
    for feat in features:
        if feat not in df.columns or feat == target:
            continue
        try:
            result = compute_woe_iv(df, feat, target, bins=bins)
            results.append({"feature": feat, "iv": result["iv"]})
        except Exception as e:
            logger.warning("IV computation failed for %s: %s", feat, e)
            results.append({"feature": feat, "iv": 0.0})

    iv_table = pd.DataFrame(results).sort_values("iv", ascending=False)

    selected = iv_table[(iv_table["iv"] >= iv_min) & (iv_table["iv"] <= iv_max)]["feature"].tolist()
    excluded_weak = iv_table[iv_table["iv"] < iv_min]["feature"].tolist()
    excluded_leakage = iv_table[iv_table["iv"] > iv_max]["feature"].tolist()

    # Honest leakage signal at the INDUSTRY-STANDARD threshold (0.5), separate
    # from the (deliberately higher) iv_max used for actual exclusion. These
    # features are KEPT but flagged: IV above the standard "suspiciously strong /
    # possible leakage" line yet at/below iv_max. On synthetic data this is
    # expected for core credit features the generator uses directly — surfacing
    # it keeps the leakage picture honest, rather than letting a rarely-triggered
    # excluded_leakage count imply leakage was screened at 0.5 when iv_max is 1.5.
    elevated_iv = iv_table[(iv_table["iv"] > leakage_warn_threshold) & (iv_table["iv"] <= iv_max)]["feature"].tolist()

    if excluded_weak:
        logger.info("Excluded %d weak features (IV < %.2f): %s", len(excluded_weak), iv_min, excluded_weak[:5])
    if excluded_leakage:
        logger.warning(
            "Excluded %d suspicious features (IV > %.2f, possible leakage): %s",
            len(excluded_leakage),
            iv_max,
            excluded_leakage,
        )

    if elevated_iv:
        logger.info(
            "Elevated-IV features KEPT but flagged (IV in (%.2f, %.2f]): %s",
            leakage_warn_threshold,
            iv_max,
            elevated_iv,
        )

    logger.info("IV feature selection: %d/%d features selected", len(selected), len(features))

    return {
        "selected_features": selected,
        "excluded_weak": excluded_weak,
        "excluded_leakage": excluded_leakage,
        "elevated_iv": elevated_iv,
        "iv_table": iv_table,
    }
