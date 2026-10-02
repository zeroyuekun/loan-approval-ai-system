"""Live-data paths that could never run: both imported modules that do not exist.

- real_world_benchmarks._fetch_income_percentiles imported
  ``.external.macro_data`` relative to services/metrics/ (no such package).
- BenchmarkResolver.resolve_macro_for_quarter imported ``.macro_data_service``
  (the module is macro_data.py) inside a bare ``except: pass``, so
  ``generate_data --use-live-data`` silently used the historical tables.
"""

from unittest.mock import MagicMock, patch

from apps.ml_engine.services.external.benchmark_resolver import BenchmarkResolver
from apps.ml_engine.services.metrics.real_world_benchmarks import RealWorldBenchmarks


def test_income_percentiles_resolve_the_abs_state_codes():
    svc = RealWorldBenchmarks.__new__(RealWorldBenchmarks)
    with (
        patch.object(RealWorldBenchmarks, "_fetch_abs_data", return_value={}),
        patch.object(RealWorldBenchmarks, "_parse_abs_latest_value", return_value=1500.0),
    ):
        result = svc._fetch_income_percentiles("NSW")
    assert result["P50"] == round(1500.0 * 52)


def test_live_macro_uses_the_macro_data_service_for_the_latest_quarter():
    live = MagicMock()
    live.get_rba_cash_rate.return_value = 9.99
    live.get_unemployment_rate.return_value = 8.88
    live.get_property_growth.return_value = 7.77
    live.get_consumer_confidence.return_value = 66.6
    resolver = BenchmarkResolver(use_live_macro=True)
    latest = max(resolver.RBA_RATE_HISTORY)
    with patch("apps.ml_engine.services.external.macro_data.MacroDataService", return_value=live):
        result = resolver.resolve_macro_for_quarter(latest, "NSW")
    assert result == {
        "rba_cash_rate": 9.99,
        "unemployment_rate": 8.88,
        "property_growth_12m": 7.77,
        "consumer_confidence": 66.6,
    }
