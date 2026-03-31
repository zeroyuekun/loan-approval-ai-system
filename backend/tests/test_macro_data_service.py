"""Tests for MacroDataService — Australian macroeconomic data fetcher.

All tests mock httpx so no real API calls are made.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from apps.ml_engine.services.macro_data_service import (
    MacroDataService,
    _CACHE_TTL_HOURS,
    _FALLBACKS,
    _FEATURE_BOUNDS,
)


# ---------------------------------------------------------------------------
# Realistic sample API responses used as test fixtures
# ---------------------------------------------------------------------------

SAMPLE_ABS_UNEMPLOYMENT_RESPONSE = {
    "data": {
        "dataSets": [
            {
                "observations": {
                    "0": [3.8],
                    "1": [3.9],
                    "2": [4.0],
                    "3": [4.1],
                    "4": [4.05],
                },
            }
        ],
    },
}

SAMPLE_ABS_RPPI_RESPONSE = {
    "data": {
        "dataSets": [
            {
                "observations": {
                    "0": [100.0],
                    "1": [101.5],
                    "2": [103.0],
                    "3": [104.2],
                    "4": [105.0],  # Current quarter
                },
            }
        ],
    },
}

SAMPLE_ABS_SERIES_FORMAT_RESPONSE = {
    "data": {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0:0": {
                        "observations": {
                            "0": [3.5],
                            "1": [3.6],
                            "2": [3.7],
                        },
                    },
                },
            }
        ],
    },
}

SAMPLE_WORLD_BANK_GDP_RESPONSE = [
    {"page": 1, "pages": 1, "per_page": 5, "total": 1},
    [
        {
            "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
            "country": {"id": "AU", "value": "Australia"},
            "countryiso3code": "AUS",
            "date": "2024",
            "value": 2.3,
            "unit": "",
            "obs_status": "",
            "decimal": 1,
        },
    ],
]

SAMPLE_WORLD_BANK_EMPTY_RESPONSE = [
    {"page": 1, "pages": 1, "per_page": 5, "total": 0},
    None,
]

SAMPLE_FRED_RBA_RESPONSE = {
    "observations": [
        {"date": "2024-11-01", "value": "4.35"},
    ],
}

SAMPLE_FRED_CCI_RESPONSE = {
    "observations": [
        {"date": "2024-10-01", "value": "97.2"},
    ],
}


def _make_mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status.return_value = None
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return mock_resp


def _make_mock_client(response):
    """Create a mock httpx.Client context manager returning *response* on .get()."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = response
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMacroDataServiceFallbacks(unittest.TestCase):
    """Each getter must return a valid float even when APIs are unreachable."""

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_rba_cash_rate_fallback(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("connection refused")
        svc = MacroDataService()
        result = svc.get_rba_cash_rate()
        self.assertIsInstance(result, float)
        self.assertEqual(result, _FALLBACKS["rba_cash_rate"])

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_unemployment_rate_fallback(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("connection refused")
        svc = MacroDataService()
        result = svc.get_unemployment_rate("NSW")
        self.assertIsInstance(result, float)
        self.assertEqual(result, _FALLBACKS["unemployment_rate"])

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_property_growth_fallback(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("timeout")
        svc = MacroDataService()
        result = svc.get_property_growth("VIC")
        self.assertIsInstance(result, float)
        self.assertEqual(result, _FALLBACKS["property_growth_12m"])

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_consumer_confidence_fallback(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("DNS failure")
        svc = MacroDataService()
        result = svc.get_consumer_confidence()
        self.assertIsInstance(result, float)
        self.assertEqual(result, _FALLBACKS["consumer_confidence"])

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_gdp_growth_fallback(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("network error")
        svc = MacroDataService()
        result = svc.get_gdp_growth()
        self.assertIsInstance(result, float)
        self.assertEqual(result, _FALLBACKS["gdp_growth"])


class TestMacroDataServiceReturnTypes(unittest.TestCase):
    """Each getter returns a float within FEATURE_BOUNDS."""

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_rba_cash_rate_within_bounds(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_FRED_RBA_RESPONSE),
        )
        svc = MacroDataService()
        svc.fred_api_key = "test-key"
        result = svc.get_rba_cash_rate()
        lo, hi = _FEATURE_BOUNDS["rba_cash_rate"]
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, lo)
        self.assertLessEqual(result, hi)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_unemployment_within_bounds(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_ABS_UNEMPLOYMENT_RESPONSE),
        )
        svc = MacroDataService()
        result = svc.get_unemployment_rate("national")
        lo, hi = _FEATURE_BOUNDS["unemployment_rate"]
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, lo)
        self.assertLessEqual(result, hi)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_property_growth_within_bounds(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_ABS_RPPI_RESPONSE),
        )
        svc = MacroDataService()
        result = svc.get_property_growth("national")
        lo, hi = _FEATURE_BOUNDS["property_growth_12m"]
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, lo)
        self.assertLessEqual(result, hi)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_gdp_growth_within_bounds(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_WORLD_BANK_GDP_RESPONSE),
        )
        svc = MacroDataService()
        result = svc.get_gdp_growth()
        lo, hi = _FEATURE_BOUNDS["gdp_growth"]
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, lo)
        self.assertLessEqual(result, hi)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_consumer_confidence_within_bounds(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_FRED_CCI_RESPONSE),
        )
        svc = MacroDataService()
        svc.fred_api_key = "test-key"
        # Make World Bank fail so it falls through to FRED
        result = svc.get_consumer_confidence()
        lo, hi = _FEATURE_BOUNDS["consumer_confidence"]
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, lo)
        self.assertLessEqual(result, hi)


