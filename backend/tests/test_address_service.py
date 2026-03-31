"""Tests for AddressService — Australian address validation and geocoding."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.accounts.services.address_service import (
    _POSTCODE_RISK_DATA,
    AddressService,
    AddressValidation,
)

# ---------------------------------------------------------------------------
# Sample API responses
# ---------------------------------------------------------------------------
GNAF_VALID_RESPONSE = [
    {
        "sla": "1 GEORGE ST, SYDNEY NSW 2000",
        "locality": "SYDNEY",
        "state": "NSW",
        "postcode": "2000",
        "score": 0.95,
        "geocoding": {
            "latitude": -33.8688,
            "longitude": 151.2093,
        },
    }
]

GNAF_EMPTY_RESPONSE = []

GOOGLE_VALID_RESPONSE = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "1 George St, Sydney NSW 2000, Australia",
            "geometry": {
                "location": {"lat": -33.8688, "lng": 151.2093},
                "location_type": "ROOFTOP",
            },
            "address_components": [
                {"long_name": "Sydney", "short_name": "Sydney", "types": ["locality"]},
                {"long_name": "New South Wales", "short_name": "NSW", "types": ["administrative_area_level_1"]},
                {"long_name": "2000", "short_name": "2000", "types": ["postal_code"]},
            ],
        }
    ],
}

GOOGLE_ZERO_RESULTS = {
    "status": "ZERO_RESULTS",
    "results": [],
}

GOOGLE_GEOCODE_RESPONSE = {
    "status": "OK",
    "results": [
        {
            "geometry": {
                "location": {"lat": -33.8688, "lng": 151.2093},
            },
        }
    ],
}


# ---------------------------------------------------------------------------
# Helper to mock httpx responses
# ---------------------------------------------------------------------------
def _mock_httpx_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    return resp


# ---------------------------------------------------------------------------
# 1. validate_address returns valid for known address (via G-NAF)
# ---------------------------------------------------------------------------
class TestValidateAddressValid:
    def test_valid_via_gnaf(self):
        svc = AddressService()
        svc.addressr_url = "http://localhost:8080"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_httpx_response(GNAF_VALID_RESPONSE)

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.validate_address("1 George St", "Sydney", "NSW", "2000")

        assert result.is_valid is True
        assert result.source == "gnaf"
        assert result.confidence >= 0.9
        assert result.postcode == "2000"
        assert result.state == "NSW"

    def test_valid_via_google_fallback(self):
        svc = AddressService()
        svc.addressr_url = ""  # No G-NAF
        svc.google_api_key = "test-key"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_httpx_response(GOOGLE_VALID_RESPONSE)

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.validate_address("1 George St", "Sydney", "NSW", "2000")

        assert result.is_valid is True
        assert result.source == "google"
        assert result.latitude is not None
        assert result.longitude is not None


# ---------------------------------------------------------------------------
# 2. validate_address returns invalid for nonsense
# ---------------------------------------------------------------------------
class TestValidateAddressInvalid:
    def test_invalid_state(self):
        svc = AddressService()
        result = svc.validate_address("123 Fake St", "Nowhere", "ZZZ", "0000")
        assert result.is_valid is False
        assert result.confidence == 0.0

    def test_gnaf_no_match(self):
        svc = AddressService()
        svc.addressr_url = "http://localhost:8080"
        svc.google_api_key = ""  # No Google fallback

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_httpx_response(GNAF_EMPTY_RESPONSE)

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.validate_address("999 Nonexistent Rd", "Faketown", "NSW", "9999")

        assert result.is_valid is False
        assert result.source == "gnaf"

    def test_google_zero_results(self):
        svc = AddressService()
        svc.addressr_url = ""
        svc.google_api_key = "test-key"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_httpx_response(GOOGLE_ZERO_RESULTS)

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.validate_address("XYZZY", "Nowhere", "NSW", "0000")

        # Google returned zero results, both APIs tried and failed
        assert result.is_valid is False


# ---------------------------------------------------------------------------
# 3. geocode returns lat/lng
# ---------------------------------------------------------------------------
class TestGeocode:
    def test_geocode_success(self):
        svc = AddressService()
        svc.google_api_key = "test-key"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_httpx_response(GOOGLE_GEOCODE_RESPONSE)

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.geocode("1 George St, Sydney NSW 2000")

        assert result is not None
        assert "latitude" in result
        assert "longitude" in result
        assert result["latitude"] == pytest.approx(-33.8688, abs=0.01)
        assert result["longitude"] == pytest.approx(151.2093, abs=0.01)

    def test_geocode_no_api_key(self):
        svc = AddressService()
        svc.google_api_key = ""
        result = svc.geocode("1 George St, Sydney")
        assert result is None

    def test_geocode_api_error(self):
        svc = AddressService()
        svc.google_api_key = "test-key"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.geocode("1 George St, Sydney")

        assert result is None


# ---------------------------------------------------------------------------
# 4. postcode_risk_data returns expected keys
# ---------------------------------------------------------------------------
class TestPostcodeRiskData:
    def test_known_postcode(self):
        svc = AddressService()
        data = svc.get_postcode_risk_data("2000")
        assert "default_rate" in data
        assert "median_income" in data
        assert "remoteness" in data
        assert 0 <= data["default_rate"] <= 1
        assert data["median_income"] > 0
        assert data["remoteness"] == "major_city"

    def test_unknown_postcode_returns_defaults(self):
        svc = AddressService()
        data = svc.get_postcode_risk_data("9999")
        assert data["default_rate"] == 0.025  # national average
        assert data["median_income"] == 72000
        assert data["remoteness"] == "unknown"

    def test_remote_postcode(self):
        svc = AddressService()
        data = svc.get_postcode_risk_data("0872")
        assert data["remoteness"] == "very_remote"
        assert data["default_rate"] > 0.04  # Higher default rate in remote areas

    def test_canberra_postcode(self):
        svc = AddressService()
        data = svc.get_postcode_risk_data("2600")
        assert data["default_rate"] < 0.02  # Low default rate
        assert data["median_income"] > 100000

    def test_all_postcodes_have_required_keys(self):
        svc = AddressService()
        required_keys = {"default_rate", "median_income", "remoteness"}
        for postcode in _POSTCODE_RISK_DATA:
            data = svc.get_postcode_risk_data(postcode)
            assert required_keys <= set(data.keys()), f"Postcode {postcode} missing keys"


# ---------------------------------------------------------------------------
# 5. Fallback when APIs unavailable
# ---------------------------------------------------------------------------
class TestApiFallback:
    def test_no_apis_configured(self):
        svc = AddressService()
        svc.addressr_url = ""
        svc.google_api_key = ""
        result = svc.validate_address("1 George St", "Sydney", "NSW", "2000")
        assert result.is_valid is False
        assert result.source == "none"
        assert result.confidence == 0.0
        # Should still populate basic fields
        assert result.state == "NSW"
        assert result.postcode == "2000"

    def test_gnaf_timeout_falls_through(self):
        svc = AddressService()
        svc.addressr_url = "http://localhost:8080"
        svc.google_api_key = ""

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.validate_address("1 George St", "Sydney", "NSW", "2000")

        assert result.is_valid is False
        assert result.source == "none"

    def test_google_500_error_returns_none(self):
        svc = AddressService()
        svc.addressr_url = ""
        svc.google_api_key = "test-key"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_httpx_response({}, status_code=500)

        with patch("apps.accounts.services.address_service.httpx.Client", return_value=mock_client):
            result = svc.validate_address("1 George St", "Sydney", "NSW", "2000")

        assert result.is_valid is False

    def test_address_validation_is_dataclass(self):
        import dataclasses

        assert dataclasses.is_dataclass(AddressValidation)

    def test_validation_result_has_all_fields(self):
        import dataclasses

        expected = {
            "is_valid",
            "normalized_address",
            "suburb",
            "state",
            "postcode",
            "latitude",
            "longitude",
            "confidence",
            "source",
        }
        actual = {f.name for f in dataclasses.fields(AddressValidation)}
        assert expected == actual
