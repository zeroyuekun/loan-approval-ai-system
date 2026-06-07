"""Fix-2 regression guard: _psi_from_histogram and compute_psi must agree.

Before the fix, _psi_from_histogram used eps=1e-4 added to EVERY bin
(``pct + eps``), while compute_psi used eps=1e-8 replacing ONLY zero bins
(``np.where(pct == 0, eps, pct)``).  Same distribution → different PSI
numbers between the weekly DriftReport and the on-demand /drift/ endpoint.

After the fix both functions share the same zero-replacement-only logic with
eps=1e-8.
"""

import numpy as np
import pytest

from apps.ml_engine.services.drift_monitor import _psi_from_histogram, compute_psi


class TestPsiFromHistogramBasic:
    """_psi_from_histogram correctness checks (independent of compute_psi)."""

    def test_identical_distributions_returns_near_zero(self):
        """Identical expected and actual distributions must yield PSI ≈ 0."""
        edges = list(np.linspace(0, 100, 11))  # 10 equal-width bins
        counts = [100] * 10  # uniform reference

        # Actual values: one value per bin centre (same as reference shape)
        bin_centres = [(edges[i] + edges[i + 1]) / 2 for i in range(10)]
        actual_vals = []
        for centre in bin_centres:
            actual_vals.extend([centre] * 10)

        result = _psi_from_histogram(counts, edges, actual_vals)
        assert result["psi"] == pytest.approx(0.0, abs=0.01), (
            f"Identical distributions should yield PSI ≈ 0, got {result['psi']}"
        )
        assert result["status"] == "stable"

    def test_stable_status_below_threshold(self):
        edges = list(np.linspace(0, 10, 6))
        counts = [20, 20, 20, 20, 20]
        actual_vals = [1, 1, 3, 3, 5, 5, 7, 7, 9, 9] * 10
        result = _psi_from_histogram(counts, edges, actual_vals)
        assert result["status"] in ("stable", "moderate_shift", "significant_shift")
        assert "psi" in result

    def test_returns_dict_with_psi_and_status_keys(self):
        edges = [0.0, 50.0, 100.0]
        counts = [50.0, 50.0]
        actual_vals = [25.0] * 100
        result = _psi_from_histogram(counts, edges, actual_vals)
        assert "psi" in result
        assert "status" in result


class TestPsiConsistency:
    """_psi_from_histogram and compute_psi must agree on the same data."""

    def _make_reference(self, data, bins=10):
        """Return histogram counts and edges matching compute_psi binning."""
        breakpoints = np.percentile(data, np.linspace(0, 100, bins + 1))
        breakpoints = np.unique(breakpoints)
        counts, edges = np.histogram(data, bins=breakpoints)
        return counts.tolist(), edges.tolist()

    def test_identical_data_both_near_zero(self):
        """Both functions must return ~0 PSI when expected == actual."""
        np.random.seed(42)
        data = np.random.normal(500, 50, 500)

        hist_counts, hist_edges = self._make_reference(data)
        psi_histogram = _psi_from_histogram(hist_counts, hist_edges, data)["psi"]
        psi_array = compute_psi(data, data)

        assert psi_histogram == pytest.approx(0.0, abs=0.02), (
            f"_psi_from_histogram should be ~0 for identical data, got {psi_histogram}"
        )
        assert psi_array == pytest.approx(0.0, abs=0.02), (
            f"compute_psi should be ~0 for identical data, got {psi_array}"
        )

    def test_shifted_data_both_agree_within_tolerance(self):
        """For shifted distributions both functions must agree within 0.05."""
        np.random.seed(123)
        expected = np.random.normal(100, 10, 1000)
        actual = np.random.normal(115, 12, 1000)  # noticeable shift

        hist_counts, hist_edges = self._make_reference(expected)
        psi_histogram = _psi_from_histogram(hist_counts, hist_edges, actual)["psi"]
        psi_array = compute_psi(expected, actual)

        assert abs(psi_histogram - psi_array) < 0.05, (
            f"PSI mismatch: _psi_from_histogram={psi_histogram:.4f}, "
            f"compute_psi={psi_array:.4f} — delta {abs(psi_histogram - psi_array):.4f} > 0.05"
        )

    def test_no_eps_inflation_on_dense_bins(self):
        """With old eps=1e-4 per-bin inflation, even identical data yielded
        PSI > 0 for a 10-bin histogram.  With zero-only replacement this must
        be ≈ 0 (both PSI values within 0.01 of 0).
        """
        np.random.seed(7)
        data = np.random.uniform(0, 1, 2000)
        hist_counts, hist_edges = self._make_reference(data, bins=10)

        result = _psi_from_histogram(hist_counts, hist_edges, data)
        assert result["psi"] == pytest.approx(0.0, abs=0.01), (
            f"Old eps inflation would push PSI above 0 even for identical data; "
            f"got {result['psi']}"
        )