class TestCaching(unittest.TestCase):
    """Second call within TTL should not hit the API again."""

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_cache_prevents_second_api_call(self, mock_client_cls):
        mock_client = _make_mock_client(
            _make_mock_response(SAMPLE_WORLD_BANK_GDP_RESPONSE),
        )
        mock_client_cls.return_value = mock_client

        svc = MacroDataService()
        result1 = svc.get_gdp_growth()
        result2 = svc.get_gdp_growth()

        self.assertEqual(result1, result2)
        # httpx.Client() should only be called once (cached on second call)
        self.assertEqual(mock_client_cls.call_count, 1)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_cache_expires_after_ttl(self, mock_client_cls):
        mock_client = _make_mock_client(
            _make_mock_response(SAMPLE_WORLD_BANK_GDP_RESPONSE),
        )
        mock_client_cls.return_value = mock_client

        svc = MacroDataService()
        svc.get_gdp_growth()

        # Manually expire cache
        svc._cache_timestamps["gdp_growth"] = datetime.utcnow() - timedelta(hours=_CACHE_TTL_HOURS + 1)
        svc.get_gdp_growth()

        # Should have fetched twice
        self.assertEqual(mock_client_cls.call_count, 2)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_stale_cache_served_on_api_failure(self, mock_client_cls):
        # First call succeeds
        mock_client = _make_mock_client(
            _make_mock_response(SAMPLE_WORLD_BANK_GDP_RESPONSE),
        )
        mock_client_cls.return_value = mock_client

        svc = MacroDataService()
        result1 = svc.get_gdp_growth()

        # Expire cache, then make API fail
        svc._cache_timestamps["gdp_growth"] = datetime.utcnow() - timedelta(hours=_CACHE_TTL_HOURS + 1)
        mock_client_cls.side_effect = Exception("API down")

        result2 = svc.get_gdp_growth()
        # Should return a valid float (either stale cache or fallback)
        self.assertIsInstance(result2, float)
        self.assertGreater(result2, 0)


class TestGetAllMacroIndicators(unittest.TestCase):
    """get_all_macro_indicators returns all expected keys."""

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_all_keys_present(self, mock_client_cls):
        # All APIs fail — should still return all keys via fallbacks
        mock_client_cls.side_effect = Exception("offline")
        svc = MacroDataService()
        indicators = svc.get_all_macro_indicators("NSW")

        expected_keys = {
            "rba_cash_rate",
            "unemployment_rate",
            "property_growth_12m",
            "consumer_confidence",
            "gdp_growth",
        }
        self.assertEqual(set(indicators.keys()), expected_keys)
        for key, val in indicators.items():
            self.assertIsInstance(val, float, f"{key} is not a float")

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_all_values_within_bounds(self, mock_client_cls):
        mock_client_cls.side_effect = Exception("offline")
        svc = MacroDataService()
        indicators = svc.get_all_macro_indicators()

        for key, val in indicators.items():
            bounds = _FEATURE_BOUNDS.get(key)
            if bounds:
                lo, hi = bounds
                self.assertGreaterEqual(val, lo, f"{key}={val} below min {lo}")
                self.assertLessEqual(val, hi, f"{key}={val} above max {hi}")


