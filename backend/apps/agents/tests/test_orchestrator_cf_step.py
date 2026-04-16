"""Tests for the orchestrator counterfactual generation step.

These tests verify that PipelineOrchestrator._run_counterfactual_step:
1. Calls CounterfactualEngine and returns results when prediction is "denied"
2. Returns [] without calling CounterfactualEngine when prediction is "approved"
3. Returns [] and logs warning when CounterfactualEngine raises an exception
"""

import logging
from unittest.mock import MagicMock, patch

import pandas as pd


@patch("apps.agents.services.orchestrator.CounterfactualEngine")
class TestRunCounterfactualStep:
    """Unit tests for _run_counterfactual_step on PipelineOrchestrator."""

    def _make_orchestrator(self):
        from apps.agents.services.orchestrator import PipelineOrchestrator

        return PipelineOrchestrator()

    def _denied_prediction_result(self):
        features_df = pd.DataFrame([{
            "annual_income": 30000.0,
            "credit_score": 400,
            "loan_amount": 200000.0,
            "loan_term_months": 36,
            "debt_to_income": 8.0,
            "employment_length": 1,
            "has_cosigner": 0,
            "monthly_expenses": 5000.0,
        }])
        return {
            "prediction": "denied",
            "probability": 0.25,
            "threshold_used": 0.5,
            "_features_df": features_df,
            "feature_importances": {"credit_score": 0.3, "annual_income": 0.2},
            "shap_values": {"credit_score": -0.4, "annual_income": -0.2},
        }

    def _approved_prediction_result(self):
        features_df = pd.DataFrame([{
            "annual_income": 200000.0,
            "credit_score": 1100,
            "loan_amount": 10000.0,
            "loan_term_months": 60,
            "debt_to_income": 1.5,
            "employment_length": 20,
            "has_cosigner": 1,
            "monthly_expenses": 2000.0,
        }])
        return {
            "prediction": "approved",
            "probability": 0.95,
            "threshold_used": 0.5,
            "_features_df": features_df,
            "feature_importances": {"credit_score": 0.3, "annual_income": 0.2},
            "shap_values": {"credit_score": 0.4, "annual_income": 0.2},
        }

    def _mock_predictor(self):
        predictor = MagicMock()
        predictor.model = MagicMock()
        predictor.feature_cols = ["annual_income", "credit_score", "loan_amount"]
        predictor.model_version = MagicMock()
        predictor.model_version.optimal_threshold = 0.5
        return predictor

    def test_calls_engine_and_returns_results_for_denied(self, MockCFEngine):
        """When prediction is denied, CounterfactualEngine is instantiated and
        generate() is called. Results are returned."""
        mock_engine_instance = MagicMock()
        mock_engine_instance.generate.return_value = [
            {"changes": {"loan_amount": 50000.0}, "statement": "Reduce your loan amount"},
        ]
        MockCFEngine.return_value = mock_engine_instance

        orch = self._make_orchestrator()
        pred_result = self._denied_prediction_result()
        predictor = self._mock_predictor()

        result = orch._run_counterfactual_step(
            prediction_result=pred_result,
            predictor=predictor,
            original_loan_amount=200000.0,
        )

        MockCFEngine.assert_called_once()
        mock_engine_instance.generate.assert_called_once()
        assert len(result) == 1
        assert result[0]["changes"]["loan_amount"] == 50000.0

    def test_returns_empty_without_calling_engine_for_approved(self, MockCFEngine):
        """When prediction is approved, CounterfactualEngine is NOT created and
        an empty list is returned."""
        orch = self._make_orchestrator()
        pred_result = self._approved_prediction_result()
        predictor = self._mock_predictor()

        result = orch._run_counterfactual_step(
            prediction_result=pred_result,
            predictor=predictor,
            original_loan_amount=10000.0,
        )

        MockCFEngine.assert_not_called()
        assert result == []

    def test_returns_empty_and_logs_warning_on_exception(self, MockCFEngine, caplog):
        """When CounterfactualEngine raises, the step catches the exception,
        logs a warning, and returns []."""
        MockCFEngine.side_effect = RuntimeError("DiCE exploded")

        orch = self._make_orchestrator()
        pred_result = self._denied_prediction_result()
        predictor = self._mock_predictor()

        with caplog.at_level(logging.WARNING, logger="agents.orchestrator"):
            result = orch._run_counterfactual_step(
                prediction_result=pred_result,
                predictor=predictor,
                original_loan_amount=200000.0,
            )

        assert result == []
        assert any("counterfactual" in rec.message.lower() for rec in caplog.records)
