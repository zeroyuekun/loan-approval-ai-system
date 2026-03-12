import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler

from .metrics import MetricsService


class ModelTrainer:
    """Trains ML models for loan approval prediction."""

    CATEGORICAL_COLS = ['purpose', 'home_ownership']
    NUMERIC_COLS = [
        'annual_income', 'credit_score', 'loan_amount', 'loan_term_months',
        'debt_to_income', 'employment_length', 'has_cosigner',
    ]

    def __init__(self):
        self.scaler = StandardScaler()
        self.label_encoders = {}
        self.metrics_service = MetricsService()

    def preprocess(self, df):
        """Encode categoricals and scale numerics."""
        df = df.copy()

        # Encode categorical columns
        for col in self.CATEGORICAL_COLS:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            self.label_encoders[col] = le

        # Scale numeric columns (including encoded categoricals)
        feature_cols = self.NUMERIC_COLS + self.CATEGORICAL_COLS
        df[feature_cols] = self.scaler.fit_transform(df[feature_cols])

        return df, feature_cols

    def train(self, data_path, algorithm='xgb'):
        """Train model with GridSearchCV and return model + metrics."""
        start_time = time.time()

        # Load and preprocess
        df = pd.read_csv(data_path)
        df, feature_cols = self.preprocess(df)

        X = df[feature_cols]
        y = df['approved']

        # 80/10/10 split
        X_train, X_temp, y_train, y_temp = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        X_val, X_test, y_val, y_test = train_test_split(
            X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
        )

        if algorithm == 'xgb':
            model, best_params = self._train_xgb(X_train, y_train, X_val, y_val)
        else:
            model, best_params = self._train_rf(X_train, y_train, X_val, y_val)

        # Evaluate on combined val+test
        X_eval = pd.concat([X_val, X_test])
        y_eval = pd.concat([y_val, y_test])
        y_pred = model.predict(X_eval)
        y_prob = model.predict_proba(X_eval)[:, 1]

        metrics = self.metrics_service.compute_metrics(y_eval, y_pred, y_prob)
        metrics['confusion_matrix'] = self.metrics_service.confusion_matrix_data(y_eval, y_pred)
        metrics['roc_curve'] = self.metrics_service.roc_curve_data(y_eval, y_prob)
        metrics['feature_importances'] = self.metrics_service.feature_importance_data(
            model, feature_cols
        )
        metrics['training_params'] = best_params
        metrics['training_time_seconds'] = round(time.time() - start_time, 2)

        return model, metrics

    def _train_rf(self, X_train, y_train, X_val, y_val):
        """Train Random Forest with GridSearchCV."""
        param_grid = {
            'n_estimators': [100, 200],
            'max_depth': [10, 20, None],
            'min_samples_split': [2, 5],
        }
        rf = RandomForestClassifier(random_state=42)
        grid = GridSearchCV(rf, param_grid, cv=3, scoring='f1', n_jobs=-1, verbose=0)
        grid.fit(X_train, y_train)
        return grid.best_estimator_, grid.best_params_

    def _train_xgb(self, X_train, y_train, X_val, y_val):
        """Train XGBoost with GridSearchCV."""
        from xgboost import XGBClassifier

        param_grid = {
            'n_estimators': [100, 200],
            'max_depth': [3, 6, 10],
            'learning_rate': [0.01, 0.1],
            'subsample': [0.8, 1.0],
        }
        xgb = XGBClassifier(
            random_state=42, eval_metric='logloss', use_label_encoder=False
        )
        grid = GridSearchCV(xgb, param_grid, cv=3, scoring='f1', n_jobs=-1, verbose=0)
        grid.fit(X_train, y_train)
        return grid.best_estimator_, grid.best_params_

    def save_model(self, model, path):
        """Save model bundle (model, scaler, encoders) to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bundle = {
            'model': model,
            'scaler': self.scaler,
            'label_encoders': self.label_encoders,
            'feature_cols': self.NUMERIC_COLS + self.CATEGORICAL_COLS,
        }
        joblib.dump(bundle, path)
        return path
