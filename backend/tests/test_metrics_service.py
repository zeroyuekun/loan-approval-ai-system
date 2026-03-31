"""Tests for MetricsService — pure Python with numpy, no Django DB needed."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from apps.ml_engine.services.metrics import MetricsService


@pytest.fixture(scope="module")
def svc():
    return MetricsService()


@pytest.fixture(scope="module")
def known_data():
    """Generate reproducible binary classification data with good separation."""
    np.random.seed(42)
    y_true = np.array([1] * 50 + [0] * 50)
    y_prob = np.concatenate(
        [
            np.random.uniform(0.6, 1.0, 50),
            np.random.uniform(0.0, 0.4, 50),
        ]
    )
    y_pred = (y_prob >= 0.5).astype(int)
    return y_true, y_pred, y_prob


@pytest.fixture(scope="module")
def perfect_data():
    """Perfect classifier: probabilities exactly match labels."""
    y_true = np.array([1] * 50 + [0] * 50)
    y_prob = np.array([1.0] * 50 + [0.0] * 50)
    y_pred = y_true.copy()
    return y_true, y_pred, y_prob


@pytest.fixture(scope="module")
def random_data():
    """Random classifier: probabilities are uninformative."""
    np.random.seed(99)
    y_true = np.array([1] * 50 + [0] * 50)
    y_prob = np.random.uniform(0.0, 1.0, 100)
    y_pred = (y_prob >= 0.5).astype(int)
    return y_true, y_pred, y_prob


# ── compute_metrics ──────────────────────────────────────────────────


class TestComputeMetrics:
    def test_returns_all_keys(self, svc, known_data):
        y_true, y_pred, y_prob = known_data
        result = svc.compute_metrics(y_true, y_pred, y_prob)
        expected_keys = {"accuracy", "precision", "recall", "f1_score", "auc_roc", "brier_score"}
        assert set(result.keys()) == expected_keys

    def test_values_are_floats_in_range(self, svc, known_data):
        y_true, y_pred, y_prob = known_data
        result = svc.compute_metrics(y_true, y_pred, y_prob)
        for key, val in result.items():
            assert isinstance(val, float), f"{key} is not float"
            assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"

    def test_well_separated_data_has_high_accuracy(self, svc, known_data):
        y_true, y_pred, y_prob = known_data
        result = svc.compute_metrics(y_true, y_pred, y_prob)
        assert result["accuracy"] >= 0.90
        assert result["auc_roc"] >= 0.95

    def test_perfect_classifier(self, svc, perfect_data):
        y_true, y_pred, y_prob = perfect_data
        result = svc.compute_metrics(y_true, y_pred, y_prob)
        assert result["accuracy"] == 1.0
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1_score"] == 1.0
        assert result["auc_roc"] == 1.0
        assert result["brier_score"] == 0.0


# ── confusion_matrix_data ────────────────────────────────────────────


class TestConfusionMatrixData:
    def test_returns_expected_keys(self, svc, known_data):
        y_true, y_pred, _ = known_data
        result = svc.confusion_matrix_data(y_true, y_pred)
        assert set(result.keys()) == {
            "true_negatives",
            "false_positives",
            "false_negatives",
            "true_positives",
            "matrix",
        }

    def test_matrix_is_2x2(self, svc, known_data):
        y_true, y_pred, _ = known_data
        result = svc.confusion_matrix_data(y_true, y_pred)
        matrix = result["matrix"]
        assert len(matrix) == 2
        assert all(len(row) == 2 for row in matrix)

    def test_counts_sum_to_total(self, svc, known_data):
        y_true, y_pred, _ = known_data
        result = svc.confusion_matrix_data(y_true, y_pred)
        total = (
            result["true_negatives"] + result["false_positives"] + result["false_negatives"] + result["true_positives"]
        )
        assert total == len(y_true)

    def test_perfect_classifier_has_no_errors(self, svc, perfect_data):
        y_true, y_pred, _ = perfect_data
        result = svc.confusion_matrix_data(y_true, y_pred)
        assert result["false_positives"] == 0
        assert result["false_negatives"] == 0


# ── roc_curve_data ───────────────────────────────────────────────────


class TestRocCurveData:
    def test_returns_expected_keys(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.roc_curve_data(y_true, y_prob)
        assert set(result.keys()) == {"fpr", "tpr", "thresholds", "auc"}

    def test_fpr_tpr_endpoints(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.roc_curve_data(y_true, y_prob)
        assert result["fpr"][0] == 0.0
        assert result["tpr"][0] == 0.0
        assert result["fpr"][-1] == 1.0
        assert result["tpr"][-1] == 1.0

    def test_auc_high_for_good_classifier(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.roc_curve_data(y_true, y_prob)
        assert result["auc"] >= 0.95


# ── feature_importance_data ──────────────────────────────────────────


class TestFeatureImportanceData:
    def test_sorted_descending(self, svc):
        model = MagicMock()
        model.feature_importances_ = np.array([0.1, 0.5, 0.3, 0.05, 0.05])
        names = ["a", "b", "c", "d", "e"]
        result = svc.feature_importance_data(model, names)
        importances = [item["importance"] for item in result]
        assert importances == sorted(importances, reverse=True)
        assert result[0]["feature"] == "b"

    def test_returns_empty_for_model_without_importances(self, svc):
        model = MagicMock(spec=[])  # no feature_importances_ attr
        result = svc.feature_importance_data(model, ["a", "b"])
        assert result == []

    def test_dict_format(self, svc):
        model = MagicMock()
        model.feature_importances_ = np.array([0.7, 0.3])
        result = svc.feature_importance_data(model, ["income", "age"])
        for item in result:
            assert "feature" in item
            assert "importance" in item
            assert isinstance(item["importance"], float)


# ── compute_gini ─────────────────────────────────────────────────────


class TestComputeGini:
    def test_perfect_classifier_gini_is_one(self, svc, perfect_data):
        y_true, _, y_prob = perfect_data
        assert svc.compute_gini(y_true, y_prob) == 1.0

    def test_gini_equals_2auc_minus_1(self, svc, known_data):
        y_true, _, y_prob = known_data
        roc = svc.roc_curve_data(y_true, y_prob)
        expected = round(2 * roc["auc"] - 1, 4)
        assert svc.compute_gini(y_true, y_prob) == expected


# ── compute_ks_statistic ─────────────────────────────────────────────


class TestComputeKS:
    def test_returns_expected_keys(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_ks_statistic(y_true, y_prob)
        assert "ks_statistic" in result
        assert "ks_threshold" in result

    def test_ks_between_0_and_1(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_ks_statistic(y_true, y_prob)
        assert 0.0 <= result["ks_statistic"] <= 1.0

    def test_perfect_classifier_ks_is_one(self, svc, perfect_data):
        y_true, _, y_prob = perfect_data
        result = svc.compute_ks_statistic(y_true, y_prob)
        assert result["ks_statistic"] == 1.0


# ── compute_log_loss ─────────────────────────────────────────────────


class TestComputeLogLoss:
    def test_returns_float(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_log_loss(y_true, y_prob)
        assert isinstance(result, float)

    def test_good_classifier_has_low_log_loss(self, svc, known_data):
        y_true, _, y_prob = known_data
        assert svc.compute_log_loss(y_true, y_prob) < 0.5


# ── compute_calibration_data ─────────────────────────────────────────


class TestComputeCalibrationData:
    def test_returns_expected_keys(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_calibration_data(y_true, y_prob)
        assert set(result.keys()) == {
            "fraction_of_positives",
            "mean_predicted_value",
            "ece",
            "n_bins",
        }

    def test_n_bins_passthrough(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_calibration_data(y_true, y_prob, n_bins=5)
        assert result["n_bins"] == 5

    def test_ece_is_non_negative(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_calibration_data(y_true, y_prob)
        assert result["ece"] >= 0.0


# ── compute_threshold_analysis ───────────────────────────────────────


class TestComputeThresholdAnalysis:
    def test_sweep_has_91_entries(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_threshold_analysis(y_true, y_prob)
        assert len(result["sweep"]) == 91

    def test_sweep_thresholds_range(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_threshold_analysis(y_true, y_prob)
        thresholds = [entry["threshold"] for entry in result["sweep"]]
        assert thresholds[0] == 0.05
        assert thresholds[-1] == 0.95

    def test_optimal_thresholds_present(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_threshold_analysis(y_true, y_prob)
        assert "f1_optimal_threshold" in result
        assert "youden_j_threshold" in result
        assert "cost_optimal_threshold" in result

    def test_optimal_thresholds_are_valid_sweep_values(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_threshold_analysis(y_true, y_prob)
        valid_thresholds = {entry["threshold"] for entry in result["sweep"]}
        assert result["f1_optimal_threshold"] in valid_thresholds
        assert result["youden_j_threshold"] in valid_thresholds
        assert result["cost_optimal_threshold"] in valid_thresholds

    def test_sweep_entry_keys(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_threshold_analysis(y_true, y_prob)
        expected_keys = {"threshold", "precision", "recall", "f1", "fpr", "approval_rate"}
        for entry in result["sweep"]:
            assert set(entry.keys()) == expected_keys


# ── compute_decile_analysis ──────────────────────────────────────────


class TestComputeDecileAnalysis:
    def test_returns_10_deciles(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_decile_analysis(y_true, y_prob)
        assert len(result["deciles"]) == 10

    def test_decile_numbering(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_decile_analysis(y_true, y_prob)
        decile_nums = [d["decile"] for d in result["deciles"]]
        assert decile_nums == list(range(1, 11))

    def test_decile_entry_keys(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_decile_analysis(y_true, y_prob)
        expected_keys = {"decile", "count", "actual_rate", "cumulative_rate", "lift"}
        for d in result["deciles"]:
            assert set(d.keys()) == expected_keys

    def test_counts_sum_to_total(self, svc, known_data):
        y_true, _, y_prob = known_data
        result = svc.compute_decile_analysis(y_true, y_prob)
        total_count = sum(d["count"] for d in result["deciles"])
        assert total_count == len(y_true)

    def test_top_decile_has_highest_lift(self, svc, known_data):
        """Decile 10 (highest predicted prob) should have the highest lift."""
        y_true, _, y_prob = known_data
        result = svc.compute_decile_analysis(y_true, y_prob)
        lifts = [d["lift"] for d in result["deciles"]]
        assert lifts[-1] == max(lifts)
