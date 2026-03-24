"""Australian address validation and geocoding service.

Sources:
- Addressr / G-NAF: Australia's authoritative address database (15.9M addresses)
- Google Geocoding API: Geocoding for risk enrichment (10K free/month)

Validates applicant addresses against official government data and enriches
with geographic risk features (postcode_default_rate).
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ABS census-derived postcode default rates (sample lookup).
# In production this would come from a database table updated quarterly.
_POSTCODE_RISK_DATA: dict[str, dict] = {
    # Sydney metro
    '2000': {'default_rate': 0.018, 'median_income': 95000, 'remoteness': 'major_city'},
    '2010': {'default_rate': 0.020, 'median_income': 88000, 'remoteness': 'major_city'},
    '2170': {'default_rate': 0.035, 'median_income': 62000, 'remoteness': 'major_city'},
    '2560': {'default_rate': 0.032, 'median_income': 68000, 'remoteness': 'inner_regional'},
    # Melbourne metro
    '3000': {'default_rate': 0.019, 'median_income': 90000, 'remoteness': 'major_city'},
    '3029': {'default_rate': 0.030, 'median_income': 65000, 'remoteness': 'major_city'},
    # Brisbane metro
    '4000': {'default_rate': 0.022, 'median_income': 82000, 'remoteness': 'major_city'},
    '4350': {'default_rate': 0.028, 'median_income': 60000, 'remoteness': 'inner_regional'},
    # Perth metro
    '6000': {'default_rate': 0.021, 'median_income': 85000, 'remoteness': 'major_city'},
    # Adelaide metro
    '5000': {'default_rate': 0.024, 'median_income': 75000, 'remoteness': 'major_city'},
    # Hobart
    '7000': {'default_rate': 0.026, 'median_income': 70000, 'remoteness': 'major_city'},
    # Canberra
    '2600': {'default_rate': 0.012, 'median_income': 110000, 'remoteness': 'major_city'},
    # Darwin
    '0800': {'default_rate': 0.030, 'median_income': 78000, 'remoteness': 'major_city'},
    # Remote
    '2880': {'default_rate': 0.045, 'median_income': 48000, 'remoteness': 'very_remote'},
    '0872': {'default_rate': 0.055, 'median_income': 42000, 'remoteness': 'very_remote'},
}

_VALID_STATES = {'NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT'}


@dataclass
class AddressValidation:
    """Result of address validation."""
    is_valid: bool
    normalized_address: str
    suburb: str
    state: str
    postcode: str
    latitude: Optional[float]
    longitude: Optional[float]
    confidence: float  # 0-1
    source: str  # 'gnaf' or 'google'


class AddressService:
    """Validates and geocodes Australian addresses."""

    def __init__(self):
        self.timeout = httpx.Timeout(10.0, connect=5.0)
        self.google_api_key = os.environ.get('GOOGLE_GEOCODING_API_KEY', '')
        self.addressr_url = os.environ.get('ADDRESSR_URL', '')  # Self-hosted

    def validate_address(
        self, address: str, suburb: str, state: str, postcode: str
    ) -> AddressValidation:
        """Validate an Australian address against G-NAF or Google Geocoding.

        Tries Addressr/G-NAF first, falls back to Google Geocoding.
        Returns an AddressValidation with is_valid=False if neither works.
        """
        # Basic input validation
        state_upper = state.upper().strip()
        postcode_clean = postcode.strip()

        if state_upper not in _VALID_STATES:
            return AddressValidation(
                is_valid=False,
                normalized_address='',
                suburb=suburb,
                state=state_upper,
                postcode=postcode_clean,
                latitude=None,
                longitude=None,
                confidence=0.0,
                source='none',
            )

        # Try G-NAF via Addressr first
        result = self._validate_via_gnaf(address, suburb, state_upper, postcode_clean)
        if result is not None:
            return result

        # Fall back to Google Geocoding
        result = self._validate_via_google(
            f'{address}, {suburb} {state_upper} {postcode_clean}, Australia'
        )
        if result is not None:
            return result

        # Both unavailable — return unvalidated with low confidence
        logger.warning("Address validation unavailable for %s %s %s", suburb, state_upper, postcode_clean)
        return AddressValidation(
            is_valid=False,
            normalized_address=f'{address}, {suburb} {state_upper} {postcode_clean}',
            suburb=suburb,
            state=state_upper,
            postcode=postcode_clean,
            latitude=None,
            longitude=None,
            confidence=0.0,
            source='none',
        )

    def geocode(self, address: str) -> Optional[dict]:
        """Geocode an address to lat/lng coordinates.

        Returns {'latitude': float, 'longitude': float} or None.
        """
        if not self.google_api_key:
            logger.debug("Google Geocoding API key not configured")
            return None

        url = 'https://maps.googleapis.com/maps/api/geocode/json'
        params = {
            'address': address,
            'key': self.google_api_key,
            'region': 'au',
            'components': 'country:AU',
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get('status') != 'OK' or not data.get('results'):
                    return None

                location = data['results'][0]['geometry']['location']
                return {
                    'latitude': location['lat'],
                    'longitude': location['lng'],
                }
        except (httpx.HTTPError, httpx.TimeoutException, KeyError, ValueError) as exc:
            logger.warning("Google Geocoding failed: %s", exc)
            return None

    def get_postcode_risk_data(self, postcode: str) -> dict:
        """Look up risk indicators for a postcode.

        Returns: {'default_rate': float, 'median_income': float, 'remoteness': str}
        Uses ABS census data by postcode. Falls back to national averages.
        """
        postcode_clean = postcode.strip()
        data = _POSTCODE_RISK_DATA.get(postcode_clean)
        if data:
            return dict(data)

        # National average fallback
        return {
            'default_rate': 0.025,
            'median_income': 72000,
            'remoteness': 'unknown',
        }

    def _validate_via_gnaf(
        self, address: str, suburb: str, state: str, postcode: str
    ) -> Optional[AddressValidation]:
        """Validate against G-NAF data via Addressr."""
        if not self.addressr_url:
            logger.debug("Addressr URL not configured, skipping G-NAF validation")
            return None

        search_term = f'{address}, {suburb} {state} {postcode}'
        url = f'{self.addressr_url}/api/v1/addresses'
        params = {'q': search_term}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                results = resp.json()

                if not results:
                    return AddressValidation(
                        is_valid=False,
                        normalized_address=search_term,
                        suburb=suburb,
                        state=state,
                        postcode=postcode,
                        latitude=None,
                        longitude=None,
                        confidence=0.0,
                        source='gnaf',
                    )

                # Take the best match
                best = results[0] if isinstance(results, list) else results
                sla = best.get('sla', search_term)
                geo = best.get('geocoding', {})

                return AddressValidation(
                    is_valid=True,
                    normalized_address=sla,
                    suburb=best.get('locality', suburb),
                    state=best.get('state', state),
                    postcode=best.get('postcode', postcode),
                    latitude=geo.get('latitude'),
                    longitude=geo.get('longitude'),
                    confidence=min(float(best.get('score', 0.8)), 1.0),
                    source='gnaf',
                )
        except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError) as exc:
            logger.warning("Addressr/G-NAF lookup failed: %s", exc)
            return None

    def _validate_via_google(self, full_address: str) -> Optional[AddressValidation]:
        """Validate and geocode via Google Geocoding API."""
        if not self.google_api_key:
            logger.debug("Google Geocoding API key not configured, skipping")
            return None

        url = 'https://maps.googleapis.com/maps/api/geocode/json'
        params = {
            'address': full_address,
            'key': self.google_api_key,
            'region': 'au',
            'components': 'country:AU',
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get('status') != 'OK' or not data.get('results'):
                    return None

                result = data['results'][0]
                location = result['geometry']['location']
                components = {
                    c['types'][0]: c for c in result.get('address_components', [])
                    if c.get('types')
                }

                suburb = components.get('locality', {}).get('long_name', '')
                state = components.get('administrative_area_level_1', {}).get('short_name', '')
                postcode = components.get('postal_code', {}).get('long_name', '')

                # Determine confidence from location_type
                loc_type = result.get('geometry', {}).get('location_type', '')
                confidence_map = {
                    'ROOFTOP': 0.95,
                    'RANGE_INTERPOLATED': 0.8,
                    'GEOMETRIC_CENTER': 0.6,
                    'APPROXIMATE': 0.4,
                }
                confidence = confidence_map.get(loc_type, 0.5)

                return AddressValidation(
                    is_valid=confidence >= 0.5,
                    normalized_address=result.get('formatted_address', full_address),
                    suburb=suburb,
                    state=state,
                    postcode=postcode,
                    latitude=location['lat'],
                    longitude=location['lng'],
                    confidence=confidence,
                    source='google',
                )
        except (httpx.HTTPError, httpx.TimeoutException, KeyError, ValueError) as exc:
            logger.warning("Google Geocoding validation failed: %s", exc)
            return None
