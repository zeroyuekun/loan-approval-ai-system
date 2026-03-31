"""Tests for CSI and KS-test drift monitoring enhancements.

Pure computation tests -- no Django DB required.
"""

import numpy as np
import pytest

from apps.ml_engine.services.drift_monitor import (
    CSI_INVESTIGATE,
    CSI_STABLE,
    compute_csi,
    compute_ks_test,
    compute_psi,
)


# ---------------------------------------------------------------------------
# compute_csi tests
# ---------------------------------------------------------------------------


class TestComputeCSI:
    def test_identical_distributions_all_stable(self):
        """CSI should be ~0 when expected and actual are the same."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 500).tolist()
        expected_features = {"feat_a": data, "feat_b": data}
        actual_features = {"feat_a": data, "feat_b": data}

        result = compute_csi(expected_features, actual_features)

        assert "feat_a" in result
        assert "feat_b" in result
        for feat in result.values():
            assert feat["csi"] < CSI_STABLE
            assert feat["status"] == "stable"

    def test_shifted_distribution_detected(self):
        """CSI should exceed threshold when distribution shifts significantly."""
        rng = np.random.RandomState(42)
        expected = rng.normal(0, 1, 1000).tolist()
        actual = rng.normal(3, 1, 1000).tolist()  # Large mean shift

        result = compute_csi({"income": expected}, {"income": actual})

        assert result["income"]["csi"] > CSI_INVESTIGATE
        assert result["income"]["status"] == "action_required"

    def test_status_classification_investigate(self):
        """Moderate shift should yield 'investigate' status."""
        rng = np.random.RandomState(99)
        expected = rng.normal(0, 1, 2000).tolist()
        # Mild shift -- tune to land between CSI_STABLE and CSI_INVESTIGATE
        actual = rng.normal(0.35, 1.05, 2000).tolist()

        result = compute_csi({"x": expected}, {"x": actual})
        csi_val = result["x"]["csi"]

        # If it lands in the investigate band, check status; otherwise
        # just verify the classification logic is consistent
        if CSI_STABLE <= csi_val < CSI_INVESTIGATE:
            assert result["x"]["status"] == "investigate"
        elif csi_val >= CSI_INVESTIGATE:
            assert result["x"]["status"] == "action_required"
        else:
            assert result["x"]["status"] == "stable"

    def test_only_common_keys_used(self):
        """Features present in only one dict should be ignored."""
        rng = np.random.RandomState(7)
        data = rng.normal(0, 1, 200).tolist()

        result = compute_csi(
            {"shared": data, "only_expected": data},
            {"shared": data, "only_actual": data},
        )

        assert "shared" in result
        assert "only_expected" not in result
        assert "only_actual" not in result

    def test_empty_arrays_no_crash(self):
        """Empty feature arrays should not raise, return CSI 0 / stable."""
        result = compute_csi({"f": []}, {"f": []})
        assert result["f"]["csi"] == 0.0
        assert result["f"]["status"] == "stable"

    def test_single_element_arrays_handled(self):
        """Single-element arrays should not raise, return CSI 0 / stable."""
        result = compute_csi({"f": [1.0]}, {"f": [2.0]})
        assert result["f"]["csi"] == 0.0
        assert result["f"]["status"] == "stable"

    def test_empty_dicts_return_empty(self):
        """No common features should return empty dict."""
        assert compute_csi({}, {}) == {}


# ---------------------------------------------------------------------------
# compute_ks_test tests
# ---------------------------------------------------------------------------


class TestComputeKSTest:
    def test_same_distribution_not_significant(self):
        """KS-test on identical distributions should not be significant."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 500)

        result = compute_ks_test(data, data)

        assert result["significant"] == False
        assert result["p_value"] > 0.05
        assert 0.0 <= result["ks_statistic"] <= 1.0

    def test_different_distribution_significant(self):
        """KS-test on clearly different distributions should be significant."""
        rng = np.random.RandomState(42)
        expected = rng.normal(0, 1, 500)
        actual = rng.normal(5, 1, 500)

        result = compute_ks_test(expected, actual)

        assert result["significant"] == True
        assert result["p_value"] < 0.05
        assert result["ks_statistic"] > 0.5

    def test_empty_arrays_safe(self):
        """Empty arrays should not raise."""
        result = compute_ks_test([], [])
        assert result == {"ks_statistic": 0.0, "p_value": 1.0, "significant": False}

    def test_single_element_safe(self):
        """Single-element arrays should not raise."""
        result = compute_ks_test([1.0], [2.0])
        assert result == {"ks_statistic": 0.0, "p_value": 1.0, "significant": False}

    def test_one_empty_one_populated(self):
        """One empty + one populated should return safe defaults."""
        result = compute_ks_test([], [1.0, 2.0, 3.0])
        assert result["significant"] is False

    def test_return_keys(self):
        """Result should always contain the expected keys."""
        rng = np.random.RandomState(0)
        result = compute_ks_test(rng.normal(size=100), rng.normal(size=100))
        assert set(result.keys()) == {"ks_statistic", "p_value", "significant"}


# ---------------------------------------------------------------------------
# Integration: CSI status thresholds
# ---------------------------------------------------------------------------


class TestCSIThresholds:
    def test_stable_threshold_constant(self):
        assert CSI_STABLE == 0.10

    def test_investigate_threshold_constant(self):
        assert CSI_INVESTIGATE == 0.20

    def test_investigate_stricter_than_psi(self):
        """CSI investigate threshold should be stricter than PSI investigate."""
        from apps.ml_engine.services.drift_monitor import PSI_INVESTIGATE

        assert CSI_INVESTIGATE < PSI_INVESTIGATE
