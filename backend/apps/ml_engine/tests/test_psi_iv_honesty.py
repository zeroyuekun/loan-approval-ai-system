"""Honesty/diagnostic guards for review #14 (PSI bin reconciliation) and
#13 (elevated-IV leakage signal). Pure unit tests — no DB."""

from __future__ import annotations

import numpy as np
import pandas as pd

from apps.ml_engine.services.metrics import MetricsService
from apps.ml_engine.services.training.feature_selection import select_features_by_iv


def test_psi_bin_components_reconcile_to_headline():
    """#14: the per-bin PSI breakdown must SUM to the headline PSI. Previously
    the bins used a 1e-4 + re-normalise scheme while the headline used the
    canonical drift_monitor primitive (1e-8, no re-normalise), so they diverged."""
    rng = np.random.default_rng(7)
    expected = rng.normal(0.0, 1.0, 2000)
    actual = rng.normal(0.6, 1.3, 2000)  # shifted + wider → non-trivial PSI

    result = MetricsService().compute_psi(expected, actual, n_bins=10)

    assert result["bins"], "expected a per-bin breakdown"
    component_sum = sum(b["psi_component"] for b in result["bins"])
    assert abs(component_sum - result["psi"]) < 1e-3, (
        f"per-bin components ({component_sum:.6f}) must reconcile to the headline PSI ({result['psi']:.6f})"
    )


def test_elevated_iv_features_are_flagged_but_kept():
    """#13: features with IV above the standard 0.5 leakage line but at/below the
    (higher) iv_max are KEPT, and reported in `elevated_iv` as an honest leakage
    signal — never silently dropped, never conflated with the rare excluded set."""
    rng = np.random.default_rng(42)
    n = 600
    target = np.array([0, 1] * (n // 2))
    df = pd.DataFrame(
        {
            "approved": target,
            "predictive": target * 2.0 + rng.normal(0, 1.0, n),
            "noise": rng.normal(0, 1, n),
        }
    )

    result = select_features_by_iv(df, ["predictive", "noise"], target="approved", iv_min=0.02, iv_max=1.5)

    assert "elevated_iv" in result, "the elevated-IV honest leakage signal must be reported"
    # Whatever lands in elevated_iv is KEPT (flagged, not excluded).
    for feat in result["elevated_iv"]:
        assert feat in result["selected_features"], f"{feat} flagged elevated but not kept"
        assert feat not in result["excluded_leakage"], f"{feat} both elevated and excluded"
    # And elevated is strictly the (0.5, iv_max] band — disjoint from the weak set.
    assert set(result["elevated_iv"]).isdisjoint(result["excluded_weak"])
