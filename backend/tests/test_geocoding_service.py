"""Tests for the geocoding service.

All HTTP calls are mocked — no real API calls are made.
"""

import pytest
from dataclasses import fields
from unittest.mock import patch, MagicMock

import httpx

from apps.ml_engine.services.geocoding_service import (
    DEFAULT_RATE_BY_REMOTENESS,
    GeocodingService,
    GeoRiskProfile,
    REMOTENESS_FALLBACK,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """GeocodingService with a fake API key."""
    with patch.dict(
        "os.environ",
        {
            "GOOGLE_GEOCODING_API_KEY": "test-api-key",
        },
    ):
        svc = GeocodingService()
        # Clear lru_cache between tests
        svc._geocode_postcode.cache_clear()
        yield svc


@pytest.fixture
def service_no_key():
    """GeocodingService without an API key."""
    with patch.dict(
        "os.environ",
        {
            "GOOGLE_GEOCODING_API_KEY": "",
        },
    ):
        svc = GeocodingService()
        svc._geocode_postcode.cache_clear()
        yield svc


@pytest.fixture
def mock_geocode_response():
    """Sample Google Geocoding API response for Sydney CBD."""
    return {
        "status": "OK",
        "results": [
            {
                "geometry": {
                    "location": {"lat": -33.8688, "lng": 151.2093},
                },
                "formatted_address": "Sydney NSW 2000, Australia",
                "address_components": [
                    {
                        "long_name": "New South Wales",
                        "short_name": "NSW",
                        "types": ["administrative_area_level_1", "political"],
                    },
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test GeoRiskProfile dataclass
# ---------------------------------------------------------------------------


class TestGeoRiskProfile:
    def test_has_expected_fields(self):
        expected = {
            "postcode",
            "latitude",
            "longitude",
            "state",
            "remoteness",
            "estimated_default_rate",
            "median_household_income",
            "unemployment_rate_local",
        }
        actual = {f.name for f in fields(GeoRiskProfile)}
        assert actual == expected

    def test_default_rate_within_bounds(self):
        """estimated_default_rate must be in (0, 1) range."""
        profile = GeoRiskProfile(
            postcode="2000",
            latitude=-33.87,
            longitude=151.21,
            state="NSW",
            remoteness="major_city",
            estimated_default_rate=0.015,
            median_household_income=None,
            unemployment_rate_local=None,
        )
        assert 0.0 <= profile.estimated_default_rate <= 1.0


# ---------------------------------------------------------------------------
# Test get_geo_risk_profile
# ---------------------------------------------------------------------------


class TestGetGeoRiskProfile:
    def test_returns_valid_profile_with_geocoding(self, service, mock_geocode_response):
        """Returns a GeoRiskProfile with lat/lng when geocoding succeeds."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_geocode_response
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            profile = service.get_geo_risk_profile("2000", state="NSW")

        assert isinstance(profile, GeoRiskProfile)
        assert profile.postcode == "2000"
        assert profile.latitude is not None
        assert profile.longitude is not None
        assert profile.remoteness == "major_city"
        assert 0.0 < profile.estimated_default_rate < 1.0

    def test_falls_back_without_api_key(self, service_no_key):
        """Returns a profile with state-level fallback when no API key."""
        profile = service_no_key.get_geo_risk_profile("2000", state="NSW")

        assert isinstance(profile, GeoRiskProfile)
        assert profile.postcode == "2000"
        assert profile.latitude is None
        assert profile.longitude is None
        assert profile.remoteness == "major_city"
        assert 0.0 < profile.estimated_default_rate < 1.0

    def test_state_fallback_when_postcode_unknown(self, service_no_key):
        """Uses state-level remoteness when postcode is not in any known range."""
        profile = service_no_key.get_geo_risk_profile("9999", state="NT")

        assert isinstance(profile, GeoRiskProfile)
        assert profile.remoteness == REMOTENESS_FALLBACK["NT"]
        assert 0.0 < profile.estimated_default_rate < 1.0


# ---------------------------------------------------------------------------
# Test _classify_remoteness
# ---------------------------------------------------------------------------


class TestClassifyRemoteness:
    def test_sydney_cbd_is_major_city(self, service):
        assert service._classify_remoteness("2000", "NSW") == "major_city"

    def test_melbourne_cbd_is_major_city(self, service):
        assert service._classify_remoteness("3000", "VIC") == "major_city"

    def test_brisbane_is_major_city(self, service):
        assert service._classify_remoteness("4000", "QLD") == "major_city"

    def test_canberra_is_major_city(self, service):
        assert service._classify_remoteness("2600", "ACT") == "major_city"

    def test_remote_nsw_postcode(self, service):
        assert service._classify_remoteness("2880", "NSW") == "remote"

    def test_very_remote_wa(self, service):
        assert service._classify_remoteness("6800", "WA") == "very_remote"

    def test_invalid_postcode_uses_state_fallback(self, service):
        assert service._classify_remoteness("invalid", "TAS") == REMOTENESS_FALLBACK["TAS"]

    def test_unknown_postcode_uses_state_fallback(self, service):
        result = service._classify_remoteness("9999", "NT")
        assert result == REMOTENESS_FALLBACK["NT"]

    def test_unknown_state_defaults_to_inner_regional(self, service):
        result = service._classify_remoteness("9999", "XX")
        assert result == "inner_regional"


# ---------------------------------------------------------------------------
# Test _estimate_default_rate
# ---------------------------------------------------------------------------


class TestEstimateDefaultRate:
    def test_returns_float_in_valid_range(self, service):
        for remoteness in DEFAULT_RATE_BY_REMOTENESS:
            rate = service._estimate_default_rate(remoteness, "NSW")
            assert 0.0 < rate < 1.0, f"Rate for {remoteness} out of bounds: {rate}"

    def test_major_city_lower_than_remote(self, service):
        city_rate = service._estimate_default_rate("major_city", "NSW")
        remote_rate = service._estimate_default_rate("remote", "NSW")
        assert city_rate < remote_rate

    def test_state_adjustment_affects_rate(self, service):
        act_rate = service._estimate_default_rate("major_city", "ACT")
        nt_rate = service._estimate_default_rate("major_city", "NT")
        # ACT has lower adjustment (0.85) than NT (1.15)
        assert act_rate < nt_rate

    def test_unknown_remoteness_uses_default(self, service):
        rate = service._estimate_default_rate("unknown_category", "NSW")
        assert 0.0 < rate < 1.0

    def test_all_remoteness_categories_produce_valid_rates(self, service):
        categories = ["major_city", "inner_regional", "outer_regional", "remote", "very_remote"]
        for cat in categories:
            for state in ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "NT", "ACT"]:
                rate = service._estimate_default_rate(cat, state)
                assert 0.0 <= rate <= 1.0, f"{cat}/{state}: {rate}"


# ---------------------------------------------------------------------------
# Test geocode_address
# ---------------------------------------------------------------------------


class TestGeocodeAddress:
    def test_returns_none_when_api_unavailable(self, service):
        """geocode_address returns None when API call fails."""
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_cls.return_value = mock_client

            result = service.geocode_address("123 Pitt St, Sydney NSW 2000")
            assert result is None

    def test_returns_none_without_api_key(self, service_no_key):
        result = service_no_key.geocode_address("123 Pitt St, Sydney NSW 2000")
        assert result is None

    def test_returns_location_on_success(self, service, mock_geocode_response):
        mock_response = MagicMock()
        mock_response.json.return_value = mock_geocode_response
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = service.geocode_address("Sydney NSW 2000")

        assert result is not None
        assert "latitude" in result
        assert "longitude" in result
        assert "formatted_address" in result
        assert isinstance(result["latitude"], float)
        assert isinstance(result["longitude"], float)

    def test_returns_none_on_zero_results(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = service.geocode_address("nonexistent place xyz")
            assert result is None
