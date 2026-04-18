"""Runtime loan-prediction orchestrator.

`ModelPredictor` loads the active `ModelVersion` artefacts for the resolved segment,
runs policy-overlay pre-checks in shadow mode, scores with the XGBoost pipeline,
decorates the response with SHAP explanations, drift snapshots, stress-test deltas,
conformal intervals, and counterfactual suggestions, and records the outcome.
"""

import logging
import time

import numpy as np
import pandas as pd
from prometheus_client import Counter, Histogram

from apps.ml_engine.services.consistency import DataConsistencyChecker
from apps.ml_engine.services.decision_assembly import (
    assemble_decision as _assemble_decision_helper,
)
from apps.ml_engine.services.feature_prep import (
    FEATURE_BOUNDS,  # noqa: F401 — re-exported for open_banking_service + tests
)
from apps.ml_engine.services.feature_prep import (
    safe_get_state as _safe_get_state_helper,
)
from apps.ml_engine.services.feature_prep import (
    validate_input as _validate_input_helper,
)
from apps.ml_engine.services.policy_overlay import (
    apply_policy_overlay as _apply_policy_overlay_helper,
)
from apps.ml_engine.services.prediction_cache import (  # noqa: F401 — re-export for external patches
    _CACHE_TTL_SECONDS,
    _MAX_CACHE_ENTRIES,
    _cache_lock,
    _load_bundle,
    _model_cache,
    _validate_model_path,
    _verify_model_hash,
    clear_model_cache,
)
from apps.ml_engine.services.prediction_diagnostics import (
    check_feature_drift as _check_feature_drift_helper,
)
from apps.ml_engine.services.prediction_diagnostics import (
    run_stress_scenarios as _run_stress_scenarios_helper,
)
from apps.ml_engine.services.prediction_explanations import (
    compute_conformal_interval as _compute_conformal_interval_helper,
)
from apps.ml_engine.services.prediction_explanations import (
    search_counterfactuals as _search_counterfactuals_helper,
)
from apps.ml_engine.services.prediction_features import (
    build_prediction_features as _build_prediction_features_helper,
)
from apps.ml_engine.services.prediction_features import (
    derive_underwriter_features as _derive_underwriter_features_helper,
)
from apps.ml_engine.services.shadow_scoring import (
    score_challengers_shadow as _score_challengers_shadow_helper,
)
from apps.ml_engine.services.shap_attribution import (
    compute_shap_attribution as _compute_shap_attribution_helper,
)

