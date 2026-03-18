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

logger = logging.getLogger(__name__)


# Module-level cache for loaded model bundles, keyed by model version ID.
_model_cache = {}
_cache_lock = threading.Lock()


# Bounds for input validation: (min, max) inclusive.
FEATURE_BOUNDS = {
    'annual_income': (0, 10_000_000),
    'credit_score': (0, 1200),  # Equifax Australia scale
    'loan_amount': (0, 50_000_000),
    'loan_term_months': (1, 600),
    'debt_to_income': (0.0, 100.0),
    'employment_length': (0, 60),
    'has_cosigner': (0, 1),
    'property_value': (0, 100_000_000),
    'deposit_amount': (0, 50_000_000),
    'monthly_expenses': (0, 1_000_000),
    'existing_credit_card_limit': (0, 10_000_000),
    'number_of_dependants': (0, 20),
    'has_hecs': (0, 1),
    'has_bankruptcy': (0, 1),
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
        _model_cache[version_id] = bundle
    return bundle


def clear_model_cache():
    """Clear the model cache (e.g. after retraining)."""
    with _cache_lock:
        _model_cache.clear()


class ModelPredictor:
    """Loads the active model and runs predictions."""

    CATEGORICAL_COLS = ['purpose', 'home_ownership', 'employment_type', 'applicant_type']

    def __init__(self):
        self.model_version = ModelVersion.objects.filter(is_active=True).first()
        if not self.model_version:
            raise ValueError("No active model version found. Train a model first.")

        bundle = _load_bundle(self.model_version)
        self.model = bundle['model']
        self.scaler = bundle['scaler']
        self.feature_cols = bundle['feature_cols']
        # Support both old (label_encoders) and new (one-hot) bundles
        self.label_encoders = bundle.get('label_encoders')
        self.categorical_cols = bundle.get('categorical_cols', self.CATEGORICAL_COLS)
        self.numeric_cols = bundle.get('numeric_cols', [])
        self.consistency_checker = DataConsistencyChecker()

    @staticmethod
    def _add_derived_features(df):
        """Add engineered features matching those computed during training."""
        df = df.copy()
        df['lvr'] = np.where(
            df['property_value'] > 0,
            df['loan_amount'] / df['property_value'],
            0.0,
        )
        df['loan_to_income'] = df['loan_amount'] / df['annual_income']
        monthly_income = df['annual_income'] / 12.0
        df['credit_card_burden'] = np.where(
            monthly_income > 0,
            df['existing_credit_card_limit'] * 0.03 / monthly_income,
            0.0,
        )
        df['expense_to_income'] = np.where(
            df['annual_income'] > 0,
            df['monthly_expenses'] * 12 / df['annual_income'],
            0.0,
        )
        return df

    def _validate_input(self, features: dict):
        """Validate feature values are within reasonable bounds.

        Raises ValueError with details on any out-of-bounds values.
        """
        errors = []
        for col, (lo, hi) in FEATURE_BOUNDS.items():
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
            'property_value': float(application.property_value or 0),
            'deposit_amount': float(application.deposit_amount or 0),
            'monthly_expenses': float(application.monthly_expenses or 0),
            'existing_credit_card_limit': float(application.existing_credit_card_limit or 0),
            'number_of_dependants': application.number_of_dependants,
            'employment_type': application.employment_type,
            'applicant_type': application.applicant_type,
            'has_hecs': int(getattr(application, 'has_hecs', 0)),
            'has_bankruptcy': int(getattr(application, 'has_bankruptcy', 0)),
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
            underlying = self.model
            if hasattr(underlying, '_calibrator') and hasattr(underlying, 'estimator'):
                # Custom _CalibratedModel from trainer.py
                underlying = underlying.estimator
            elif hasattr(underlying, 'calibrated_classifiers_'):
                cc = underlying.calibrated_classifiers_[0]
                underlying = cc.estimator if hasattr(cc, 'estimator') else cc.base_estimator
            explainer = shap.TreeExplainer(underlying)
            sv = explainer.shap_values(df[self.feature_cols])
            # For binary classification shap_values may return a list of two arrays
            if isinstance(sv, list):
                sv = sv[1]  # SHAP values for the positive class
            for name, val in zip(self.feature_cols, sv[0]):
                shap_values_dict[name] = round(float(val), 4)
            shap_available = True
        except Exception:
            logger.warning("SHAP computation failed, returning empty shap_values", exc_info=True)

        processing_time = int((time.time() - start_time) * 1000)

        # Use optimal threshold from model version if available
        threshold = self.model_version.optimal_threshold or 0.5
        probability = round(float(probabilities[1]), 4)
        prediction_label = 'approved' if probability >= threshold else 'denied'

        # Flag borderline cases for human review
        requires_human_review = abs(probability - threshold) <= 0.10

        return {
            'prediction': prediction_label,
            'probability': probability,
            'threshold_used': threshold,
            'requires_human_review': requires_human_review,
            'feature_importances': importances,
            'shap_values': shap_values_dict,
            'shap_available': shap_available,
            'processing_time_ms': processing_time,
            'model_version': str(self.model_version.id),
            'consistency_warnings': consistency['warnings'],
        }
