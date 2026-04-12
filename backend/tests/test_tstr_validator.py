"""Tests for TSTRValidator — APRA fidelity, real-world AUC estimation, and end-to-end validate().

These tests prove specific bugs exist BEFORE fixes are applied:
- Zero NPL rate handling (rel_err defaults to 1.0, penalty capped at 0.03)
- All-defaults edge case (AUC cannot be computed)
- Boundary AUC=0.5 should not be used as measured (random classifier)
"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from apps.ml_engine.services.tstr_validator import TSTRValidator


class TestComputeApraFidelity:
    """Tests for TSTRValidator.compute_apra_fidelity"""

    def setup_method(self):
        self.validator = TSTRValidator()
        self.base_metrics = {"auc_roc": 0.87}

    def _make_test_df(self, n=200, default_rate=0.02):
        """Helper: create a df_test_raw with actual_outcome column."""
        outcomes = ["current"] * int(n * (1 - default_rate)) + ["default"] * int(n * default_rate)
        # Pad to exact length
        while len(outcomes) < n:
            outcomes.append("current")
        return pd.DataFrame({"actual_outcome": outcomes[:n]})

    def _make_y_prob(self, n=200):
        """Helper: create approval probabilities."""
        return np.random.RandomState(42).uniform(0.3, 0.95, n)

    @patch("apps.ml_engine.services.macro_data_service.MacroDataService")
    def test_happy_path_returns_all_signals(self, MockMacro):
        """Verify all 3 signals returned when data is complete."""
        MockMacro.return_value.get_apra_quarterly_arrears.return_value = {
            "npl_rate": 0.02, "quarter": "2025Q4", "published_date": "2026-01-15",
            "total_arrears_rate": 0.03,
        }
        df = self._make_test_df(200, default_rate=0.02)
        y_prob = self._make_y_prob(200)
        result = self.validator.compute_apra_fidelity(self.base_metrics, y_prob, df)
        assert result["available"] is True
        assert "synthetic_default_rate" in result
        assert "apra_fidelity_penalty" in result
        assert result["apra_npl_rate"] == 0.02

    @patch("apps.ml_engine.services.macro_data_service.MacroDataService")
    def test_macro_service_raises_returns_unavailable(self, MockMacro):
        """Graceful degradation when MacroDataService raises."""
        MockMacro.return_value.get_apra_quarterly_arrears.side_effect = RuntimeError("API down")
        result = self.validator.compute_apra_fidelity(self.base_metrics, None, None)
        assert result["available"] is False

    @patch("apps.ml_engine.services.macro_data_service.MacroDataService")
    def test_missing_actual_outcome_column(self, MockMacro):
        MockMacro.return_value.get_apra_quarterly_arrears.return_value = {"npl_rate": 0.02}
        df = pd.DataFrame({"some_col": [1, 2, 3]})
        result = self.validator.compute_apra_fidelity(self.base_metrics, None, df)
        assert result["available"] is False
        assert "actual_outcome" in result.get("reason", "")

    @patch("apps.ml_engine.services.macro_data_service.MacroDataService")
    def test_zero_npl_rate_rel_err_defaults_to_one(self, MockMacro):
        """When APRA NPL is 0, rel_err defaults to 1.0 -- poorly-aligned."""
        MockMacro.return_value.get_apra_quarterly_arrears.return_value = {
            "npl_rate": 0.0, "quarter": "2025Q4",
        }
        df = self._make_test_df(200, default_rate=0.05)
        y_prob = self._make_y_prob(200)
        result = self.validator.compute_apra_fidelity(self.base_metrics, y_prob, df)
        assert result["available"] is True
        assert result["data_fidelity_relative_error"] is None
        assert result["data_fidelity_interpretation"] == "poorly-aligned"
        # Penalty should be capped at 0.03
        assert result["apra_fidelity_penalty"] == 0.03

    @patch("apps.ml_engine.services.macro_data_service.MacroDataService")
    def test_all_defaults_no_auc(self, MockMacro):
        """When all outcomes are default, AUC cannot be computed."""
        MockMacro.return_value.get_apra_quarterly_arrears.return_value = {"npl_rate": 0.02}
        df = pd.DataFrame({"actual_outcome": ["default"] * 100})
        y_prob = np.random.uniform(0.1, 0.9, 100)
        result = self.validator.compute_apra_fidelity(self.base_metrics, y_prob, df)
        assert result["actual_default_auc"] is None


class TestEstimateRealWorldAuc:

    def setup_method(self):
        self.validator = TSTRValidator()

    def test_with_measured_actual_default_auc(self):
        """When actual_default_auc is available, it should be used directly."""
        metrics = {"auc_roc": 0.87, "training_metadata": {}}
        apra = {"available": True, "actual_default_auc": 0.82, "apra_fidelity_penalty": 0.01,
                "apra_quarter": "2025Q4", "synthetic_default_rate": 0.02,
                "apra_npl_rate": 0.02, "data_fidelity_interpretation": "well-aligned"}
        result = self.validator.estimate_real_world_auc(metrics, apra_fidelity=apra)
        assert result["estimate_source"] == "measured_actual_default_auc"
        assert result["estimated_real_auc"] == 0.82

    def test_degradation_only_without_apra(self):
        """Without APRA data, uses literature-based degradation."""
        metrics = {"auc_roc": 0.87, "training_metadata": {"overfitting_gap": 0.01, "cv_auc_std": 0.01}}
        result = self.validator.estimate_real_world_auc(metrics)
        assert result["estimate_source"] == "degradation_heuristic"
        assert result["estimated_real_auc"] < 0.87  # degradation applied

    def test_actual_default_auc_at_boundary_0_5(self):
        """AUC exactly 0.5 should NOT be used as measured (random classifier)."""
        metrics = {"auc_roc": 0.87}
        apra = {"available": True, "actual_default_auc": 0.5}
        result = self.validator.estimate_real_world_auc(metrics, apra_fidelity=apra)
        assert result["estimate_source"] == "degradation_heuristic"


class TestValidateEndToEnd:

    def setup_method(self):
        self.validator = TSTRValidator()

    @patch("apps.ml_engine.services.macro_data_service.MacroDataService")
    def test_validate_returns_all_sections(self, MockMacro):
        MockMacro.return_value.get_apra_quarterly_arrears.return_value = {
            "npl_rate": 0.02, "quarter": "2025Q4",
        }
        metrics = {"auc_roc": 0.85, "training_metadata": {"cv_auc_std": 0.015, "overfitting_gap": 0.02}}
        df = pd.DataFrame({"actual_outcome": ["current"] * 180 + ["default"] * 20})
        y_prob = np.random.RandomState(42).uniform(0.3, 0.95, 200)
        result = self.validator.validate(metrics, y_prob=y_prob, df_test_raw=df)
        assert "estimated_real_world_auc" in result
        assert "synthetic_confidence" in result
        assert "apra_fidelity" in result
        assert "summary" in result