class TestABSParsing(unittest.TestCase):
    """Test parsing of ABS SDMX-JSON responses."""

    def test_parse_abs_latest_value_observations_format(self):
        svc = MacroDataService()
        result = svc._parse_abs_latest_value(SAMPLE_ABS_UNEMPLOYMENT_RESPONSE)
        self.assertIsNotNone(result)
        self.assertEqual(result, 4.05)  # Last observation

    def test_parse_abs_latest_value_series_format(self):
        svc = MacroDataService()
        result = svc._parse_abs_latest_value(SAMPLE_ABS_SERIES_FORMAT_RESPONSE)
        self.assertIsNotNone(result)
        self.assertEqual(result, 3.7)  # Last observation in series

    def test_parse_abs_latest_value_empty_response(self):
        svc = MacroDataService()
        result = svc._parse_abs_latest_value({"data": {"dataSets": []}})
        self.assertIsNone(result)

    def test_parse_abs_latest_value_no_observations(self):
        svc = MacroDataService()
        result = svc._parse_abs_latest_value(
            {
                "data": {"dataSets": [{"observations": {}}]},
            }
        )
        self.assertIsNone(result)

    def test_parse_abs_property_growth(self):
        """5 quarters: 100 -> 105 = 5% annual growth."""
        svc = MacroDataService()
        result = svc._parse_abs_property_growth(SAMPLE_ABS_RPPI_RESPONSE)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 5.0, places=1)

    def test_parse_abs_property_growth_insufficient_data(self):
        svc = MacroDataService()
        short_data = {
            "data": {"dataSets": [{"observations": {"0": [100.0], "1": [102.0]}}]},
        }
        result = svc._parse_abs_property_growth(short_data)
        self.assertIsNone(result)


class TestWorldBankParsing(unittest.TestCase):
    """Test parsing of World Bank JSON responses."""

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_world_bank_gdp_parsing(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_WORLD_BANK_GDP_RESPONSE),
        )
        svc = MacroDataService()
        result = svc.get_gdp_growth()
        self.assertEqual(result, 2.3)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_world_bank_empty_data_falls_to_fallback(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_WORLD_BANK_EMPTY_RESPONSE),
        )
        svc = MacroDataService()
        result = svc.get_gdp_growth()
        self.assertEqual(result, _FALLBACKS["gdp_growth"])

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_world_bank_null_values_skipped(self, mock_client_cls):
        """World Bank sometimes returns entries with value=None for future years."""
        data_with_nulls = [
            {"page": 1, "pages": 1, "per_page": 5, "total": 2},
            [
                {"value": None, "date": "2025"},
                {"value": 1.8, "date": "2024"},
            ],
        ]
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(data_with_nulls),
        )
        svc = MacroDataService()
        result = svc.get_gdp_growth()
        self.assertEqual(result, 1.8)


class TestFREDParsing(unittest.TestCase):
    """Test parsing of FRED JSON responses."""

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_fred_rba_rate_parsing(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(SAMPLE_FRED_RBA_RESPONSE),
        )
        svc = MacroDataService()
        svc.fred_api_key = "test-key"
        result = svc.get_rba_cash_rate()
        self.assertEqual(result, 4.35)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_fred_no_api_key_falls_to_fallback(self, mock_client_cls):
        svc = MacroDataService()
        svc.fred_api_key = ""
        result = svc.get_rba_cash_rate()
        self.assertEqual(result, _FALLBACKS["rba_cash_rate"])

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_fred_empty_observations_falls_to_fallback(self, mock_client_cls):
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response({"observations": []}),
        )
        svc = MacroDataService()
        svc.fred_api_key = "test-key"
        result = svc.get_rba_cash_rate()
        self.assertEqual(result, _FALLBACKS["rba_cash_rate"])


class TestClipping(unittest.TestCase):
    """Values outside FEATURE_BOUNDS must be clipped."""

    def test_clip_high_value(self):
        svc = MacroDataService()
        result = svc._clip("rba_cash_rate", 25.0)
        self.assertEqual(result, 20.0)

    def test_clip_low_value(self):
        svc = MacroDataService()
        result = svc._clip("rba_cash_rate", -1.0)
        self.assertEqual(result, 0.0)

    def test_clip_within_bounds(self):
        svc = MacroDataService()
        result = svc._clip("rba_cash_rate", 4.35)
        self.assertEqual(result, 4.35)

    def test_clip_negative_property_growth(self):
        svc = MacroDataService()
        result = svc._clip("property_growth_12m", -60.0)
        self.assertEqual(result, -50.0)

    def test_clip_unknown_indicator_passthrough(self):
        svc = MacroDataService()
        result = svc._clip("unknown_indicator", 999.0)
        self.assertEqual(result, 999.0)

    @patch("apps.ml_engine.services.macro_data_service.httpx.Client")
    def test_extreme_api_value_gets_clipped(self, mock_client_cls):
        """Simulate an API returning an absurd value — it must be clipped."""
        extreme_response = {
            "observations": [
                {"date": "2024-11-01", "value": "50.0"},  # Way above max 20
            ],
        }
        mock_client_cls.return_value = _make_mock_client(
            _make_mock_response(extreme_response),
        )
        svc = MacroDataService()
        svc.fred_api_key = "test-key"
        result = svc.get_rba_cash_rate()
        self.assertEqual(result, 20.0)  # Clipped to max


if __name__ == "__main__":
    unittest.main()
