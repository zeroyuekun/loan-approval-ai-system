import hashlib
import logging
import math
import threading
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from django.conf import settings

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.consistency import DataConsistencyChecker
from prometheus_client import Counter, Histogram

ml_predictions_total = Counter(
    'ml_predictions_total', 'Total ML predictions',
    ['decision', 'model_version'],
)
ml_prediction_latency_seconds = Histogram(
    'ml_prediction_latency_seconds', 'ML prediction computation time',
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
ml_prediction_confidence = Histogram(
    'ml_prediction_confidence', 'Prediction confidence distribution',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
ml_drift_warnings_total = Counter(
    'ml_drift_warnings_total', 'Predictions with drift warnings',
)

logger = logging.getLogger(__name__)


# Module-level cache for loaded model bundles, keyed by model version ID.
# Bounded to _MAX_CACHE_ENTRIES to prevent unbounded memory growth.
_MAX_CACHE_ENTRIES = 3
_model_cache = {}
_cache_lock = threading.Lock()


# Bounds for input validation: (min, max) inclusive.
FEATURE_BOUNDS = {
    'annual_income': (0, 10_000_000),
    'credit_score': (0, 1200),  # Equifax Australia scale
    'loan_amount': (0, 5_000_000),  # Aligned with LoanApplication.loan_amount MaxValueValidator
    'loan_term_months': (1, 600),
    'debt_to_income': (0.0, 100.0),
    'employment_length': (0, 60),
    'has_cosigner': (0, 1),
    'property_value': (0, 100_000_000),
    'deposit_amount': (0, 5_000_000),  # Cannot exceed loan amount
    'monthly_expenses': (0, 1_000_000),
    'existing_credit_card_limit': (0, 10_000_000),
    'number_of_dependants': (0, 10),  # Aligned with LoanApplication.number_of_dependants MaxValueValidator
    'has_hecs': (0, 1),
    'has_bankruptcy': (0, 1),
    'num_credit_enquiries_6m': (0, 50),
    'worst_arrears_months': (0, 36),
    'num_defaults_5yr': (0, 20),
    'credit_history_months': (0, 600),
    'total_open_accounts': (0, 50),
    'num_bnpl_accounts': (0, 20),
    'savings_balance': (0, 10_000_000),
    'salary_credit_regularity': (0, 1),
    'num_dishonours_12m': (0, 100),
    'avg_monthly_savings_rate': (-1, 1),
    'days_in_overdraft_12m': (0, 365),
    'rba_cash_rate': (0, 20),
    'unemployment_rate': (0, 30),
    'property_growth_12m': (-50, 100),
    'consumer_confidence': (0, 200),
    'income_verification_gap': (0, 10),
    'document_consistency_score': (0, 1),
    # CCR features
    'num_late_payments_24m': (0, 50),
    'worst_late_payment_days': (0, 90),
    'total_credit_limit': (0, 5_000_000),
    'credit_utilization_pct': (0, 1),
    'num_hardship_flags': (0, 10),
    'months_since_last_default': (0, 999),
    'num_credit_providers': (0, 30),
    # BNPL-specific
    'bnpl_total_limit': (0, 100_000),
    'bnpl_utilization_pct': (0, 1),
    'bnpl_late_payments_12m': (0, 50),
    'bnpl_monthly_commitment': (0, 10_000),
    # CDR/Open Banking transaction features
    'income_source_count': (0, 20),
    'rent_payment_regularity': (0, 1),
    'utility_payment_regularity': (0, 1),
    'essential_to_total_spend': (0, 1),
    'subscription_burden': (0, 1),
    'balance_before_payday': (-10_000, 1_000_000),
    'min_balance_30d': (-10_000, 1_000_000),
    'days_negative_balance_90d': (0, 90),
    # Geographic risk
    'postcode_default_rate': (0, 1),
    # Behavioral features
    'financial_literacy_score': (0.0, 1.0),
    'prepayment_buffer_months': (0, 60),
    'optimism_bias_flag': (0, 1),
    'negative_equity_flag': (0, 1),
}


def _validate_model_path(file_path):
    """Validate that the model file path is safe to load."""
    models_dir = Path(settings.ML_MODELS_DIR).resolve()
    resolved = Path(file_path).resolve()

    if not resolved.is_relative_to(models_dir):
        raise ValueError(
            f"Model file path '{file_path}' is outside the allowed directory"
        )
    if resolved.suffix != '.joblib':
        raise ValueError(
            f"Model file must have .joblib extension, got '{resolved.suffix}'"
        )
    if not resolved.exists():
        raise FileNotFoundError(f"Model file not found: {resolved}")

    return resolved


def _verify_model_hash(file_path, expected_hash):
    """Verify SHA-256 hash of model file to detect tampering."""
    if not expected_hash:
        logger.warning("No file_hash stored for model — skipping integrity check")
        return
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    actual_hash = sha256.hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            f"Model file integrity check failed: expected hash {expected_hash[:16]}..., "
            f"got {actual_hash[:16]}..."
        )


def _load_bundle(model_version):
    """Load and cache a model bundle, returning it from cache if available."""
    version_id = model_version.id
    with _cache_lock:
        if version_id in _model_cache:
            return _model_cache[version_id]

    resolved_path = _validate_model_path(model_version.file_path)
    _verify_model_hash(resolved_path, getattr(model_version, 'file_hash', None))

    bundle = joblib.load(resolved_path)

    with _cache_lock:
        # Evict oldest entries if cache is at capacity
        while len(_model_cache) >= _MAX_CACHE_ENTRIES:
            oldest_key = next(iter(_model_cache))
            del _model_cache[oldest_key]
            logger.info('Evicted model version %s from cache (max %d entries)',
                        oldest_key, _MAX_CACHE_ENTRIES)
        _model_cache[version_id] = bundle
    return bundle


def clear_model_cache():
    """Clear the model cache (e.g. after retraining)."""
    with _cache_lock:
        _model_cache.clear()


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
        return 'AAA'
    elif pd < 0.01:
        return 'AA'
    elif pd < 0.03:
        return 'A'
    elif pd < 0.07:
        return 'BBB'
    elif pd < 0.15:
        return 'BB'
    elif pd < 0.30:
        return 'B'
    else:
        return 'CCC'


class ModelPredictor:
    """Loads the active model and runs predictions."""

    CATEGORICAL_COLS = ['purpose', 'home_ownership', 'employment_type', 'applicant_type', 'state', 'savings_trend_3m', 'industry_risk_tier']

    def __init__(self, model_version=None):
        if model_version is not None:
            self.model_version = model_version
        else:
            from apps.ml_engine.services.model_selector import select_model_version
            self.model_version = select_model_version()

        bundle = _load_bundle(self.model_version)
        self.model = bundle['model']
        self.scaler = bundle['scaler']
        self.feature_cols = bundle['feature_cols']
        # Support both old (label_encoders) and new (one-hot) bundles
        self.label_encoders = bundle.get('label_encoders')
        self.categorical_cols = bundle.get('categorical_cols', self.CATEGORICAL_COLS)
        self.numeric_cols = bundle.get('numeric_cols', [])
        self.reference_distribution = bundle.get('reference_distribution', {})
        from apps.ml_engine.services.feature_engineering import DEFAULT_IMPUTATION_VALUES
        self.imputation_values = bundle.get('imputation_values', DEFAULT_IMPUTATION_VALUES)
        self.feature_bounds = bundle.get('feature_bounds', {})
        self.group_thresholds = bundle.get('group_thresholds', {})
        self.conformal_scores = bundle.get('conformal_scores', np.array([]))
        self.consistency_checker = DataConsistencyChecker()

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
        try:
            state = getattr(application, 'state', None)
            if state:
                return state
        except Exception as e:
            logger.debug('Could not read state from application, defaulting to NSW: %s', e)
        return 'NSW'

    def _validate_input(self, features: dict):
        """Validate feature values are within reasonable bounds.

        Raises ValueError with details on any out-of-bounds values.
        """
        bounds = {**FEATURE_BOUNDS}
        # Data-driven bounds can only widen the hardcoded range, never narrow it.
        # This prevents the training set's min/max from rejecting legitimate
        # edge-case applicants (e.g. credit_score 620, 3 months arrears).
        for col, (data_lo, data_hi) in self.feature_bounds.items():
            if col in bounds:
                hard_lo, hard_hi = bounds[col]
                bounds[col] = (min(hard_lo, data_lo), max(hard_hi, data_hi))
            else:
                bounds[col] = (data_lo, data_hi)

        errors = []
        for col, (lo, hi) in bounds.items():
            val = features.get(col)
            if val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                errors.append(f"{col}: cannot convert {val!r} to number")
                continue
            if math.isnan(val) or math.isinf(val):
                errors.append(f"{col}: invalid value (nan/inf not allowed)")
                continue
            if val < lo or val > hi:
                errors.append(f"{col}: {val} is outside valid range [{lo}, {hi}]")

        if errors:
            raise ValueError("Input validation failed: " + "; ".join(errors))

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
                    df[col] = df[col].apply(
                        lambda x, kc=known_classes, le_=le: x if x in kc else le_.classes_[0]
                    )
                    df[col] = le.transform(df[col].astype(str))
            df[self.feature_cols] = self.scaler.transform(df[self.feature_cols])
        else:
            # New path: one-hot encoding
            df = pd.get_dummies(df, columns=self.categorical_cols, dtype=float)

            # Align to training columns: add missing as 0, reorder
            missing_cols = [col for col in self.feature_cols if col not in df.columns]
            if missing_cols:
                logger.warning(
                    "Unknown categories at inference time — columns missing from training: %s. "
                    "These will be set to 0.",
                    missing_cols,
                )
            for col in missing_cols:
                df[col] = 0.0

            df[self.feature_cols] = self.scaler.transform(df[self.feature_cols])

        return df

    def predict(self, application):
        """
        Predict approval for a LoanApplication instance.
        Returns dict with prediction, probability, and feature_importances.
        """
        start_time = time.time()

        # Build feature dict from application
        features = {
            'annual_income': float(application.annual_income),
            'credit_score': application.credit_score,
            'loan_amount': float(application.loan_amount),
            'loan_term_months': application.loan_term_months,
            'debt_to_income': float(application.debt_to_income),
            'employment_length': application.employment_length,
            'has_cosigner': int(application.has_cosigner),
            'purpose': application.purpose,
            'home_ownership': application.home_ownership,
            'property_value': float(application.property_value) if application.property_value is not None else self.imputation_values.get('property_value', 0),
            'deposit_amount': float(application.deposit_amount) if application.deposit_amount is not None else self.imputation_values.get('deposit_amount', 0),
            'monthly_expenses': float(application.monthly_expenses) if application.monthly_expenses is not None else self.imputation_values.get('monthly_expenses', 2500),
            'existing_credit_card_limit': float(application.existing_credit_card_limit) if application.existing_credit_card_limit is not None else self.imputation_values.get('existing_credit_card_limit', 0),
            'number_of_dependants': application.number_of_dependants,
            'employment_type': application.employment_type,
            'applicant_type': application.applicant_type,
            'has_hecs': int(getattr(application, 'has_hecs', 0)),
            'has_bankruptcy': int(getattr(application, 'has_bankruptcy', 0)),
            'state': self._safe_get_state(application),
            # Bureau features
            'num_credit_enquiries_6m': int(application.num_credit_enquiries_6m) if application.num_credit_enquiries_6m is not None else self.imputation_values.get('num_credit_enquiries_6m', 1),
            'worst_arrears_months': int(application.worst_arrears_months) if application.worst_arrears_months is not None else self.imputation_values.get('worst_arrears_months', 0),
            'num_defaults_5yr': int(application.num_defaults_5yr) if application.num_defaults_5yr is not None else self.imputation_values.get('num_defaults_5yr', 0),
            'credit_history_months': int(application.credit_history_months) if application.credit_history_months is not None else self.imputation_values.get('credit_history_months', 120),
            'total_open_accounts': int(application.total_open_accounts) if application.total_open_accounts is not None else self.imputation_values.get('total_open_accounts', 3),
            'num_bnpl_accounts': int(application.num_bnpl_accounts) if application.num_bnpl_accounts is not None else self.imputation_values.get('num_bnpl_accounts', 0),
            # Behavioural features
            'is_existing_customer': int(getattr(application, 'is_existing_customer', False)),
            'savings_balance': float(application.savings_balance) if application.savings_balance is not None else self.imputation_values.get('savings_balance', 10000),
            'salary_credit_regularity': float(application.salary_credit_regularity) if application.salary_credit_regularity is not None else self.imputation_values.get('salary_credit_regularity', 0.8),
            'num_dishonours_12m': int(application.num_dishonours_12m) if application.num_dishonours_12m is not None else self.imputation_values.get('num_dishonours_12m', 0),
            'avg_monthly_savings_rate': float(application.avg_monthly_savings_rate) if application.avg_monthly_savings_rate is not None else self.imputation_values.get('avg_monthly_savings_rate', 0.10),
            'days_in_overdraft_12m': int(application.days_in_overdraft_12m) if application.days_in_overdraft_12m is not None else self.imputation_values.get('days_in_overdraft_12m', 0),
            # Macroeconomic context
            'rba_cash_rate': float(application.rba_cash_rate) if application.rba_cash_rate is not None else self.imputation_values.get('rba_cash_rate', 4.10),
            'unemployment_rate': float(application.unemployment_rate) if application.unemployment_rate is not None else self.imputation_values.get('unemployment_rate', 3.8),
            'property_growth_12m': float(application.property_growth_12m) if application.property_growth_12m is not None else self.imputation_values.get('property_growth_12m', 5.0),
            'consumer_confidence': float(application.consumer_confidence) if application.consumer_confidence is not None else self.imputation_values.get('consumer_confidence', 95.0),
            # Application integrity
            'income_verification_gap': float(application.income_verification_gap) if application.income_verification_gap is not None else self.imputation_values.get('income_verification_gap', 1.0),
            'document_consistency_score': float(application.document_consistency_score) if application.document_consistency_score is not None else self.imputation_values.get('document_consistency_score', 0.9),
            # Open Banking features (Plaid/Basiq-inspired)
            'savings_trend_3m': getattr(application, 'savings_trend_3m', None) or 'flat',
            'discretionary_spend_ratio': float(application.discretionary_spend_ratio) if getattr(application, 'discretionary_spend_ratio', None) is not None else self.imputation_values.get('discretionary_spend_ratio', 0.35),
            'gambling_transaction_flag': int(getattr(application, 'gambling_transaction_flag', False)),
            'bnpl_active_count': int(application.bnpl_active_count) if getattr(application, 'bnpl_active_count', None) is not None else self.imputation_values.get('bnpl_active_count', 0),
            'overdraft_frequency_90d': int(application.overdraft_frequency_90d) if getattr(application, 'overdraft_frequency_90d', None) is not None else self.imputation_values.get('overdraft_frequency_90d', 0),
            'income_verification_score': float(application.income_verification_score) if getattr(application, 'income_verification_score', None) is not None else self.imputation_values.get('income_verification_score', 0.85),
            # CCR features
            'num_late_payments_24m': int(application.num_late_payments_24m) if getattr(application, 'num_late_payments_24m', None) is not None else 0,
            'worst_late_payment_days': int(application.worst_late_payment_days) if getattr(application, 'worst_late_payment_days', None) is not None else 0,
            'total_credit_limit': float(application.total_credit_limit) if getattr(application, 'total_credit_limit', None) is not None else self.imputation_values.get('total_credit_limit', 20000.0),
            'credit_utilization_pct': float(application.credit_utilization_pct) if getattr(application, 'credit_utilization_pct', None) is not None else self.imputation_values.get('credit_utilization_pct', 0.30),
            'num_hardship_flags': int(application.num_hardship_flags) if getattr(application, 'num_hardship_flags', None) is not None else 0,
            'months_since_last_default': float(application.months_since_last_default) if getattr(application, 'months_since_last_default', None) is not None else self.imputation_values.get('months_since_last_default', 999),
            'num_credit_providers': int(application.num_credit_providers) if getattr(application, 'num_credit_providers', None) is not None else self.imputation_values.get('num_credit_providers', 2),
            # BNPL-specific
            'bnpl_total_limit': float(application.bnpl_total_limit) if getattr(application, 'bnpl_total_limit', None) is not None else 0.0,
            'bnpl_utilization_pct': float(application.bnpl_utilization_pct) if getattr(application, 'bnpl_utilization_pct', None) is not None else 0.0,
            'bnpl_late_payments_12m': int(application.bnpl_late_payments_12m) if getattr(application, 'bnpl_late_payments_12m', None) is not None else 0,
            'bnpl_monthly_commitment': float(application.bnpl_monthly_commitment) if getattr(application, 'bnpl_monthly_commitment', None) is not None else 0.0,
            # CDR/Open Banking transaction features
            'income_source_count': int(application.income_source_count) if getattr(application, 'income_source_count', None) is not None else 1,
            'rent_payment_regularity': float(application.rent_payment_regularity) if getattr(application, 'rent_payment_regularity', None) is not None else self.imputation_values.get('rent_payment_regularity', 0.85),
            'utility_payment_regularity': float(application.utility_payment_regularity) if getattr(application, 'utility_payment_regularity', None) is not None else self.imputation_values.get('utility_payment_regularity', 0.90),
            'essential_to_total_spend': float(application.essential_to_total_spend) if getattr(application, 'essential_to_total_spend', None) is not None else self.imputation_values.get('essential_to_total_spend', 0.50),
            'subscription_burden': float(application.subscription_burden) if getattr(application, 'subscription_burden', None) is not None else self.imputation_values.get('subscription_burden', 0.05),
            'balance_before_payday': float(application.balance_before_payday) if getattr(application, 'balance_before_payday', None) is not None else self.imputation_values.get('balance_before_payday', 2000.0),
            'min_balance_30d': float(application.min_balance_30d) if getattr(application, 'min_balance_30d', None) is not None else self.imputation_values.get('min_balance_30d', 500.0),
            'days_negative_balance_90d': int(application.days_negative_balance_90d) if getattr(application, 'days_negative_balance_90d', None) is not None else 0,
            # Geographic risk
            'postcode_default_rate': float(application.postcode_default_rate) if getattr(application, 'postcode_default_rate', None) is not None else self.imputation_values.get('postcode_default_rate', 0.015),
            'industry_risk_tier': getattr(application, 'industry_risk_tier', None) or 'medium',
        }

        # Validate inputs
        self._validate_input(features)

        # Cross-validate data consistency
        consistency = self.consistency_checker.check_all(features)
        if not consistency['consistent']:
            error_msgs = '; '.join(e['message'] for e in consistency['errors'])
            raise ValueError(
                f"Data consistency check failed: {error_msgs}"
            )

        df = pd.DataFrame([features])
        features_df = df.copy()  # preserve raw features for counterfactual generation

        # Transform using saved preprocessing artifacts
        df = self._transform(df)

        # Predict
        prediction = self.model.predict(df[self.feature_cols])[0]
        probabilities = self.model.predict_proba(df[self.feature_cols])[0]

        # Global feature importances
        importances = {}
        if hasattr(self.model, 'feature_importances_'):
            for name, imp in zip(self.feature_cols, self.model.feature_importances_):
                importances[name] = round(float(imp), 4)

        # Per-prediction SHAP values
        shap_values_dict = {}
        shap_available = False
        try:
            # For calibrated models, extract the underlying estimator for TreeExplainer.
            # _CalibratedModel wraps the fitted tree model with isotonic calibration;
            # SHAP needs the raw tree model, not the wrapper.
            underlying = self.model.get_underlying_estimator() if hasattr(self.model, 'get_underlying_estimator') else self.model
            explainer = shap.TreeExplainer(underlying)
            sv = explainer.shap_values(df[self.feature_cols])
            # For binary classification shap_values may return a list of two arrays
            if isinstance(sv, list):
                sv = sv[1]  # SHAP values for the positive class
            for name, val in zip(self.feature_cols, sv[0]):
                shap_values_dict[name] = round(float(val), 4)
            shap_available = True

            calibrated_prob = float(probabilities[1])
            if abs(float(np.array(explainer.expected_value).flat[0]) - calibrated_prob) > 0.05:
                logger.warning('SHAP expected value (%.3f) diverges from calibrated probability (%.3f) — values are from uncalibrated base model', float(np.array(explainer.expected_value).flat[0]), calibrated_prob)
        except Exception:
            logger.warning("SHAP computation failed, returning empty shap_values", exc_info=True)

        processing_time = int((time.time() - start_time) * 1000)

        # Per-application drift flags: check if key features are far outside
        # the training distribution (APRA CPG 235 ongoing monitoring)
        drift_warnings = self._check_feature_drift(features)

        # Use optimal threshold from model version if available
        threshold = self.model_version.optimal_threshold or 0.5
        probability = round(float(probabilities[1]), 4)

        # Per-group fairness threshold (EEOC 80% rule compliance)
        effective_threshold = threshold
        employment_type = features.get('employment_type', '')
        if self.group_thresholds and employment_type in self.group_thresholds:
            effective_threshold = self.group_thresholds[employment_type]

        prediction_label = 'approved' if probability >= effective_threshold else 'denied'

        # Flag borderline cases for human review
        requires_human_review = abs(probability - threshold) <= 0.10

        # Also flag for review if significant feature drift detected
        if any(w.get('severity') == 'drift' for w in drift_warnings):
            requires_human_review = True

        # Expected Loss (EL = PD x LGD x EAD) — Basel III / APRA APS 113
        from .metrics import MetricsService
        _ms = MetricsService()
        property_val = float(features.get('property_value') or 0)
        lvr = (float(features.get('loan_amount', 0)) / property_val) if property_val > 0 else 0.0
        expected_loss = _ms.compute_expected_loss(
            pd_value=1.0 - probability,  # PD = probability of denial/default
            loan_amount=features.get('loan_amount', 0),
            purpose=features.get('purpose', 'personal'),
            lvr=lvr,
            credit_score=features.get('credit_score', 864),
        )

        # Stress testing — 4 adverse scenarios
        stress_results = self._stress_test(features, threshold)

        # Conformal prediction interval (95% coverage)
        confidence_interval = self._conformal_interval(probability, alpha=0.05)

        result = {
            'prediction': prediction_label,
            'probability': probability,
            'threshold_used': threshold,
            'effective_threshold': effective_threshold,
            'requires_human_review': requires_human_review,
            'feature_importances': importances,
            'shap_values': shap_values_dict,
            'shap_available': shap_available,
            'shap_model_note': 'Feature attributions computed on base model before probability calibration',
            'processing_time_ms': processing_time,
            'model_version': str(self.model_version.id),
            'consistency_warnings': consistency['warnings'],
            'drift_warnings': drift_warnings,
            'expected_loss': expected_loss,
            'stress_test': stress_results,
            'confidence_interval': confidence_interval,
        }

        # Generate counterfactual explanations for denied applications
        if result['prediction'] == 'denied':
            try:
                model_bundle = {
                    'model': self.model,
                    'threshold': threshold,
                }
                result['counterfactuals'] = self._generate_counterfactuals(
                    features_df, result['feature_importances'], model_bundle
                )
            except Exception as e:
                logger.warning('Counterfactual generation failed: %s', e)
                result['counterfactuals'] = []
        else:
            result['counterfactuals'] = []

        # Emit Prometheus metrics for ML observability
        try:
            ml_predictions_total.labels(
                decision=result['prediction'],
                model_version=str(self.model_version.id)[:8],
            ).inc()
            ml_prediction_latency_seconds.observe(result['processing_time_ms'] / 1000.0)
            ml_prediction_confidence.observe(result['probability'])
            if result.get('drift_warnings'):
                ml_drift_warnings_total.inc()
        except Exception as e:
            logger.debug('Prometheus metrics emission failed (non-blocking): %s', e)

        # === Champion/Challenger Shadow Scoring ===
        # If challenger models exist, score with them too (shadow mode)
        try:
            from apps.ml_engine.models import ModelVersion as MV
            from apps.ml_engine.models import PredictionLog

            challengers = MV.objects.filter(
                is_active=False,
                traffic_percentage__gt=0,
                traffic_percentage__lt=100,
            ).exclude(pk=self.model_version.pk)

            for challenger in challengers[:2]:  # Max 2 challengers
                try:
                    challenger_predictor = ModelPredictor(model_version=challenger)
                    features_transformed_c = challenger_predictor._transform(features_df.copy())  # Use raw features, not already-transformed df
                    challenger_prob = float(
                        challenger_predictor.model.predict_proba(
                            features_transformed_c[challenger_predictor.feature_cols]
                        )[:, 1][0]
                    )
                    challenger_pred = (
                        'approved'
                        if challenger_prob >= (challenger.optimal_threshold or 0.5)
                        else 'denied'
                    )

                    # Log shadow prediction (not used for decision)
                    PredictionLog.objects.create(
                        model_version=challenger,
                        application=application,
                        prediction=challenger_pred,
                        probability=challenger_prob,
                        feature_importances={},
                        processing_time_ms=0,
                    )
                    logger.info(
                        'Shadow score: challenger %s predicted %s (%.3f) vs champion %s (%.3f)',
                        challenger.version, challenger_pred, challenger_prob,
                        prediction_label, probability,
                    )
                except Exception as e:
                    logger.warning('Shadow scoring failed for challenger %s: %s', challenger.version, e)
        except Exception as e:
            logger.debug('Shadow scoring check skipped: %s', e)

        return result

    def _check_feature_drift(self, features):
        """Check if individual feature values fall far outside training distribution.

        This is a per-application check, not a batch PSI. It flags when a single
        applicant's values are extreme outliers relative to what the model was
        trained on, which may indicate the model is being applied outside its
        valid range.

        For batch PSI monitoring, use MetricsService.compute_feature_psi().
        """
        warnings = []
        if not self.reference_distribution:
            return warnings

        for col, ref in self.reference_distribution.items():
            val = features.get(col)
            if val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue

            mean = ref.get('mean', 0)
            std = ref.get('std', 1)
            percentiles = ref.get('percentiles', [])

            if std < 0.001:
                continue

            # Flag values beyond 3 standard deviations from training mean
            z_score = abs(val - mean) / std
            if z_score > 4.0:
                warnings.append({
                    'feature': col,
                    'value': val,
                    'z_score': round(z_score, 2),
                    'training_mean': round(mean, 2),
                    'training_std': round(std, 2),
                    'severity': 'drift',
                    'message': (
                        f'{col} value ({val:,.2f}) is {z_score:.1f} standard deviations '
                        f'from the training mean ({mean:,.2f}). The model may not '
                        f'be reliable for this input range.'
                    ),
                })
            elif z_score > 3.0:
                warnings.append({
                    'feature': col,
                    'value': val,
                    'z_score': round(z_score, 2),
                    'training_mean': round(mean, 2),
                    'training_std': round(std, 2),
                    'severity': 'warning',
                    'message': (
                        f'{col} value ({val:,.2f}) is {z_score:.1f} standard deviations '
                        f'from the training mean ({mean:,.2f}). This is unusual but '
                        f'within tolerance.'
                    ),
                })

        return warnings

    def _stress_test(self, features, threshold):
        """Run 4 adverse scenarios to show model behavior under stress.

        Required under APRA APS 110 for stress testing. Shows that worse
        inputs produce lower approval probabilities (model degrades sensibly).
        """
        scenarios = {}
        base_prob = None

        try:
            df_base = pd.DataFrame([features])
            df_base = self._transform(df_base)
            base_prob = float(self.model.predict_proba(df_base[self.feature_cols])[0][1])

            # Scenario 1: Income -15%
            stressed = features.copy()
            stressed['annual_income'] = float(stressed['annual_income']) * 0.85
            stressed['debt_to_income'] = float(stressed.get('loan_amount', 0)) / stressed['annual_income']
            df_s = pd.DataFrame([stressed])
            df_s = self._transform(df_s)
            prob = float(self.model.predict_proba(df_s[self.feature_cols])[0][1])
            scenarios['income_minus_15pct'] = {
                'probability': round(prob, 4),
                'decision': 'approved' if prob >= threshold else 'denied',
                'change': round(prob - base_prob, 4),
            }

            # Scenario 2: Property value -20%
            stressed = features.copy()
            if float(stressed.get('property_value', 0)) > 0:
                stressed['property_value'] = float(stressed['property_value']) * 0.80
            df_s = pd.DataFrame([stressed])
            df_s = self._transform(df_s)
            prob = float(self.model.predict_proba(df_s[self.feature_cols])[0][1])
            scenarios['property_minus_20pct'] = {
                'probability': round(prob, 4),
                'decision': 'approved' if prob >= threshold else 'denied',
                'change': round(prob - base_prob, 4),
            }

            # Scenario 3: Credit score -50
            stressed = features.copy()
            stressed['credit_score'] = max(300, int(stressed['credit_score']) - 50)
            df_s = pd.DataFrame([stressed])
            df_s = self._transform(df_s)
            prob = float(self.model.predict_proba(df_s[self.feature_cols])[0][1])
            scenarios['credit_minus_50'] = {
                'probability': round(prob, 4),
                'decision': 'approved' if prob >= threshold else 'denied',
                'change': round(prob - base_prob, 4),
            }

            # Scenario 4: Combined stress (all three)
            stressed = features.copy()
            stressed['annual_income'] = float(stressed['annual_income']) * 0.85
            stressed['debt_to_income'] = float(stressed.get('loan_amount', 0)) / stressed['annual_income']
            if float(stressed.get('property_value', 0)) > 0:
                stressed['property_value'] = float(stressed['property_value']) * 0.80
            stressed['credit_score'] = max(300, int(stressed['credit_score']) - 50)
            df_s = pd.DataFrame([stressed])
            df_s = self._transform(df_s)
            prob = float(self.model.predict_proba(df_s[self.feature_cols])[0][1])
            scenarios['combined_stress'] = {
                'probability': round(prob, 4),
                'decision': 'approved' if prob >= threshold else 'denied',
                'change': round(prob - base_prob, 4),
            }
        except Exception:
            logger.warning("Stress test computation failed", exc_info=True)

        return {
            'base_probability': round(base_prob, 4) if base_prob is not None else None,
            'scenarios': scenarios,
        }

    def _conformal_interval(self, probability, alpha=0.05):
        """Compute conformal prediction interval with guaranteed coverage.

        Uses split conformal prediction: nonconformity scores computed on
        the validation set during training define how much the prediction
        can vary. At confidence level (1-alpha), the true probability is
        within [prob - q, prob + q] where q is the (1-alpha) quantile of
        the nonconformity scores.

        This gives honest uncertainty estimates — unlike a raw probability
        which has no coverage guarantee.

        Args:
            probability: model predicted probability of approval
            alpha: significance level (0.05 = 95% confidence)

        Returns:
            dict with lower, upper bounds and confidence level.
        """
        if len(self.conformal_scores) == 0:
            return {
                'lower': round(probability, 4),
                'upper': round(probability, 4),
                'confidence_level': 1 - alpha,
                'available': False,
            }

        # Quantile of nonconformity scores at (1 - alpha) level
        n = len(self.conformal_scores)
        sorted_scores = np.sort(self.conformal_scores)

        # Small Sample Beta Correction (SSBC) for calibration sets < 500
        # Reference: arxiv.org/abs/2509.15349
        ssbc_applied = False
        if n < 500:
            try:
                from scipy.stats import beta as beta_dist

                # Adjust alpha for finite-sample coverage guarantee
                # Target: P(coverage >= 1-alpha) >= 0.9
                adjusted_alpha = alpha
                for candidate_alpha in np.arange(alpha * 0.5, alpha, 0.001):
                    k = int(np.ceil((1 - candidate_alpha) * (n + 1))) - 1
                    k = min(k, n - 1)
                    # Beta distribution for order statistic coverage
                    coverage_prob = 1 - beta_dist.cdf(1 - alpha, n - k, k + 1)
                    if coverage_prob >= 0.9:
                        adjusted_alpha = candidate_alpha
                        break

                if adjusted_alpha != alpha:
                    logger.info(
                        'SSBC: adjusted alpha from %.3f to %.3f (n=%d, target coverage=0.9)',
                        alpha, adjusted_alpha, n,
                    )
                    alpha = adjusted_alpha
                    ssbc_applied = True
            except ImportError:
                logger.debug('scipy not available for SSBC correction')

        q_idx = int(np.ceil((1 - alpha) * (n + 1))) - 1
        q_idx = min(max(q_idx, 0), n - 1)
        q = float(sorted_scores[q_idx])

        lower = max(0.0, probability - q)
        upper = min(1.0, probability + q)

        return {
            'lower': round(lower, 4),
            'upper': round(upper, 4),
            'width': round(upper - lower, 4),
            'confidence_level': 1 - alpha,
            'ssbc_applied': ssbc_applied,
            'available': True,
        }

    def _generate_counterfactuals(self, features_df, feature_importances, model_bundle):
        """Generate counterfactual explanations for denied applications.

        For top 3 negative factors, binary-search for the value that flips
        the prediction. Returns actionable statements.
        """
        counterfactuals = []

        if not feature_importances:
            return counterfactuals

        # Get top 3 features that most contributed to denial
        sorted_features = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:3]

        model = model_bundle['model']

        for feature_name, importance in sorted_features:
            if feature_name not in features_df.columns:
                continue

            current_value = features_df[feature_name].iloc[0]

            # Define search bounds based on feature type
            feature_bounds = {
                'credit_score': (300, 1200),
                'annual_income': (20000, 2000000),
                'debt_to_income': (0, 10),
                'employment_length': (0, 50),
                'loan_amount': (5000, 5000000),
                'monthly_expenses': (500, 50000),
                'existing_credit_card_limit': (0, 200000),
            }

            bounds = feature_bounds.get(feature_name)
            if bounds is None:
                continue

            # Determine search direction (increase or decrease)
            # For DTI, expenses, loan_amount: decrease is better
            # For credit_score, income, employment: increase is better
            decrease_is_better = feature_name in ('debt_to_income', 'monthly_expenses', 'loan_amount', 'existing_credit_card_limit')

            if decrease_is_better:
                low, high = bounds[0], float(current_value)
            else:
                low, high = float(current_value), bounds[1]

            # Binary search for the flip point
            flip_value = None
            for _ in range(30):  # max iterations
                mid = (low + high) / 2
                test_df = features_df.copy()
                test_df[feature_name] = mid

                try:
                    # Use the same preprocessing pipeline as predict()
                    transformed_df = self._transform(test_df)
                    prob = model.predict_proba(transformed_df[self.feature_cols])[0][1]
                    threshold = model_bundle.get('threshold', 0.5)

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
                    logger.debug('Counterfactual binary search step failed: %s', e)
                    break

            if flip_value is not None:
                # Format the counterfactual statement
                readable_name = feature_name.replace('_', ' ').title()

                if feature_name in ('annual_income', 'loan_amount', 'monthly_expenses', 'existing_credit_card_limit'):
                    current_fmt = f"${current_value:,.0f}"
                    target_fmt = f"${flip_value:,.0f}"
                elif feature_name == 'credit_score':
                    current_fmt = f"{int(current_value)}"
                    target_fmt = f"{int(flip_value)}"
                elif feature_name == 'debt_to_income':
                    current_fmt = f"{current_value:.1f}x"
                    target_fmt = f"{flip_value:.1f}x"
                else:
                    current_fmt = f"{current_value:.1f}"
                    target_fmt = f"{flip_value:.1f}"

                direction = "Reducing" if decrease_is_better else "Increasing"
                counterfactuals.append({
                    'feature': feature_name,
                    'current_value': float(current_value),
                    'target_value': round(float(flip_value), 2),
                    'statement': f"{direction} {readable_name.lower()} from {current_fmt} to {target_fmt} would change the outcome",
                })

        return counterfactuals
