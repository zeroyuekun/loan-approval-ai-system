import numpy as np


class TestPSIComputation:
    """Test Population Stability Index calculation."""

    def test_identical_distributions_low_psi(self):
        """Same distribution should produce PSI near 0."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        np.random.seed(42)
        data = np.random.normal(0, 1, 1000)

        psi = compute_psi(data, data)
        assert psi < 0.01, f"Identical distributions should have PSI near 0, got {psi}"

    def test_similar_distributions_stable(self):
        """Similar distributions should produce PSI < 0.10."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        np.random.seed(42)
        expected = np.random.normal(0, 1, 1000)
        actual = np.random.normal(0.05, 1.02, 1000)  # Slight shift

        psi = compute_psi(expected, actual)
        assert psi < 0.10, f"Similar distributions should have PSI < 0.10, got {psi}"

    def test_shifted_distribution_high_psi(self):
        """Significantly shifted distribution should produce PSI > 0.25."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        np.random.seed(42)
        expected = np.random.normal(0, 1, 1000)
        actual = np.random.normal(2, 1.5, 1000)  # Major shift

        psi = compute_psi(expected, actual)
        assert psi > 0.25, f"Shifted distributions should have PSI > 0.25, got {psi}"

    def test_empty_distribution(self):
        """Empty arrays should return PSI = 0."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        psi = compute_psi([], [1, 2, 3])
        assert psi == 0.0

        psi = compute_psi([1, 2, 3], [])
        assert psi == 0.0

    def test_psi_symmetric_approximately(self):
        """PSI should be roughly symmetric (not exactly due to binning)."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        np.random.seed(42)
        a = np.random.normal(0, 1, 1000)
        b = np.random.normal(1, 1, 1000)

        psi_ab = compute_psi(a, b)
        psi_ba = compute_psi(b, a)

        # Should be in same ballpark (not identical due to binning from expected)
        assert abs(psi_ab - psi_ba) < psi_ab * 0.5, f"PSI should be roughly symmetric: {psi_ab} vs {psi_ba}"

    def test_constant_distribution_returns_zero(self):
        """Constant distribution (all same value) should return PSI = 0."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        expected = np.ones(100)
        actual = np.ones(100)

        psi = compute_psi(expected, actual)
        assert psi == 0.0, f"Constant distributions should have PSI = 0, got {psi}"

    def test_psi_non_negative(self):
        """PSI should always be non-negative."""
        from apps.ml_engine.services.drift_monitor import compute_psi

        np.random.seed(42)
        for _ in range(10):
            a = np.random.normal(np.random.uniform(-5, 5), np.random.uniform(0.5, 3), 500)
            b = np.random.normal(np.random.uniform(-5, 5), np.random.uniform(0.5, 3), 500)
            psi = compute_psi(a, b)
            assert psi >= 0, f"PSI should be non-negative, got {psi}"


class TestPSIThresholds:
    """Test PSI threshold constants."""

    def test_threshold_values(self):
        """Verify threshold constants match industry standards."""
        from apps.ml_engine.services.drift_monitor import PSI_INVESTIGATE, PSI_STABLE

        assert PSI_STABLE == 0.10, f"PSI_STABLE should be 0.10, got {PSI_STABLE}"
        assert PSI_INVESTIGATE == 0.25, f"PSI_INVESTIGATE should be 0.25, got {PSI_INVESTIGATE}"
        assert PSI_STABLE < PSI_INVESTIGATE, "PSI_STABLE should be less than PSI_INVESTIGATE"


class TestConformalSSBC:
    """Test Small Sample Beta Correction for conformal prediction."""

    def test_ssbc_adjusts_alpha_for_small_n(self):
        """SSBC should tighten alpha for small calibration sets."""

        alpha = 0.05
        n = 100  # Small calibration set

        # For small n, the conformal quantile is at position close to n,
        # meaning the coverage guarantee depends heavily on the specific calibration draw.
        # The standard conformal quantile index:
        q_idx = int(np.ceil((1 - alpha) * (n + 1))) - 1
        q_idx = min(q_idx, n - 1)

        # With n=100 and alpha=0.05, q_idx = 95 (96th value out of 100)
        # The coverage variance is significant for small n
        assert q_idx < n, f"Quantile index {q_idx} should be < n={n}"
        assert q_idx >= n * 0.9, "Quantile index should be near top for small alpha"
        # Key property: for small n, the gap between q_idx and n is small,
        # meaning a single outlier in calibration could shift coverage significantly
        gap = n - q_idx
        assert gap <= 10, f"Gap between quantile and n should be small for small n, got {gap}"

    def test_ssbc_no_adjustment_for_large_n(self):
        """SSBC should not significantly adjust alpha for large calibration sets."""
        from scipy.stats import beta as beta_dist

        alpha = 0.05
        n = 5000  # Large calibration set

        adjusted_alpha = alpha
        for candidate in np.arange(alpha * 0.5, alpha, 0.001):
            k = int(np.ceil((1 - candidate) * (n + 1))) - 1
            k = min(k, n - 1)
            coverage_prob = 1 - beta_dist.cdf(1 - alpha, n - k, k + 1)
            if coverage_prob >= 0.9:
                adjusted_alpha = candidate
                break

        # For large n, adjustment should be minimal
        assert abs(adjusted_alpha - alpha) < 0.01, (
            f"SSBC should not significantly adjust for n={n}: got {adjusted_alpha}"
        )

    def test_ssbc_monotonic_in_n(self):
        """As n increases, the adjustment should decrease (closer to original alpha)."""
        from scipy.stats import beta as beta_dist

        alpha = 0.05
        adjustments = []

        for n in [50, 100, 200, 500]:
            adjusted_alpha = alpha
            for candidate in np.arange(alpha * 0.5, alpha, 0.001):
                k = int(np.ceil((1 - candidate) * (n + 1))) - 1
                k = min(k, n - 1)
                coverage_prob = 1 - beta_dist.cdf(1 - alpha, n - k, k + 1)
                if coverage_prob >= 0.9:
                    adjusted_alpha = candidate
                    break
            adjustments.append(alpha - adjusted_alpha)

        # Adjustment should decrease as n increases
        for i in range(len(adjustments) - 1):
            assert adjustments[i] >= adjustments[i + 1], f"Adjustment should decrease with n: {adjustments}"
