"""Metrics subpackage — model performance metrics + real-world benchmarks.

Extracted from the flat ml_engine/services/ directory on 2026-05-26 as PR-2
of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

This PR moves `metrics.py` and `real_world_benchmarks.py` into a focused
subpackage. The in-file split into `compute / fairness / calibration /
ranking` modules described in the spec is deferred to a future PR — the
current single-file compute.py preserves zero behaviour change.

Re-exports preserve the public API. Direct imports from this subpackage
are preferred for new code:

    from apps.ml_engine.services.metrics.compute import MetricsService
"""

from apps.ml_engine.services.metrics.compute import (
    MetricsService,
    VintageAnalyser,
    brier_decomposition,
    ks_statistic,
    psi,
    psi_by_feature,
)
from apps.ml_engine.services.metrics.real_world_benchmarks import RealWorldBenchmarks

__all__ = [
    "MetricsService",
    "RealWorldBenchmarks",
    "VintageAnalyser",
    "brier_decomposition",
    "ks_statistic",
    "psi",
    "psi_by_feature",
]
