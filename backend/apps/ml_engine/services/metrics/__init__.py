"""Metrics subpackage — model performance metrics + real-world benchmarks.

``compute`` holds the model-performance metrics; ``real_world_benchmarks``
the Australian public-source lending benchmarks. The names below are
re-exported; direct submodule imports are preferred for new code:

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
