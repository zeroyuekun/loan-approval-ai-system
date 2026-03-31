"""Geocoding service for geographic risk enrichment.

Uses Google Geocoding API (10K free requests/month) to:
1. Geocode applicant addresses to lat/lng
2. Compute geographic risk indicators by postcode
3. Enrich LoanApplication.postcode_default_rate with real data

ABS census data by postcode provides median income, unemployment, and
demographic composition for geographic risk scoring.
"""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GeoRiskProfile:
    """Geographic risk profile for a postcode/location."""

    postcode: str
    latitude: float | None
    longitude: float | None
    state: str
    remoteness: str  # 'major_city', 'inner_regional', 'outer_regional', 'remote', 'very_remote'
    estimated_default_rate: float  # 0-1, based on area socioeconomic indicators
    median_household_income: float | None
    unemployment_rate_local: float | None


# Australian postcode remoteness classification (ABS ARIA+)
# These ranges are simplified from ABS ARIA+ 2021 data.
# Full production system would load from a reference table.
MAJOR_CITY_RANGES = [
    (2000, 2234),  # Sydney CBD & inner suburbs
    (3000, 3207),  # Melbourne CBD & inner suburbs
    (4000, 4179),  # Brisbane CBD & inner suburbs
    (5000, 5199),  # Adelaide CBD & inner suburbs
    (6000, 6199),  # Perth CBD & inner suburbs
    (2600, 2618),  # Canberra
    (7000, 7049),  # Hobart CBD
    (800, 832),  # Darwin CBD
]

INNER_REGIONAL_RANGES = [
    (2250, 2310),  # Central Coast / Hunter NSW
    (2320, 2490),  # Hunter / Mid-North Coast
    (2500, 2530),  # Wollongong / Illawarra
    (3211, 3500),  # Regional VIC (Ballarat, Bendigo)
    (4205, 4399),  # Gold Coast / Sunshine Coast hinterland
    (7050, 7199),  # Southern TAS
]

OUTER_REGIONAL_RANGES = [
    (2540, 2599),  # South Coast NSW
    (2700, 2799),  # Western NSW
    (3501, 3699),  # North-east VIC
    (4400, 4699),  # Central QLD
    (5200, 5499),  # Regional SA
]

REMOTE_RANGES = [
    (2830, 2899),  # Far west NSW
    (4700, 4899),  # North QLD
    (5500, 5799),  # Remote SA
    (6200, 6699),  # Regional WA
    (870, 899),  # Remote NT
]

VERY_REMOTE_RANGES = [
    (4900, 4999),  # Far north QLD
    (5800, 5999),  # Very remote SA
    (6700, 6999),  # Very remote WA
    (900, 999),  # Very remote NT
]

# Fallback remoteness by state (used when postcode not in any range)
REMOTENESS_FALLBACK = {
    "NSW": "major_city",
    "VIC": "major_city",
    "QLD": "inner_regional",
    "WA": "inner_regional",
    "SA": "major_city",
    "TAS": "outer_regional",
    "NT": "remote",
    "ACT": "major_city",
}

# Estimated default rates by remoteness (informed by APRA ADI statistics)
DEFAULT_RATE_BY_REMOTENESS = {
    "major_city": 0.015,
    "inner_regional": 0.022,
    "outer_regional": 0.030,
    "remote": 0.040,
    "very_remote": 0.055,
}

# State-level adjustments: multiplier on base remoteness default rate.
# Derived from APRA ADI Property Exposure statistics by state.
STATE_DEFAULT_RATE_ADJUSTMENT = {
    "NSW": 0.95,  # Slightly below national average
    "VIC": 0.98,
    "QLD": 1.05,
    "WA": 1.10,  # Mining cycle volatility
    "SA": 1.02,
    "TAS": 1.08,
    "NT": 1.15,  # Higher volatility
    "ACT": 0.85,  # Government employment stability
}


