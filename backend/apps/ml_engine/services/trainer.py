import logging
import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, train_test_split
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

from .metrics import MetricsService


class _CalibratedModel:
    """Wraps a fitted classifier with isotonic probability calibration.

    Replaces sklearn's CalibratedClassifierCV(cv='prefit') which was
    removed in scikit-learn 1.8.
    """

    def __init__(self, estimator, X_val, y_val):
        self.estimator = estimator
        val_probs = estimator.predict_proba(X_val)[:, 1]
        self._calibrator = IsotonicRegression(out_of_bounds='clip')
        self._calibrator.fit(val_probs, y_val)

    def predict(self, X):
        return self.estimator.predict(X)

    def predict_proba(self, X):
        raw_probs = self.estimator.predict_proba(X)[:, 1]
        calibrated = self._calibrator.predict(raw_probs)
        return np.column_stack([1 - calibrated, calibrated])

    @property
    def feature_importances_(self):
        return self.estimator.feature_importances_


class ModelTrainer:
    """Handles model training with GridSearchCV."""

    CATEGORICAL_COLS = ['purpose', 'home_ownership', 'employment_type', 'applicant_type']
    NUMERIC_COLS = [
        'annual_income', 'credit_score', 'loan_amount', 'loan_term_months',
        'debt_to_income', 'employment_length', 'has_cosigner',
        'property_value', 'deposit_amount', 'monthly_expenses',
        'existing_credit_card_limit', 'number_of_dependants',
        'has_hecs', 'has_bankruptcy',
        'lvr', 'loan_to_income', 'credit_card_burden', 'expense_to_income',
    ]

    def __init__(self):
        self.scaler = StandardScaler()
        self.ohe_columns = None  # column names after one-hot encoding
        self.metrics_service = MetricsService()

    @staticmethod
    def add_derived_features(df):
        """Add engineered features: LVR, loan-to-income, credit card burden, expense-to-income."""
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
        # Ensure new columns exist with defaults if missing from older datasets
        if 'has_hecs' not in df.columns:
            df['has_hecs'] = 0
        if 'has_bankruptcy' not in df.columns:
            df['has_bankruptcy'] = 0
        return df

    def fit_preprocess(self, df):
        """Fit encoders/scaler on training data and transform it.

        Returns (transformed DataFrame, feature column names).
        """
        df = df.copy()

        # Add derived features before encoding/scaling
        df = self.add_derived_features(df)

        # One-hot encode categorical columns
        df = pd.get_dummies(df, columns=self.CATEGORICAL_COLS, dtype=float)

        # Determine feature columns: numeric + all one-hot columns
        ohe_cols = [c for c in df.columns if any(c.startswith(cat + '_') for cat in self.CATEGORICAL_COLS)]
        feature_cols = self.NUMERIC_COLS + sorted(ohe_cols)
        self.ohe_columns = feature_cols  # save for transform

        # Fit and transform numeric + encoded features
        df[feature_cols] = self.scaler.fit_transform(df[feature_cols])

        return df, feature_cols

    def transform(self, df):
        """Transform new data using already-fit scaler and column schema.

        Must call fit_preprocess first.
        """
        if self.ohe_columns is None:
            raise RuntimeError("Must call fit_preprocess before transform")

        df = df.copy()

        # Add derived features before encoding/scaling
        df = self.add_derived_features(df)

        # One-hot encode categorical columns
        df = pd.get_dummies(df, columns=self.CATEGORICAL_COLS, dtype=float)

        # Align columns: add missing columns as 0, drop extra columns
        for col in self.ohe_columns:
            if col not in df.columns:
                df[col] = 0.0
        df = df[self.ohe_columns + [c for c in df.columns if c not in self.ohe_columns]]

        # Scale using already-fit scaler
        df[self.ohe_columns] = self.scaler.transform(df[self.ohe_columns])

        return df, self.ohe_columns

    def train(self, data_path, algorithm='xgb'):
        """Train model with GridSearchCV and return model + metrics."""
        start_time = time.time()

        # Load data
        df = pd.read_csv(data_path)

        if len(df) < 20:
            raise ValueError(f'Dataset too small for training: {len(df)} rows (minimum 20 required)')

        y = df['approved']
        class_counts = y.value_counts()
        if class_counts.min() < 5:
            raise ValueError(
                f'Insufficient class balance: {dict(class_counts)}. '
                f'Each class needs at least 5 samples.'
            )

        # 80/10/10 split BEFORE preprocessing to avoid data leakage
        df_train, df_temp, y_train, y_temp = train_test_split(
            df, y, test_size=0.2, random_state=42, stratify=y
        )
        df_val, df_test, y_val, y_test = train_test_split(
            df_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
        )

        # Save original test indices before transform() resets them
        test_original_indices = df_test.index.copy()

        # Fit preprocessing on training data only
        df_train, feature_cols = self.fit_preprocess(df_train)
        X_train = df_train[feature_cols]

        # Transform val and test using already-fit encoders/scaler
        df_val, _ = self.transform(df_val)
        X_val = df_val[feature_cols]

        df_test, _ = self.transform(df_test)
        X_test = df_test[feature_cols]

        if algorithm == 'xgb':
            raw_model, best_params = self._train_xgb(X_train, y_train, X_val, y_val)
        else:
            raw_model, best_params = self._train_rf(X_train, y_train, X_val, y_val)

        # Probability calibration on validation set only (avoids data leakage
        # since GridSearchCV already used cross-validation on the training set)
        model = _CalibratedModel(raw_model, X_val, y_val)

        # Evaluate on test set only (val was used implicitly via GridSearchCV)
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        metrics = self.metrics_service.compute_metrics(y_test, y_pred, y_prob)
        metrics['confusion_matrix'] = self.metrics_service.confusion_matrix_data(y_test, y_pred)
        metrics['roc_curve'] = self.metrics_service.roc_curve_data(y_test, y_prob)
        metrics['feature_importances'] = self.metrics_service.feature_importance_data(
            model, feature_cols
        )
        metrics['training_params'] = best_params

        # New banking metrics
        metrics['gini_coefficient'] = self.metrics_service.compute_gini(y_test, y_prob)
        ks_result = self.metrics_service.compute_ks_statistic(y_test, y_prob)
        metrics['ks_statistic'] = ks_result['ks_statistic']
        metrics['log_loss'] = self.metrics_service.compute_log_loss(y_test, y_prob)
        metrics['calibration_data'] = self.metrics_service.compute_calibration_data(y_test, y_prob)
        metrics['threshold_analysis'] = self.metrics_service.compute_threshold_analysis(y_test, y_prob)
        metrics['decile_analysis'] = self.metrics_service.compute_decile_analysis(y_test, y_prob)

        # Overfitting detection — derive predictions from probabilities
        # to avoid a redundant full inference pass on the training set
        y_train_pred_prob = model.predict_proba(X_train)[:, 1]
        train_auc = round(float(roc_auc_score(y_train, y_train_pred_prob)), 4)
        test_auc = metrics['auc_roc']
        overfitting_gap = round(train_auc - test_auc, 4)
        if overfitting_gap > 0.05:
            logger.warning(
                "Overfitting detected: train AUC %.4f vs test AUC %.4f (gap: %.4f)",
                train_auc, test_auc, overfitting_gap,
            )

        training_time = round(time.time() - start_time, 2)
        metrics['training_time_seconds'] = training_time
        metrics['training_metadata'] = {
            'train_size': len(y_train),
            'val_size': len(y_val),
            'test_size': len(y_test),
            'class_balance': round(float(y.mean()), 4),
            'training_time_seconds': training_time,
            'overfitting_gap': overfitting_gap,
            'train_auc': round(train_auc, 4),
            'n_features': len(feature_cols),
        }

        # Fairness metrics with full TPR/FPR/disparate impact
        fairness_metrics = {}
        for col in ['employment_type', 'applicant_type']:
            if col in df.columns:
                test_indices = test_original_indices
                original_vals = df.loc[test_indices, col] if col in df.columns else pd.Series()
                if len(original_vals) > 0:
                    fairness_result = self.metrics_service.compute_fairness_metrics(
                        y_test.values, y_pred, y_prob, original_vals.values
                    )
                    fairness_metrics[col] = fairness_result
        metrics['fairness'] = fairness_metrics

        return model, metrics

    def _train_rf(self, X_train, y_train, X_val, y_val):
        """Train Random Forest with GridSearchCV."""
        param_grid = {
            'n_estimators': [100, 200],
            'max_depth': [10, 20, None],
            'min_samples_split': [2, 5],
        }
        rf = RandomForestClassifier(random_state=42, class_weight='balanced')
        grid = GridSearchCV(rf, param_grid, cv=5, scoring='f1', n_jobs=-1, verbose=0)
        grid.fit(X_train, y_train)
        return grid.best_estimator_, grid.best_params_

    def _train_xgb(self, X_train, y_train, X_val, y_val):
        """Train XGBoost with RandomizedSearchCV, class imbalance handling, and early stopping."""
        from xgboost import XGBClassifier

        # Handle class imbalance
        neg_count = int((y_train == 0).sum())
        pos_count = int((y_train == 1).sum())
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

        param_grid = {
            'n_estimators': [100, 200, 300],
            'max_depth': [3, 6, 9],
            'learning_rate': [0.01, 0.1],
            'subsample': [0.8, 1.0],
            'min_child_weight': [1, 5],
            'colsample_bytree': [0.8, 1.0],
            'reg_alpha': [0, 0.1],
            'reg_lambda': [1, 5],
        }
        # n_jobs=1 here so XGBoost does NOT spawn its own thread pool
        # inside each RandomizedSearchCV worker (n_jobs=-1 below).
        # Without this, N sklearn workers × N XGBoost threads causes
        # thread oversubscription and makes training slower, not faster.
        xgb = XGBClassifier(
            random_state=42,
            eval_metric='logloss',
            scale_pos_weight=scale_pos_weight,
            n_jobs=1,
        )
        search = RandomizedSearchCV(
            xgb, param_grid, n_iter=50, cv=3, scoring='f1',
            n_jobs=-1, verbose=0, random_state=42,
        )
        search.fit(X_train, y_train)
        best_params = search.best_params_

        # Refit with early stopping using validation set.
        # n_jobs=-1 is safe here: single model, use all cores for tree building.
        final_model = XGBClassifier(
            **best_params,
            random_state=42,
            eval_metric='logloss',
            scale_pos_weight=scale_pos_weight,
            early_stopping_rounds=20,
            n_jobs=-1,
        )
        final_model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        return final_model, best_params

    def save_model(self, model, path):
        """Save model bundle (model, scaler, column names) to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bundle = {
            'model': model,
            'scaler': self.scaler,
            'feature_cols': self.ohe_columns,
            'categorical_cols': self.CATEGORICAL_COLS,
            'numeric_cols': self.NUMERIC_COLS,
        }
        joblib.dump(bundle, path)
        return path
