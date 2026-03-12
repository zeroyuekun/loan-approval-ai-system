import time

import joblib
import numpy as np
import pandas as pd

from apps.ml_engine.models import ModelVersion


class ModelPredictor:
    """Loads the active model and makes predictions on loan applications."""

    def __init__(self):
        self.model_version = ModelVersion.objects.filter(is_active=True).first()
        if not self.model_version:
            raise ValueError("No active model version found. Train a model first.")

        bundle = joblib.load(self.model_version.file_path)
        self.model = bundle['model']
        self.scaler = bundle['scaler']
        self.label_encoders = bundle['label_encoders']
        self.feature_cols = bundle['feature_cols']

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
        }

        df = pd.DataFrame([features])

        # Encode categoricals
        for col, le in self.label_encoders.items():
            if col in df.columns:
                # Handle unseen labels gracefully
                known_classes = set(le.classes_)
                df[col] = df[col].apply(
                    lambda x: x if x in known_classes else le.classes_[0]
                )
                df[col] = le.transform(df[col].astype(str))

        # Scale features
        df[self.feature_cols] = self.scaler.transform(df[self.feature_cols])

        # Predict
        prediction = self.model.predict(df[self.feature_cols])[0]
        probabilities = self.model.predict_proba(df[self.feature_cols])[0]

        # Feature importances for this prediction
        importances = {}
        if hasattr(self.model, 'feature_importances_'):
            for name, imp in zip(self.feature_cols, self.model.feature_importances_):
                importances[name] = round(float(imp), 4)

        processing_time = int((time.time() - start_time) * 1000)

        return {
            'prediction': 'approved' if prediction == 1 else 'denied',
            'probability': round(float(probabilities[1]), 4),
            'feature_importances': importances,
            'processing_time_ms': processing_time,
            'model_version': str(self.model_version.id),
        }
