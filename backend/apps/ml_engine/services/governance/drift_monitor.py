"""Batch drift monitoring: PSI, CSI (Characteristic Stability Index), and KS-test.

Compares feature distributions between training data and recent predictions.

PSI measures overall score distribution shift.
CSI applies the same formula per-feature to pinpoint which inputs are drifting.
KS-test provides a distribution-free statistical significance check.

The industry-standard PSI thresholds (0.10 / 0.25) have no statistical
foundation — they are arbitrary convention. We supplement with KS-test
(p-value based) for statistically grounded drift detection.
"""

import logging
from datetime import timedelta

import joblib
import numpy as np
from django.utils import timezone
from scipy.stats import ks_2samp

logger = logging.getLogger(__name__)

# PSI threshold provenance (important for regulatory defensibility):
# The industry-standard thresholds (0.10 / 0.25) have NO statistical
# foundation — they are arbitrary industry convention.
# For statistically grounded thresholds, supplement with KS-test (p-value based).
PSI_STABLE = 0.10  # Heuristic: no significant shift
PSI_INVESTIGATE = 0.25  # Heuristic: moderate shift, investigate
# CSI uses the same thresholds applied per-feature
CSI_STABLE = 0.10
CSI_INVESTIGATE = 0.20  # Stricter per-feature threshold


def compute_psi(expected, actual, bins=10):
    """PSI between two distributions. Returns float."""
    expected = np.array(expected, dtype=float)
    actual = np.array(actual, dtype=float)

    if len(expected) == 0 or len(actual) == 0:
        return 0.0

    # Create bins from expected distribution
    breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)

    if len(breakpoints) < 2:
        return 0.0

    # Count proportions in each bin (canonical PSI — no re-normalisation)
    eps = 1e-8  # Avoid log(0); small enough not to distort near-identical distributions
    expected_counts = np.histogram(expected, bins=breakpoints)[0]
    actual_counts = np.histogram(actual, bins=breakpoints)[0]

    expected_pct = expected_counts / len(expected)
    actual_pct = actual_counts / len(actual)

    # Replace zeros only (avoid log(0)); do NOT re-normalise after substitution
    # so that the sum of percentages is preserved and PSI stays at 0.0 for
    # identical distributions.
    expected_pct = np.where(expected_pct == 0, eps, expected_pct)
    actual_pct = np.where(actual_pct == 0, eps, actual_pct)

    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))

    return round(float(psi), 6)


# ORM field → reference-distribution key mapping for on-demand drift.
_ON_DEMAND_FIELD_MAP = {
    "annual_income": "annual_income",
    "credit_score": "credit_score",
    "loan_amount": "loan_amount",
    "loan_term_months": "loan_term_months",
    "debt_to_income": "debt_to_income",
    "employment_length": "employment_length",
    "has_cosigner": "has_cosigner",
    "property_value": "property_value",
    "deposit_amount": "deposit_amount",
    "monthly_expenses": "monthly_expenses",
    "existing_credit_card_limit": "existing_credit_card_limit",
    "number_of_dependants": "number_of_dependants",
    "has_hecs": "has_hecs",
    "has_bankruptcy": "has_bankruptcy",
}


def _psi_from_histogram(hist_counts, hist_edges, actual_vals):
    """Canonical histogram-bin PSI used by the on-demand /drift/ endpoint.

    Uses the same approach as compute_psi: normalise to proportions, then
    replace ONLY zero bins with eps (1e-8) — no renormalisation after
    substitution, so the sum of percentages is preserved and PSI stays at
    0.0 for identical distributions.  The previous implementation added eps
    to EVERY bin and used a much larger eps (1e-4), causing the on-demand
    endpoint to report systematically different PSI values than the weekly
    DriftReport path for the same data.
    """
    bin_edges = np.array(hist_edges)
    expected_counts = np.array(hist_counts, dtype=float)
    actual_counts = np.histogram(actual_vals, bins=bin_edges)[0].astype(float)
    eps = 1e-8  # Match compute_psi — small enough not to distort near-identical distributions
    expected_pct = expected_counts / expected_counts.sum()
    actual_pct = actual_counts / actual_counts.sum()
    # Replace zeros only (avoid log(0)); do NOT re-normalise after substitution
    expected_pct = np.where(expected_pct == 0, eps, expected_pct)
    actual_pct = np.where(actual_pct == 0, eps, actual_pct)
    psi_value = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))
    if psi_value < PSI_STABLE:
        psi_status = "stable"
    elif psi_value < PSI_INVESTIGATE:
        psi_status = "moderate_shift"
    else:
        psi_status = "significant_shift"
    return {"psi": round(psi_value, 4), "status": psi_status}


