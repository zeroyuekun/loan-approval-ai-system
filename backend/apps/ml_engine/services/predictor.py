"""Runtime loan-prediction orchestrator.

`ModelPredictor` loads the active `ModelVersion` artefacts for the resolved segment,
runs policy-overlay pre-checks in shadow mode, scores with the XGBoost pipeline,
decorates the response with SHAP explanations, drift snapshots, stress-test deltas,
conformal intervals, and counterfactual suggestions, and records the outcome.
"""

import logging
import math
import time

import numpy as np
import pandas as pd
import shap
from django.conf import settings
from prometheus_client import Counter, Histogram

from apps.ml_engine.services.consistency import DataConsistencyChecker
from apps.ml_engine.services.feature_prep import (
    safe_get_state as _safe_get_state_helper,
    validate_input as _validate_input_helper,
)
from apps.ml_engine.services.policy_recompute import (
    recompute_lvr_driven_policy_vars as _recompute_lvr_driven_policy_vars,
)
from apps.ml_engine.services.prediction_diagnostics import (
    check_feature_drift as _check_feature_drift_helper,
    run_stress_scenarios as _run_stress_scenarios_helper,
)
from apps.ml_engine.services.prediction_explanations import (
    compute_conformal_interval as _compute_conformal_interval_helper,
    search_counterfactuals as _search_counterfactuals_helper,
)
from apps.ml_engine.services.prediction_features import (
    build_prediction_features as _build_prediction_features_helper,
    derive_underwriter_features as _derive_underwriter_features_helper,
)
from apps.ml_engine.services.shadow_scoring import (
    score_challengers_shadow as _score_challengers_shadow_helper,
)
# Re-export cache helpers so external callers and tests that patch
# `predictor._validate_model_path`, `predictor._verify_model_hash`,
# `predictor._load_bundle`, `predictor._model_cache`, etc. keep working after
# the Arm C Phase 1 split. These names are mutable-object bindings; patches
# applied to the `predictor` module propagate because internal callers of the
# loader look up these names on `prediction_cache`, and the re-exports share
# identity with that module's bindings at import time.
from apps.ml_engine.services.prediction_cache import (  # noqa: F401 — re-export
    _MAX_CACHE_ENTRIES,
    _CACHE_TTL_SECONDS,
    _cache_lock,
    _load_bundle,
    _model_cache,
    _validate_model_path,
    _verify_model_hash,
    clear_model_cache,
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


# Bounds for input validation: (min, max) inclusive.
FEATURE_BOUNDS = {
    "annual_income": (0, 10_000_000),
    "credit_score": (0, 1200),  # Equifax Australia scale
    "loan_amount": (0, 5_000_000),  # Aligned with LoanApplication.loan_amount MaxValueValidator
    "loan_term_months": (1, 600),
    "debt_to_income": (0.0, 100.0),
    "employment_length": (0, 60),
    "has_cosigner": (0, 1),
    "property_value": (0, 100_000_000),
    "deposit_amount": (0, 5_000_000),  # Cannot exceed loan amount
    "monthly_expenses": (0, 1_000_000),
    "existing_credit_card_limit": (0, 10_000_000),
    "number_of_dependants": (0, 10),  # Aligned with LoanApplication.number_of_dependants MaxValueValidator
    "has_hecs": (0, 1),
    "has_bankruptcy": (0, 1),
    "num_credit_enquiries_6m": (0, 50),
    "worst_arrears_months": (0, 36),
    "num_defaults_5yr": (0, 20),
    "credit_history_months": (0, 600),
    "total_open_accounts": (0, 50),
    "num_bnpl_accounts": (0, 20),
    "savings_balance": (0, 10_000_000),
    "salary_credit_regularity": (0, 1),
    "num_dishonours_12m": (0, 100),
    "avg_monthly_savings_rate": (-1, 1),
    "days_in_overdraft_12m": (0, 365),
    "rba_cash_rate": (0, 20),
    "unemployment_rate": (0, 30),
    "property_growth_12m": (-50, 100),
    "consumer_confidence": (0, 200),
    "income_verification_gap": (0, 10),
    "document_consistency_score": (0, 1),
    # CCR features
    "num_late_payments_24m": (0, 50),
    "worst_late_payment_days": (0, 90),
    "total_credit_limit": (0, 5_000_000),
    "credit_utilization_pct": (0, 1),
    "num_hardship_flags": (0, 10),
    "months_since_last_default": (0, 999),
    "num_credit_providers": (0, 30),
    # BNPL-specific
    "bnpl_total_limit": (0, 100_000),
    "bnpl_utilization_pct": (0, 1),
    "bnpl_late_payments_12m": (0, 50),
    "bnpl_monthly_commitment": (0, 10_000),
    # CDR/Open Banking transaction features
    "income_source_count": (0, 20),
    "rent_payment_regularity": (0, 1),
    "utility_payment_regularity": (0, 1),
    "essential_to_total_spend": (0, 1),
    "subscription_burden": (0, 1),
    "balance_before_payday": (-10_000, 1_000_000),
    "min_balance_30d": (-10_000, 1_000_000),
    "days_negative_balance_90d": (0, 90),
    # Geographic risk
    "postcode_default_rate": (0, 1),
    # Behavioral features
    "financial_literacy_score": (0.0, 1.0),
    "prepayment_buffer_months": (0, 60),
    "optimism_bias_flag": (0, 1),
    "negative_equity_flag": (0, 1),
    # Underwriter-internal variables exposed as features.
    # effective_loan_amount ceiling must cover max loan_amount (5M) + max
    # LMI premium (3% * 5M = 150k) with headroom, otherwise large high-LVR
    # home loans fail validation before reaching the model.
    "hem_benchmark": (0, 20_000),
    "hem_gap": (-20_000, 20_000),
    "lmi_premium": (0, 200_000),
    "effective_loan_amount": (0, 5_200_000),
}


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

        # Global feature importances
        importances = {}
        if hasattr(self.model, "feature_importances_"):
            for name, imp in zip(self.feature_cols, self.model.feature_importances_, strict=False):
                importances[name] = round(float(imp), 4)

        # Per-prediction SHAP values
        shap_values_dict = {}
        shap_available = False
        try:
            # For calibrated models, extract the underlying estimator for TreeExplainer.
            # _CalibratedModel wraps the fitted tree model with isotonic calibration;
            # SHAP needs the raw tree model, not the wrapper.
            underlying = (
                self.model.get_underlying_estimator() if hasattr(self.model, "get_underlying_estimator") else self.model
            )
            explainer = shap.TreeExplainer(underlying)
            sv = explainer.shap_values(df[self.feature_cols])
            # For binary classification shap_values may return:
            # - list of two arrays (sklearn models, SHAP <0.45)
            # - 3D numpy array shape (n_samples, n_features, 2) (SHAP >=0.45 multi-output)
            # - 2D numpy array shape (n_samples, n_features) (XGBoost log-odds, single output)
            if isinstance(sv, list):
                sv = sv[1]  # positive class
            elif hasattr(sv, "ndim") and sv.ndim == 3:
                sv = sv[:, :, 1]  # positive class from 3D array
            for name, val in zip(self.feature_cols, sv[0], strict=False):
                shap_values_dict[name] = round(float(val), 4)
            shap_available = True

            calibrated_prob = float(probabilities[1])
            if abs(float(np.array(explainer.expected_value).flat[0]) - calibrated_prob) > 0.05:
                # Expected — SHAP runs against the uncalibrated base model so its
                # baseline naturally differs from the calibrated probability.
                # Logged at DEBUG only; not actionable in production.
                logger.debug(
                    "SHAP expected value (%.3f) diverges from calibrated probability (%.3f) — values are from uncalibrated base model",
                    float(np.array(explainer.expected_value).flat[0]),
                    calibrated_prob,
                )
        except Exception:
            logger.warning("SHAP computation failed, returning empty shap_values", exc_info=True)

        processing_time = int((time.time() - start_time) * 1000)

        # Per-application drift flags: check if key features are far outside
        # the training distribution (APRA CPG 235 ongoing monitoring)
        drift_warnings = self._check_feature_drift(features)

        # Use optimal threshold from model version. Falling back to a
        # hardcoded 0.5 can cause disparate-impact issues because the model
        # was calibrated against its learned threshold. Warn loudly instead.
        threshold = self.model_version.optimal_threshold
        if threshold is None:
            threshold = 0.5
            logger.warning(
                "ModelVersion %s has no optimal_threshold set — falling back to 0.5. "
                "This may cause calibration drift and disparate-impact risk. "
                "Re-run validate_model to populate optimal_threshold.",
                self.model_version.id,
            )
        probability = round(float(probabilities[1]), 4)

        # Per-group fairness threshold (EEOC 80% rule compliance)
        effective_threshold = threshold
        employment_type = features.get("employment_type", "")
        if self.group_thresholds and employment_type in self.group_thresholds:
            effective_threshold = self.group_thresholds[employment_type]

        prediction_label = "approved" if probability >= effective_threshold else "denied"

        # Flag borderline cases for human review (use effective_threshold
        # so group-adjusted decisions are consistent with the borderline flag)
        requires_human_review = abs(probability - effective_threshold) <= 0.10

        # Also flag for review if significant feature drift detected
        if any(w.get("severity") == "drift" for w in drift_warnings):
            requires_human_review = True

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

        # Stress testing — 4 adverse scenarios
        stress_results = self._stress_test(features, threshold)

        # Conformal prediction interval (95% coverage)
        confidence_interval = self._conformal_interval(probability, alpha=0.05)

        # === Risk-based pricing tier (D4) ==========================
        # PD = 1 − approval probability. Tier is computed even when the
        # model denies — the tier itself may independently decline
        # regardless of the model's verdict (PD > top cutoff).
        try:
            from apps.ml_engine.services.pricing_engine import get_tier

            pricing_tier = get_tier(pd_score=1.0 - probability, segment=features.get("purpose", "personal"))
            pricing_payload = pricing_tier.to_dict()
            # Pricing-tier decline overrides an otherwise-approved model result.
            if not pricing_tier.approved and prediction_label == "approved":
                logger.info(
                    "Pricing tier decline overrides model approve: PD=%.4f segment=%s",
                    pricing_tier.pd_score,
                    pricing_tier.segment,
                )
                prediction_label = "denied"
        except Exception:
            logger.warning("Pricing tier computation failed", exc_info=True)
            pricing_payload = {"tier": "unavailable", "approved": True}

        # === Credit policy overlay (D3) ============================
        # Evaluate always so shadow-mode logs capture what WOULD have
        # happened under enforce; mode decides whether the verdict is
        # actually applied. Rule evaluation is cheap (<1ms) and pure.
        try:
            from apps.ml_engine.services import credit_policy as _policy

            policy_result = _policy.evaluate(application)
            policy_mode = _policy.current_mode()
            final_prediction = _policy.apply_overlay_to_decision(prediction_label, policy_result, policy_mode)

            if policy_mode == _policy.OVERLAY_MODE_SHADOW and not policy_result.passed:
                # Shadow mode: log what enforce would have done.
                hypothetical = _policy.apply_overlay_to_decision(
                    prediction_label, policy_result, _policy.OVERLAY_MODE_ENFORCE
                )
                if hypothetical != prediction_label:
                    logger.warning(
                        "credit_policy_shadow_disagreement",
                        extra={
                            "model_version": str(self.model_version.id),
                            "model_decision": prediction_label,
                            "policy_hypothetical": hypothetical,
                            "hard_fails": policy_result.hard_fails,
                            "refers": policy_result.refers,
                        },
                    )

            policy_payload = {
                **policy_result.to_dict(),
                "mode": policy_mode,
                "changed_model_decision": final_prediction != prediction_label,
            }

            # Enforce-mode refer takes precedence over model borderline flag —
            # send to human review rather than approve/deny auto-pathway.
            if policy_mode == _policy.OVERLAY_MODE_ENFORCE and policy_result.has_refer:
                requires_human_review = True

            # D6 — referral audit trail (orthogonal to bias review queue).
            # Persist on the LoanApplication itself so admins can query
            # referrals via /api/loans/referrals/. Save is wrapped in a
            # try/except so a persistence failure never breaks prediction.
            if policy_result.has_refer and application is not None:
                try:
                    application.referral_status = application.ReferralStatus.REFERRED
                    application.referral_codes = list(policy_result.refers)
                    application.referral_rationale = {
                        code: policy_result.rationale_by_code.get(code, "") for code in policy_result.refers
                    }
                    application.save(update_fields=["referral_status", "referral_codes", "referral_rationale"])
                except Exception:
                    logger.warning(
                        "referral_audit_save_failed",
                        exc_info=True,
                        extra={
                            "application_id": str(getattr(application, "id", None)),
                            "refers": list(policy_result.refers),
                        },
                    )

            prediction_label = final_prediction
        except Exception as _policy_exc:
            logger.warning("credit_policy_evaluate_failed", exc_info=True)
            policy_payload = {
                "passed": None,
                "mode": "off",
                "error": str(_policy_exc),
            }

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
                challenger_predictor.model.predict_proba(
                    transformed[challenger_predictor.feature_cols]
                )[:, 1][0]
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

