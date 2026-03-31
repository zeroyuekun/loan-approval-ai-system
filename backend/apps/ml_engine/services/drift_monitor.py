"""Batch drift monitoring: PSI, CSI (Characteristic Stability Index), and KS-test.

Compares feature distributions between training data and recent predictions.

PSI measures overall score distribution shift.
CSI applies the same formula per-feature to pinpoint which inputs are drifting.
KS-test provides a distribution-free statistical significance check.

References:
  - Fiddler AI: "Measuring Data Drift with PSI"
  - Towards Data Science: "Stop Retraining Blindly: Use PSI"
  - Lewis (1994): Original PSI threshold proposal
  - Yurdakul (2020): "Statistical Properties of PSI", J. Risk Model Validation
  - Siddiqi (2023): Population Resemblance Statistic, arXiv:2307.11878
"""

import logging
import os
from datetime import timedelta

import joblib
import numpy as np
from django.utils import timezone
from scipy.stats import ks_2samp

logger = logging.getLogger(__name__)

# PSI threshold provenance (important for regulatory defensibility):
# The industry-standard thresholds (0.10 / 0.25) originate from Lewis (1994)
# and have NO statistical foundation — they are arbitrary industry convention.
# See: Yurdakul (2020) "Statistical Properties of PSI", J. Risk Model Validation.
# For statistically grounded thresholds, supplement with KS-test (p-value based)
# or the Population Resemblance Statistic (Siddiqi, 2023, arXiv:2307.11878).
PSI_STABLE = 0.10  # Heuristic: no significant shift
PSI_INVESTIGATE = 0.25  # Heuristic: moderate shift, investigate
# CSI uses the same thresholds applied per-feature
CSI_STABLE = 0.10
CSI_INVESTIGATE = 0.20  # Stricter per-feature threshold


def compute_psi(expected, actual, bins=10):
    """Compute Population Stability Index between two distributions.

    Args:
        expected: array-like, reference distribution (training data)
        actual: array-like, current distribution (recent predictions)
        bins: number of bins

    Returns:
        float: PSI value
    """
    expected = np.array(expected, dtype=float)
    actual = np.array(actual, dtype=float)

    if len(expected) == 0 or len(actual) == 0:
        return 0.0

    # Create bins from expected distribution
    breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)

    if len(breakpoints) < 2:
        return 0.0

    # Count proportions in each bin
    eps = 1e-4  # Avoid log(0)
    expected_counts = np.histogram(expected, bins=breakpoints)[0]
    actual_counts = np.histogram(actual, bins=breakpoints)[0]

    expected_pct = expected_counts / len(expected) + eps
    actual_pct = actual_counts / len(actual) + eps

    # Normalize
    expected_pct = expected_pct / expected_pct.sum()
    actual_pct = actual_pct / actual_pct.sum()

    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))

    return round(float(psi), 6)


def compute_csi(expected_features: dict, actual_features: dict, bins: int = 10) -> dict:
    """Compute Characteristic Stability Index per feature.

    CSI applies the same PSI formula to individual features (not scores).
    Identifies which specific features are drifting.

    Args:
        expected_features: dict mapping feature_name → array-like of reference values
        actual_features: dict mapping feature_name → array-like of current values
        bins: number of bins for PSI computation

    Returns:
        dict mapping feature_name → {'csi': float, 'status': str}
        where status is 'stable', 'investigate', or 'action_required'
    """
    results = {}
    common_keys = set(expected_features.keys()) & set(actual_features.keys())

    for feature in sorted(common_keys):
        expected = np.array(expected_features[feature], dtype=float)
        actual = np.array(actual_features[feature], dtype=float)

        # Guard against empty or single-element arrays
        if len(expected) < 2 or len(actual) < 2:
            results[feature] = {"csi": 0.0, "status": "stable"}
            continue

        csi_value = compute_psi(expected, actual, bins=bins)

        if csi_value >= CSI_INVESTIGATE:
            status = "action_required"
        elif csi_value >= CSI_STABLE:
            status = "investigate"
        else:
            status = "stable"

        results[feature] = {"csi": csi_value, "status": status}

    return results


def compute_ks_test(expected, actual):
    """Kolmogorov-Smirnov test as supplement to PSI.

    Unlike PSI (which is bin-dependent), KS-test is distribution-free
    and provides a proper p-value for statistical significance.

    Args:
        expected: array-like, reference distribution
        actual: array-like, current distribution

    Returns:
        dict with 'ks_statistic' (float), 'p_value' (float), 'significant' (bool)
    """
    expected = np.array(expected, dtype=float)
    actual = np.array(actual, dtype=float)

    if len(expected) < 2 or len(actual) < 2:
        return {"ks_statistic": 0.0, "p_value": 1.0, "significant": False}

    stat, p_value = ks_2samp(expected, actual)

    return {
        "ks_statistic": round(float(stat), 6),
        "p_value": round(float(p_value), 6),
        "significant": p_value < 0.05,
    }