ml_predictions_total = Counter(
    "ml_predictions_total",
    "Total ML predictions",
    ["decision", "model_version"],
)
ml_prediction_latency_seconds = Histogram(
    "ml_prediction_latency_seconds",
    "ML prediction computation time",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
ml_prediction_confidence = Histogram(
    "ml_prediction_confidence",
    "Prediction confidence distribution",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
ml_drift_warnings_total = Counter(
    "ml_drift_warnings_total",
    "Predictions with drift warnings",
)

logger = logging.getLogger(__name__)


def compute_risk_grade(probability):
    """Map approval probability to internal risk grade.

    Grades reflect probability of default (1 - approval probability).
    These are INTERNAL grades for portfolio segmentation, not comparable
    to external agency ratings (S&P, Moody's). External AAA implies PD
    ~0.01%; our Grade 1 (best) covers PD < 0.5% — a much wider band
    appropriate for consumer lending risk stratification per APS 220.
    """
    pd = 1.0 - probability  # probability of default
    if pd < 0.005:
        return "AAA"
    elif pd < 0.01:
        return "AA"
    elif pd < 0.03:
        return "A"
    elif pd < 0.07:
        return "BBB"
    elif pd < 0.15:
        return "BB"
    elif pd < 0.30:
        return "B"
    else:
        return "CCC"


class ModelPredictor:
    """Loads the active model and runs predictions."""

    CATEGORICAL_COLS = [
        "purpose",
        "home_ownership",
        "employment_type",
        "applicant_type",
        "state",
        "savings_trend_3m",
        "industry_risk_tier",
        # sa3_region excluded: ~50 categories causes OHE explosion
        "industry_anzsic",
    ]

    def __init__(self, model_version=None, *, segment=None):
        if model_version is not None:
            self.model_version = model_version
        else:
            from apps.ml_engine.services.model_selector import select_model_version
            from apps.ml_engine.services.segmentation import SEGMENT_UNIFIED

            self.model_version = select_model_version(segment=segment or SEGMENT_UNIFIED)

        bundle = _load_bundle(self.model_version)
        self.model = bundle["model"]
        self.scaler = bundle["scaler"]
        self.feature_cols = bundle["feature_cols"]
        # Support both old (label_encoders) and new (one-hot) bundles
        self.label_encoders = bundle.get("label_encoders")
        self.categorical_cols = bundle.get("categorical_cols", self.CATEGORICAL_COLS)
        self.numeric_cols = bundle.get("numeric_cols", [])
        self.reference_distribution = bundle.get("reference_distribution", {})
        from apps.ml_engine.services.feature_engineering import DEFAULT_IMPUTATION_VALUES

        self.imputation_values = bundle.get("imputation_values", DEFAULT_IMPUTATION_VALUES)
        self.feature_bounds = bundle.get("feature_bounds", {})
        self.group_thresholds = bundle.get("group_thresholds", {})
        self.conformal_scores = bundle.get("conformal_scores", np.array([]))
        self.consistency_checker = DataConsistencyChecker()
        from .metrics import MetricsService

        self._metrics_service = MetricsService()

    @classmethod
    def for_application(cls, application):
        """Create a predictor routed to the application's product segment.

        Derives the segment from application.purpose / home_ownership, then
        calls `select_model_version` which falls back to the unified model
        if no active segment-specific model is available. This is the
        preferred entry point for scoring tasks — constructor access
        without a segment defaults to unified.
        """
        from apps.ml_engine.services.segmentation import derive_segment

        segment = derive_segment(application)
        return cls(segment=segment)

    @staticmethod
    def _add_derived_features(df):
        """Add engineered features matching those computed during training.

        Delegates to the shared feature_engineering module (single source
        of truth) to eliminate training/serving skew.
        """
        from apps.ml_engine.services.feature_engineering import compute_derived_features

        return compute_derived_features(df)

    @staticmethod
    def _safe_get_state(application):
        """Safely get state from application, handling unmigrated databases."""
        return _safe_get_state_helper(application)

    def _validate_input(self, features: dict):
        """Validate feature values against hard + user bounds. See `feature_prep`."""
        _validate_input_helper(features, FEATURE_BOUNDS, user_bounds=self.feature_bounds)

    def _transform(self, df):
        """Transform a DataFrame using the saved preprocessing artifacts.

        Supports both legacy (LabelEncoder) and new (one-hot) bundles.
        """
        df = df.copy()

        # Add derived features to match training pipeline
        df = self._add_derived_features(df)

        if self.label_encoders:
            # Legacy path: LabelEncoder-based bundles
            for col, le in self.label_encoders.items():
                if col in df.columns:
                    known_classes = set(le.classes_)
                    df[col] = df[col].apply(lambda x, kc=known_classes, le_=le: x if x in kc else le_.classes_[0])
                    df[col] = le.transform(df[col].astype(str))
            df[self.feature_cols] = self.scaler.transform(df[self.feature_cols])
        else:
            # New path: one-hot encoding. A single inference row only emits the
            # dummy columns matching that row's actual values, so almost every
            # other dummy column will be 'missing' and must be padded to 0 —
            # this is normal one-hot reindexing, NOT an unknown-category event.
            #
            # Detect *truly* unknown categorical values (a value at inference
            # whose dummy column never existed at training time) before encoding.
            unknown_values: dict[str, list[str]] = {}
            for col in self.categorical_cols:
                if col not in df.columns:
                    continue
                for raw_val in df[col].dropna().unique():
                    expected_dummy = f"{col}_{raw_val}"
                    if expected_dummy not in self.feature_cols:
                        unknown_values.setdefault(col, []).append(str(raw_val))

            if unknown_values:
                logger.warning(
                    "Unknown categorical values at inference — defaulting to all-zero encoding: %s",
                    unknown_values,
                )

            df = pd.get_dummies(df, columns=self.categorical_cols, dtype=float)

            # Align to training columns: pad missing one-hot columns with 0.
            for col in self.feature_cols:
                if col not in df.columns:
                    df[col] = 0.0

            df[self.feature_cols] = self.scaler.transform(df[self.feature_cols])

        return df

    def predict(self, application):
        """
        Predict approval for a LoanApplication instance.
        Returns dict with prediction, probability, and feature_importances.
        """
        start_time = time.time()

        features = _build_prediction_features_helper(
            application,
            safe_get_state_fn=self._safe_get_state,
            imputation_values=self.imputation_values,
        )
        _derive_underwriter_features_helper(features)

        # Validate inputs
        self._validate_input(features)

        # Cross-validate data consistency
        consistency = self.consistency_checker.check_all(features)
        if not consistency["consistent"]:
            error_msgs = "; ".join(e["message"] for e in consistency["errors"])
            raise ValueError(f"Data consistency check failed: {error_msgs}")

        df = pd.DataFrame([features])
        features_df = df.copy()  # preserve raw features for counterfactual generation

        # Transform using saved preprocessing artifacts
        df = self._transform(df)

        # Predict (probability-based — label derived from threshold comparison)
        probabilities = self.model.predict_proba(df[self.feature_cols])[0]

        attribution = _compute_shap_attribution_helper(
            model=self.model,
            df=df,
            feature_cols=self.feature_cols,
            positive_probability=float(probabilities[1]),
        )
        importances = attribution["feature_importances"]
        shap_values_dict = attribution["shap_values"]
        shap_available = attribution["shap_available"]

        processing_time = int((time.time() - start_time) * 1000)

        # Per-application drift flags: check if key features are far outside
        # the training distribution (APRA CPG 235 ongoing monitoring)
        drift_warnings = self._check_feature_drift(features)

        decision = _assemble_decision_helper(
            probability_positive=float(probabilities[1]),
            model_version=self.model_version,
            group_thresholds=self.group_thresholds,
            employment_type=features.get("employment_type", ""),
            drift_warnings=drift_warnings,
            segment=features.get("purpose", "personal"),
        )
        probability = decision["probability"]
        threshold = decision["threshold"]
        effective_threshold = decision["effective_threshold"]
        prediction_label = decision["prediction_label"]
        requires_human_review = decision["requires_human_review"]
        pricing_payload = decision["pricing_payload"]

        # Expected Loss (EL = PD x LGD x EAD) — Basel III / APRA APS 113
        property_val = float(features.get("property_value") or 0)
        lvr = (float(features.get("loan_amount", 0)) / property_val) if property_val > 0 else 0.0
        expected_loss = self._metrics_service.compute_expected_loss(
            pd_value=1.0 - probability,  # PD = probability of denial/default
            loan_amount=features.get("loan_amount", 0),
            purpose=features.get("purpose", "personal"),
            lvr=lvr,
            credit_score=features.get("credit_score", 864),
        )

        stress_results = self._stress_test(features, threshold)
        confidence_interval = self._conformal_interval(probability, alpha=0.05)

        # === Credit policy overlay (D3) + referral audit (D6) ======
        prediction_label, requires_human_review, policy_payload = _apply_policy_overlay_helper(
            application=application,
            model_version=self.model_version,
            prediction_label=prediction_label,
            requires_human_review=requires_human_review,
        )

        result = {
            "prediction": prediction_label,
            "probability": probability,
            "threshold_used": threshold,
            "effective_threshold": effective_threshold,
            "requires_human_review": requires_human_review,
            "feature_importances": importances,
            "shap_values": shap_values_dict,
            "shap_available": shap_available,
            "shap_model_note": "Feature attributions computed on base model before probability calibration",
            "processing_time_ms": processing_time,
            "model_version": str(self.model_version.id),
            "consistency_warnings": consistency["warnings"],
            "drift_warnings": drift_warnings,
            "expected_loss": expected_loss,
            "stress_test": stress_results,
            "confidence_interval": confidence_interval,
            "policy_decision": policy_payload,
            "pricing_tier": pricing_payload,
            # Raw (pre-transform) features for downstream counterfactual generation
            "_features_df": features_df,
        }

        # Generate counterfactual explanations for denied applications
        if result["prediction"] == "denied":
            try:
                model_bundle = {
                    "model": self.model,
                    "threshold": threshold,
                }
                result["counterfactuals"] = self._generate_counterfactuals(
                    features_df, result["feature_importances"], model_bundle
                )
            except Exception as e:
                logger.warning("Counterfactual generation failed: %s", e)
                result["counterfactuals"] = []
        else:
            result["counterfactuals"] = []

        # Emit Prometheus metrics for ML observability
        try:
            ml_predictions_total.labels(
                decision=result["prediction"],
                model_version=str(self.model_version.id)[:8],
            ).inc()
            ml_prediction_latency_seconds.observe(result["processing_time_ms"] / 1000.0)
            ml_prediction_confidence.observe(result["probability"])
            if result.get("drift_warnings"):
                ml_drift_warnings_total.inc()
        except Exception as e:
            logger.debug("Prometheus metrics emission failed (non-blocking): %s", e)

        # === Champion/Challenger Shadow Scoring ===
        def _score_with_challenger(challenger_mv, raw_df):
            challenger_predictor = ModelPredictor(model_version=challenger_mv)
            transformed = challenger_predictor._transform(raw_df)
            prob = float(
                challenger_predictor.model.predict_proba(transformed[challenger_predictor.feature_cols])[:, 1][0]
            )
            label = "approved" if prob >= (challenger_mv.optimal_threshold or 0.5) else "denied"
            return prob, label

        _score_challengers_shadow_helper(
            application=application,
            champion_version=self.model_version,
            champion_probability=probability,
            champion_prediction_label=prediction_label,
            features_df=features_df,
            score_fn=_score_with_challenger,
        )

        return result

    def _check_feature_drift(self, features):
        """Per-application drift check. See `prediction_diagnostics.check_feature_drift`."""
        return _check_feature_drift_helper(features, self.reference_distribution)

    def _stress_test(self, features, threshold):
        """APS-110 stress scenarios. See `prediction_diagnostics.run_stress_scenarios`."""
        return _run_stress_scenarios_helper(
            features,
            threshold,
            model=self.model,
            transform_fn=self._transform,
            feature_cols=self.feature_cols,
        )

    def _conformal_interval(self, probability, alpha=0.05):
        """Split-conformal interval. See `prediction_explanations.compute_conformal_interval`."""
        return _compute_conformal_interval_helper(probability, self.conformal_scores, alpha=alpha)

    def _generate_counterfactuals(self, features_df, feature_importances, model_bundle):
        """Binary-search counterfactuals. See `prediction_explanations.search_counterfactuals`."""
        return _search_counterfactuals_helper(
            features_df,
            feature_importances,
            model_bundle,
            transform_fn=self._transform,
            feature_cols=self.feature_cols,
        )