def compute_on_demand_feature_psi(model_version, days=30):
    """On-demand per-feature PSI for recent applications vs the model's
    stored reference distribution. Single source of truth for the
    ModelDriftView endpoint — mirrors the weekly DriftReport binning."""
    from apps.loans.models import LoanApplication
    from apps.ml_engine.services.scoring.predictor import ModelPredictor

    predictor = ModelPredictor(model_version=model_version)
    ref_dist = predictor.reference_distribution
    if not ref_dist:
        return {"error": "no_reference_distribution"}

    cutoff = timezone.now() - timedelta(days=days)
    recent_apps = LoanApplication.objects.filter(created_at__gte=cutoff)
    app_count = recent_apps.count()
    if app_count < 20:
        return {"insufficient_data": True, "application_count": app_count, "days": days}

    numeric_cols = predictor.numeric_cols or list(ref_dist.keys())
    feature_psi, overall_status = {}, "stable"
    for col in numeric_cols:
        ref = ref_dist.get(col)
        if not isinstance(ref, dict):
            continue
        hist_counts, hist_edges = ref.get("histogram_counts", []), ref.get("histogram_edges", [])
        db_field = _ON_DEMAND_FIELD_MAP.get(col, col)
        try:
            actual_vals = np.array(list(recent_apps.values_list(db_field, flat=True)), dtype=float)
            actual_vals = actual_vals[np.isfinite(actual_vals)]
        except (ValueError, TypeError):
            continue
        if len(actual_vals) < 10:
            continue
        if hist_counts and hist_edges and len(hist_edges) >= 3:
            result = _psi_from_histogram(hist_counts, hist_edges, actual_vals)
        else:
            from apps.ml_engine.services.metrics import MetricsService

            percentiles = ref.get("percentiles", [])
            if not percentiles:
                continue
            result = MetricsService().compute_psi(np.array(percentiles), actual_vals)
        feature_psi[col] = {
            "psi": result["psi"],
            "status": result["status"],
            "training_mean": round(ref.get("mean", 0), 2),
            "training_std": round(ref.get("std", 0), 2),
            "current_mean": round(float(np.mean(actual_vals)), 2),
            "current_std": round(float(np.std(actual_vals)), 2),
        }
        if result["status"] == "significant_shift":
            overall_status = "significant_shift"
        elif result["status"] == "moderate_shift" and overall_status == "stable":
            overall_status = "moderate_shift"
    return {
        "model_version": str(model_version.id),
        "days_analysed": days,
        "application_count": app_count,
        "overall_status": overall_status,
        "feature_psi": feature_psi,
    }


def compute_csi(expected_features: dict, actual_features: dict, bins: int = 10) -> dict:
    """Per-feature PSI (Characteristic Stability Index). Returns {feature: {csi, status}}."""
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
    """KS two-sample test. Returns {ks_statistic, p_value, significant}."""
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
    """Full drift report (PSI + CSI + KS) for recent predictions vs training reference."""
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
    from apps.ml_engine.services.scoring.predictor import _validate_model_path

    bundle_path = model_version.file_path
    try:
        validated_path = _validate_model_path(bundle_path)
    except (ValueError, FileNotFoundError) as e:
        logger.error("Model bundle validation failed: %s", e)
        return None

    try:
        bundle = joblib.load(validated_path)
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

    # Determine alert level — use per-model thresholds from retraining_policy
    # if available, otherwise fall back to module-level defaults.
    policy = getattr(model_version, "retraining_policy", None) or {}
    psi_stable = policy.get("psi_stable", PSI_STABLE)
    psi_investigate = policy.get("psi_investigate", PSI_INVESTIGATE)

    if max_psi >= psi_investigate:
        alert_level = "significant"
        drift_detected = True
    elif max_psi >= psi_stable:
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