def compute_batch_drift_report(model_version, days=7):
    """Compute PSI for all features over the last N days.

    Args:
        model_version: ModelVersion instance
        days: number of days to look back

    Returns:
        dict with per-feature PSI, overall assessment, and label drift
    """
    from apps.ml_engine.models import DriftReport, PredictionLog

    cutoff = timezone.now() - timedelta(days=days)

    # Get recent prediction probabilities for label drift
    recent_probs = list(
        PredictionLog.objects.filter(
            model_version=model_version,
            created_at__gte=cutoff,
        ).values_list("probability", flat=True)
    )

    if not recent_probs or len(recent_probs) < 10:
        logger.info("Not enough recent predictions (%d) for drift analysis", len(recent_probs))
        return None

    # Load training reference distribution from model bundle
    bundle_path = model_version.file_path
    if not os.path.exists(bundle_path):
        logger.error("Model bundle not found: %s", bundle_path)
        return None

    try:
        bundle = joblib.load(bundle_path)
        reference_distribution = bundle.get("reference_distribution", {})
    except Exception as e:
        logger.error("Failed to load model bundle for drift check: %s", e)
        return None

    if not reference_distribution:
        logger.warning("No reference distribution in model bundle -- skipping drift check")
        return None

    # Compute per-feature PSI
    psi_results = {}
    max_psi = 0.0

    # Label drift: compare approval rate
    recent_approval_rate = sum(1 for p in recent_probs if p >= (model_version.optimal_threshold or 0.5)) / len(
        recent_probs
    )
    training_approval_rate = reference_distribution.get("approval_rate", 0.5)
    label_drift = abs(recent_approval_rate - training_approval_rate)

    # Compute PSI for prediction probability distribution
    ks_results = {}
    if "probability_distribution" in reference_distribution:
        prob_psi = compute_psi(reference_distribution["probability_distribution"], recent_probs)
        psi_results["prediction_probability"] = prob_psi
        max_psi = max(max_psi, prob_psi)
        ks_results["prediction_probability"] = compute_ks_test(
            reference_distribution["probability_distribution"], recent_probs
        )

    # Compute CSI on per-feature distributions if available
    csi_results = {}
    ref_features = reference_distribution.get("feature_distributions", {})
    actual_features = reference_distribution.get("_actual_feature_cache", {})
    # If feature distributions are available in the reference, compute CSI
    if ref_features:
        # Build actual feature dict from recent prediction logs if not cached
        if not actual_features:
            recent_logs = PredictionLog.objects.filter(
                model_version=model_version,
                created_at__gte=cutoff,
            ).values_list("input_data", flat=True)
            actual_features = {}
            for input_data in recent_logs:
                if isinstance(input_data, dict):
                    for key, val in input_data.items():
                        if key in ref_features:
                            actual_features.setdefault(key, []).append(val)

        if actual_features:
            csi_results = compute_csi(ref_features, actual_features)
            # Also compute KS-test per feature
            for feature in sorted(set(ref_features) & set(actual_features)):
                ks_results[feature] = compute_ks_test(ref_features[feature], actual_features[feature])

    # Merge CSI and KS data into psi_per_feature for storage
    for feature, csi_data in csi_results.items():
        if feature not in psi_results:
            psi_results[feature] = csi_data["csi"]
        psi_results[f"{feature}_csi"] = csi_data
    for feature, ks_data in ks_results.items():
        psi_results[f"{feature}_ks"] = ks_data

    # Determine alert level
    if max_psi >= PSI_INVESTIGATE:
        alert_level = "significant"
        drift_detected = True
    elif max_psi >= PSI_STABLE:
        alert_level = "moderate"
        drift_detected = True
    else:
        alert_level = "none"
        drift_detected = False

    # Create DriftReport (period_start/period_end are DateFields)
    report = DriftReport.objects.create(
        model_version=model_version,
        report_date=timezone.now().date(),
        period_start=cutoff.date(),
        period_end=timezone.now().date(),
        num_predictions=len(recent_probs),
        psi_score=max_psi,
        psi_per_feature=psi_results,
        mean_probability=float(np.mean(recent_probs)),
        std_probability=float(np.std(recent_probs)),
        approval_rate=recent_approval_rate,
        drift_detected=drift_detected,
        alert_level=alert_level,
    )

    if drift_detected:
        logger.warning(
            "Drift detected for model %s: PSI=%.4f, alert_level=%s, label_drift=%.4f",
            model_version.version,
            max_psi,
            alert_level,
            label_drift,
        )
    else:
        logger.info("No drift detected for model %s: PSI=%.4f", model_version.version, max_psi)

    return {
        "report_id": report.pk,
        "psi_score": max_psi,
        "psi_per_feature": psi_results,
        "csi_per_feature": csi_results,
        "ks_tests": ks_results,
        "drift_detected": drift_detected,
        "alert_level": alert_level,
        "label_drift": label_drift,
        "num_predictions": len(recent_probs),
    }