class GeocodingService:
    """Geocodes addresses and computes geographic risk profiles."""

    GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self):
        self.timeout = httpx.Timeout(10.0, connect=5.0)
        self.google_api_key = os.environ.get("GOOGLE_GEOCODING_API_KEY", "")

    def get_geo_risk_profile(self, postcode: str, state: str = "") -> GeoRiskProfile:
        """Get geographic risk profile for an Australian postcode.

        Geocodes the postcode, determines remoteness, estimates default rate.
        Falls back to state-level estimates if geocoding fails.
        """
        # Attempt geocoding for lat/lng
        geo_result = self._geocode_postcode(postcode)

        latitude = None
        longitude = None
        if geo_result:
            latitude = geo_result.get("latitude")
            longitude = geo_result.get("longitude")
            # Try to extract state from geocoding result if not provided
            if not state and geo_result.get("state"):
                state = geo_result["state"]

        # Classify remoteness
        remoteness = self._classify_remoteness(postcode, state)

        # Estimate default rate
        estimated_default_rate = self._estimate_default_rate(remoteness, state)

        return GeoRiskProfile(
            postcode=postcode,
            latitude=latitude,
            longitude=longitude,
            state=state,
            remoteness=remoteness,
            estimated_default_rate=estimated_default_rate,
            median_household_income=None,  # Would come from ABS census data
            unemployment_rate_local=None,  # Would come from ABS labour force data
        )

    def geocode_address(self, address: str) -> dict | None:
        """Geocode a full address using Google Geocoding API.

        Returns {'latitude': float, 'longitude': float, 'formatted_address': str}
        or None if geocoding fails.
        """
        if not self.google_api_key:
            logger.warning("Google Geocoding API key not configured")
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    self.GOOGLE_GEOCODING_URL,
                    params={
                        "address": address,
                        "components": "country:AU",
                        "key": self.google_api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") != "OK" or not data.get("results"):
                    logger.warning(
                        "Geocoding returned status %s for address: %s",
                        data.get("status"),
                        address,
                    )
                    return None

                result = data["results"][0]
                location = result["geometry"]["location"]

                return {
                    "latitude": location["lat"],
                    "longitude": location["lng"],
                    "formatted_address": result.get("formatted_address", ""),
                }
        except Exception:
            logger.exception("Google Geocoding API request failed for: %s", address)
            return None

    def _classify_remoteness(self, postcode: str, state: str) -> str:
        """Classify postcode into ABS ARIA+ remoteness category.

        Checks postcode against known ranges. Falls back to state-level
        default if postcode is not in any recognised range.
        """
        try:
            pc = int(postcode)
        except (ValueError, TypeError):
            return REMOTENESS_FALLBACK.get(state, "inner_regional")

        # Check ranges in order from most to least urban
        range_map = [
            (MAJOR_CITY_RANGES, "major_city"),
            (INNER_REGIONAL_RANGES, "inner_regional"),
            (OUTER_REGIONAL_RANGES, "outer_regional"),
            (REMOTE_RANGES, "remote"),
            (VERY_REMOTE_RANGES, "very_remote"),
        ]

        for ranges, category in range_map:
            for low, high in ranges:
                if low <= pc <= high:
                    return category

        # Fallback to state-level estimate
        return REMOTENESS_FALLBACK.get(state, "inner_regional")

    def _estimate_default_rate(self, remoteness: str, state: str) -> float:
        """Estimate default rate based on remoteness and state.

        Uses APRA ADI statistics on loan performance by geographic area.
        Combines base remoteness rate with state-level adjustment.
        Result is always clipped to (0, 1) range.
        """
        base_rate = DEFAULT_RATE_BY_REMOTENESS.get(remoteness, 0.025)
        state_adj = STATE_DEFAULT_RATE_ADJUSTMENT.get(state, 1.0)

        estimated = base_rate * state_adj

        # Clip to valid (0, 1) range
        return max(0.0, min(1.0, round(estimated, 4)))

    @lru_cache(maxsize=1000)  # noqa: B019
    def _geocode_postcode(self, postcode: str) -> dict | None:
        """Geocode an Australian postcode (cached).

        Returns {'latitude': float, 'longitude': float, 'state': str} or None.
        """
        if not self.google_api_key:
            logger.debug("No Google API key — skipping postcode geocoding")
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    self.GOOGLE_GEOCODING_URL,
                    params={
                        "address": f"{postcode}, Australia",
                        "components": "country:AU",
                        "key": self.google_api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") != "OK" or not data.get("results"):
                    return None

                result = data["results"][0]
                location = result["geometry"]["location"]

                # Extract state from address components
                state = ""
                for component in result.get("address_components", []):
                    if "administrative_area_level_1" in component.get("types", []):
                        state = component.get("short_name", "")
                        break

                return {
                    "latitude": location["lat"],
                    "longitude": location["lng"],
                    "state": state,
                }
        except Exception:
            logger.exception("Failed to geocode postcode %s", postcode)
            return None
