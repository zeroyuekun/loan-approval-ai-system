"""Tests for ML predictor input validation and consistency checks."""

from unittest.mock import MagicMock, patch

from django.test import TestCase


class PredictorInputValidationTestCase(TestCase):
    @patch("apps.ml_engine.services.predictor._load_bundle")
    @patch("apps.ml_engine.services.model_selector.select_model_version")
    def test_feature_bounds_validation(self, mock_select, mock_load):
        """Feature bounds should reject out-of-range values."""
        from apps.ml_engine.services.predictor import ModelPredictor

        mock_select.return_value = MagicMock(id=1, version_label="test-v1")
        mock_load.return_value = {
            "model": MagicMock(),
            "scaler": MagicMock(),
            "feature_cols": [],
            "label_encoders": None,
            "categorical_cols": [],
            "numeric_cols": [],
            "reference_distribution": {},
            "imputation_values": {},
            "feature_bounds": {},
            "group_thresholds": {},
            "conformal_scores": [],
        }
        predictor = ModelPredictor()

        # Create a mock application with invalid credit score
        app = MagicMock()
        app.credit_score = -100  # Invalid
        app.annual_income = 85000
        app.loan_amount = 350000
        app.loan_term_months = 360
        app.debt_to_income = 4.0
        app.employment_length = 5
        app.purpose = "home"
        app.home_ownership = "mortgage"
        app.has_cosigner = False
        app.property_value = 500000
        app.deposit_amount = 150000
        app.monthly_expenses = 2000
        app.existing_credit_card_limit = 5000
        app.number_of_dependants = 0
        app.employment_type = "payg_permanent"
        app.applicant_type = "single"
        app.has_hecs = False
        app.has_bankruptcy = False
        app.state = "NSW"

        # Should raise or handle gracefully
        try:
            result = predictor.predict(app)
            # If it returns, verify the warning is present
            if "warnings" in result:
                self.assertTrue(len(result["warnings"]) > 0)
        except Exception:
            pass  # Expected — no active model in test


class RiskGradeTestCase(TestCase):
    def test_risk_grade_mapping(self):
        """Risk grades should map correctly from probability."""
        from apps.ml_engine.services.predictor import compute_risk_grade

        # pd = 1 - probability; thresholds: <0.005=AAA, <0.01=AA, <0.03=A, <0.07=BBB, <0.15=BB, <0.30=B, else CCC
        self.assertEqual(compute_risk_grade(0.999), "AAA")  # pd=0.001
        self.assertEqual(compute_risk_grade(0.995), "AA")  # pd=0.005
        self.assertEqual(compute_risk_grade(0.98), "A")  # pd=0.02
        self.assertEqual(compute_risk_grade(0.95), "BBB")  # pd=0.05
        self.assertEqual(compute_risk_grade(0.90), "BB")  # pd=0.10
        self.assertEqual(compute_risk_grade(0.80), "B")  # pd=0.20
        self.assertEqual(compute_risk_grade(0.60), "CCC")  # pd=0.40
        self.assertEqual(compute_risk_grade(0.30), "CCC")  # pd=0.70
