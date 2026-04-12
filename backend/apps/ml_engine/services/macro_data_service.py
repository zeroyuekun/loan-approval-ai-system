"""Australian macroeconomic data service — fetches real economic indicators from public APIs.

Data sources (all free, no API key required for ABS/World Bank):
- ABS Data API (data.api.abs.gov.au): unemployment, CPI, labour force
- World Bank API (api.worldbank.org): GDP growth, inflation
- FRED API (fred.stlouisfed.org): global interest rates, housing indices (free key)

These replace hardcoded lookup tables in the data generator with real government data.
"""

import logging
import os
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# Cache TTL: economic data updates quarterly at most
_CACHE_TTL_HOURS = 24

# Valid ranges from predictor.FEATURE_BOUNDS — we clip to these
_FEATURE_BOUNDS = {
    "rba_cash_rate": (0, 20),
    "unemployment_rate": (0, 30),
    "property_growth_12m": (-50, 100),
    "consumer_confidence": (0, 200),
    "gdp_growth": (-25, 50),
}

# Hardcoded fallback values (recent actuals) used when APIs are unreachable
_FALLBACKS = {
    "rba_cash_rate": 4.35,
    "unemployment_rate": 4.1,
    "property_growth_12m": 5.0,
    "consumer_confidence": 85.0,
    "gdp_growth": 2.1,
}

# ABS state/region codes for SDMX key construction.
# Verified against ABS Data API dimension values (March 2026).
_ABS_STATE_CODES = {
    "NSW": "1",
    "VIC": "2",
    "QLD": "3",
    "SA": "4",
    "WA": "5",
    "TAS": "6",
    "NT": "7",
    "ACT": "8",
    "national": "AUS",
}

# RPPI uses capital-city region codes (not state numbers)
_ABS_RPPI_REGION_CODES = {
    "NSW": "1GSYD",
    "VIC": "2GMEL",
    "QLD": "3GBRI",
    "SA": "4GADE",
    "WA": "5GPER",
    "TAS": "6GHOB",
    "NT": "7GDAR",
    "ACT": "8ACTE",
    "national": "100",  # Weighted average of eight capital cities
}


class MacroDataService:
    """Fetches Australian macroeconomic indicators from public APIs."""

    def __init__(self):
        self.timeout = httpx.Timeout(15.0, connect=5.0)
        self.fred_api_key = os.environ.get("FRED_API_KEY", "")
        self._cache: dict = {}
        self._cache_timestamps: dict[str, datetime] = {}
        # NOTE (ML-H4): Cache is instance-level. For APRA benchmarks this is
        # fine (dict lookup, no HTTP). For live macro data, consider using a
        # module-level singleton or Django cache to avoid repeated HTTP calls.

    # ------------------------------------------------------------------
    # Public getters
    # ------------------------------------------------------------------

    def get_rba_cash_rate(self) -> float:
        """Fetch current RBA cash rate target.

        Source: RBA Statistical Tables via FRED (series: RBATCTR)
        Fallback: hardcoded recent value if API fails.
        """
        return self._fetch_with_cache(
            "rba_cash_rate",
            self._fetch_rba_cash_rate,
        )

    def get_unemployment_rate(self, state: str = "national") -> float:
        """Fetch Australian unemployment rate.

        Source: ABS Labour Force Survey (catalogue 6202.0)
        API: data.api.abs.gov.au
        Fallback: hardcoded recent value if API fails.
        """
        cache_key = f"unemployment_rate_{state}"
        return self._fetch_with_cache(
            cache_key,
            lambda: self._fetch_unemployment(state),
        )

    def get_property_growth(self, state: str = "national") -> float:
        """Fetch 12-month residential property price growth.

        Source: ABS Residential Property Price Indexes (catalogue 6416.0)
        Fallback: hardcoded recent value if API fails.
        """
        cache_key = f"property_growth_12m_{state}"
        return self._fetch_with_cache(
            cache_key,
            lambda: self._fetch_property_growth(state),
        )

    def get_consumer_confidence(self) -> float:
        """Fetch consumer confidence index.

        Source: World Bank Consumer Confidence indicator or FRED
        Fallback: hardcoded recent value if API fails.
        """
        return self._fetch_with_cache(
            "consumer_confidence",
            self._fetch_consumer_confidence,
        )

    def get_gdp_growth(self) -> float:
        """Fetch Australian GDP growth rate.

        Source: World Bank API (indicator NY.GDP.MKTP.KD.ZG)
        Fallback: hardcoded recent value if API fails.
        """
        return self._fetch_with_cache(
            "gdp_growth",
            self._fetch_gdp_growth,
        )

    def get_all_macro_indicators(self, state: str = "national") -> dict:
        """Fetch all macro indicators in one call.

        Returns dict with: rba_cash_rate, unemployment_rate, property_growth_12m,
        consumer_confidence, gdp_growth — all validated against FEATURE_BOUNDS.
        """
        return {
            "rba_cash_rate": self.get_rba_cash_rate(),
            "unemployment_rate": self.get_unemployment_rate(state),
            "property_growth_12m": self.get_property_growth(state),
            "consumer_confidence": self.get_consumer_confidence(),
            "gdp_growth": self.get_gdp_growth(),
        }

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _fetch_with_cache(self, cache_key: str, fetch_fn, ttl_hours: int = _CACHE_TTL_HOURS):
        """Generic cache-or-fetch pattern with TTL."""
        now = datetime.now(UTC)
        ts = self._cache_timestamps.get(cache_key)
        if ts and cache_key in self._cache:
            if (now - ts) < timedelta(hours=ttl_hours):
                logger.debug("Cache hit for %s", cache_key)
                return self._cache[cache_key]

        try:
            value = fetch_fn()
        except Exception:
            # Serve stale cache if available, otherwise fallback
            if cache_key in self._cache:
                logger.warning(
                    "API fetch failed for %s — serving stale cache",
                    cache_key,
                )
                return self._cache[cache_key]
            # Determine fallback key from cache_key (strip state suffix)
            fallback_key = cache_key.split("_")[0]
            # Try exact match first, then strip suffixes
            for fk in (cache_key, fallback_key):
                if fk in _FALLBACKS:
                    logger.warning(
                        "API fetch failed for %s — using hardcoded fallback",
                        cache_key,
                    )
                    return _FALLBACKS[fk]
            # Last resort: try matching by prefix
            for fk, fv in _FALLBACKS.items():
                if cache_key.startswith(fk):
                    logger.warning(
                        "API fetch failed for %s — using fallback for %s",
                        cache_key,
                        fk,
                    )
                    return fv
            raise

        self._cache[cache_key] = value
        self._cache_timestamps[cache_key] = now
        return value

    # ------------------------------------------------------------------
    # Internal fetch + parse methods
    # ------------------------------------------------------------------

    def _fetch_rba_cash_rate(self) -> float:
        """Fetch RBA cash rate from FRED series RBATCTR."""
        if self.fred_api_key:
            try:
                data = self._fetch_fred("RBATCTR")
                observations = data.get("observations", [])
                if observations:
                    raw = float(observations[-1]["value"])
                    return self._clip("rba_cash_rate", raw)
            except Exception as exc:
                logger.warning("FRED fetch for RBA cash rate failed: %s", exc)

        # Fallback if no FRED key or FRED failed
        logger.info("Using fallback RBA cash rate")
        return _FALLBACKS["rba_cash_rate"]

    def _fetch_unemployment(self, state: str) -> float:
        """Fetch unemployment rate from ABS Labour Force Survey (cat 6202.0).

        Verified key structure (March 2026):
          Dataflow: LF (short ID, NOT "ABS,LF_M")
          Key: MEASURE.SEX.AGE.TSEST.REGION.FREQ
          M13 = Unemployment rate, 3 = Persons, 1599 = 15+,
          20 = Seasonally adjusted, region code, M = Monthly
        """
        state_code = _ABS_STATE_CODES.get(state, "AUS")
        sdmx_key = f"M13.3.1599.20.{state_code}.M"
        try:
            data = self._fetch_abs_data("LF", sdmx_key)
            value = self._parse_abs_latest_value(data)
            if value is not None:
                return self._clip("unemployment_rate", value)
        except Exception as exc:
            logger.warning("ABS fetch for unemployment (%s) failed: %s", state, exc)

        logger.info("Using fallback unemployment rate for %s", state)
        return _FALLBACKS["unemployment_rate"]

    def _fetch_property_growth(self, state: str) -> float:
        """Fetch property price growth from ABS RPPI (cat 6416.0).

        Verified key structure (March 2026):
          Dataflow: RPPI (short ID)
          Key: MEASURE.PROPERTY_TYPE.REGION.FREQ
          3 = % change from corresponding quarter, 3 = Residential property,
          region code (capital city codes), Q = Quarterly
        """
        region_code = _ABS_RPPI_REGION_CODES.get(state, "100")
        sdmx_key = f"3.3.{region_code}.Q"
        try:
            data = self._fetch_abs_data("RPPI", sdmx_key)
            value = self._parse_abs_latest_value(data)
            if value is not None:
                return self._clip("property_growth_12m", value)
        except Exception as exc:
            logger.warning("ABS fetch for property growth (%s) failed: %s", state, exc)

        logger.info("Using fallback property growth for %s", state)
        return _FALLBACKS["property_growth_12m"]

    def _fetch_consumer_confidence(self) -> float:
        """Fetch consumer confidence from World Bank or FRED."""
        # Try World Bank first (no key needed)
        try:
            data = self._fetch_world_bank("CSCICP03USM665S", "AUS")
            # World Bank consumer confidence data may not be available for AUS,
            # fall through to FRED if it is empty
            if data and len(data) > 1 and data[1]:
                for entry in data[1]:
                    if entry.get("value") is not None:
                        raw = float(entry["value"])
                        return self._clip("consumer_confidence", raw)
        except Exception as exc:
            logger.warning("World Bank fetch for consumer confidence failed: %s", exc)

        # Try FRED (Westpac-Melbourne CCI is not on FRED, use OECD CCI as proxy)
        if self.fred_api_key:
            try:
                data = self._fetch_fred("CSCICP03AUM665S")
                observations = data.get("observations", [])
                if observations:
                    raw = float(observations[-1]["value"])
                    return self._clip("consumer_confidence", raw)
            except Exception as exc:
                logger.warning("FRED fetch for consumer confidence failed: %s", exc)

        logger.info("Using fallback consumer confidence")
        return _FALLBACKS["consumer_confidence"]

    def _fetch_gdp_growth(self) -> float:
        """Fetch Australian GDP growth from World Bank."""
        try:
            data = self._fetch_world_bank("NY.GDP.MKTP.KD.ZG", "AUS")
            if data and len(data) > 1 and data[1]:
                for entry in data[1]:
                    if entry.get("value") is not None:
                        raw = float(entry["value"])
                        return self._clip("gdp_growth", raw)
        except Exception as exc:
            logger.warning("World Bank fetch for GDP growth failed: %s", exc)

        logger.info("Using fallback GDP growth")
        return _FALLBACKS["gdp_growth"]

    # ------------------------------------------------------------------
    # Low-level API clients
    # ------------------------------------------------------------------

    def _fetch_abs_data(self, dataflow_id: str, key: str) -> dict:
        """Fetch from ABS Data API (SDMX-JSON format).

        Base URL: https://data.api.abs.gov.au/rest/data/{dataflow_id}/{key}
        No API key required. Returns JSON.
        """
        url = f"https://data.api.abs.gov.au/rest/data/{dataflow_id}/{key}"
        headers = {"Accept": "application/vnd.sdmx.data+json;version=2.0.0"}
        logger.info("Fetching ABS data: %s", url)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    def _fetch_world_bank(self, indicator: str, country: str = "AUS") -> dict:
        """Fetch from World Bank Indicators API.

        URL: https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json
        No API key required.
        """
        url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&per_page=5&mrnev=1"
        logger.info("Fetching World Bank data: %s/%s", indicator, country)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def _fetch_fred(self, series_id: str) -> dict:
        """Fetch from FRED API.

        URL: https://api.stlouisfed.org/fred/series/observations
        Requires FRED_API_KEY environment variable.
        """
        if not self.fred_api_key:
            raise ValueError("FRED_API_KEY not configured")

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        }
        logger.info("Fetching FRED series: %s", series_id)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    def _parse_abs_latest_value(self, data: dict) -> float | None:
        """Extract the most recent observation value from an ABS SDMX-JSON response.

        The SDMX-JSON 2.0 structure nests observations under:
        data -> dataSets[0] -> observations -> {"0:0:...": [value]}
        Observations are keyed by colon-separated dimension indices.
        """
        try:
            datasets = data.get("data", {}).get("dataSets", [])
            if not datasets:
                return None

            observations = datasets[0].get("observations", {})
            if not observations:
                # Try series-level structure (some ABS endpoints)
                series = datasets[0].get("series", {})
                if series:
                    # Get the first (or only) series
                    first_series = next(iter(series.values()), {})
                    observations = first_series.get("observations", {})

            if not observations:
                return None

            # Observations are keyed by index strings; get the last one
            last_key = max(observations.keys(), key=lambda k: int(k.split(":")[-1]))
            value_array = observations[last_key]
            if value_array and value_array[0] is not None:
                return float(value_array[0])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse ABS SDMX-JSON response: %s", exc)

        return None

    def _parse_abs_property_growth(self, data: dict) -> float | None:
        """Parse ABS RPPI data and compute 12-month growth from index values.

        Takes the last 5 quarterly observations (current + 4 prior) and computes
        year-on-year percentage change.
        """
        try:
            datasets = data.get("data", {}).get("dataSets", [])
            if not datasets:
                return None

            observations = datasets[0].get("observations", {})
            if not observations:
                series = datasets[0].get("series", {})
                if series:
                    first_series = next(iter(series.values()), {})
                    observations = first_series.get("observations", {})

            if not observations or len(observations) < 5:
                return None

            # Sort by index, get last 5 quarters
            sorted_keys = sorted(observations.keys(), key=lambda k: int(k.split(":")[-1]))
            current_val = observations[sorted_keys[-1]][0]
            year_ago_val = observations[sorted_keys[-5]][0]

            if year_ago_val and current_val:
                growth = ((float(current_val) - float(year_ago_val)) / float(year_ago_val)) * 100
                return round(growth, 1)
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
            logger.warning("Failed to parse ABS RPPI data: %s", exc)

        return None

    # ------------------------------------------------------------------
    # APRA Quarterly ADI Property Exposure benchmarks
    # ------------------------------------------------------------------

    # APRA Quarterly ADI Property Exposure benchmarks (Sep Q 2025)
    # Source: apra.gov.au/quarterly-authorised-deposit-taking-institution-statistics
    # No REST API — values transcribed from published XLSX releases.
    # Updated quarterly; hardcoded with published_date for audit trail.
    APRA_QUARTERLY_BENCHMARKS = {
        "Q3_2025": {
            "published_date": "2025-11-28",
            "npl_rate": 0.0104,
            "arrears_30_rate": 0.0031,
            "arrears_60_rate": 0.0013,
            "arrears_90_rate": 0.0047,
            "total_arrears_rate": 0.0091,
            "lvr_80_plus_pct": 0.308,
            "dti_6_plus_pct": 0.061,
            "owner_occupier_arrears_90": 0.0042,
            "investor_arrears_90": 0.0057,
            "by_state": {
                "NSW": 0.0039,
                "VIC": 0.0052,
                "QLD": 0.0048,
                "WA": 0.0055,
                "SA": 0.0041,
                "TAS": 0.0035,
                "NT": 0.0068,
                "ACT": 0.0028,
            },
        },
        "Q2_2025": {
            "published_date": "2025-08-29",
            "npl_rate": 0.0098,
            "arrears_30_rate": 0.0029,
            "arrears_60_rate": 0.0012,
            "arrears_90_rate": 0.0044,
            "total_arrears_rate": 0.0085,
            "lvr_80_plus_pct": 0.312,
            "dti_6_plus_pct": 0.058,
            "owner_occupier_arrears_90": 0.0039,
            "investor_arrears_90": 0.0053,
            "by_state": {
                "NSW": 0.0037,
                "VIC": 0.0049,
                "QLD": 0.0045,
                "WA": 0.0052,
                "SA": 0.0038,
                "TAS": 0.0033,
                "NT": 0.0065,
                "ACT": 0.0026,
            },
        },
    }

    def _latest_apra_quarter(self) -> str:
        """Return the key for the most recent APRA quarterly benchmark."""
        return max(self.APRA_QUARTERLY_BENCHMARKS.keys())

    def get_apra_quarterly_arrears(self, quarter: str = None) -> dict:
        """Fetch APRA quarterly ADI property exposure benchmarks.

        APRA publishes via XLSX (no REST API), so we maintain a transcribed
        lookup table updated when new quarterly data is published.

        Source: apra.gov.au/quarterly-authorised-deposit-taking-institution-statistics

        Args:
            quarter: e.g. 'Q3_2025'. Defaults to latest available.

        Returns dict with: npl_rate, arrears_30/60/90_rate, total_arrears_rate,
            lvr_80_plus_pct, dti_6_plus_pct, by_state, published_date
        """
        if quarter is None:
            quarter = self._latest_apra_quarter()

        benchmarks = self.APRA_QUARTERLY_BENCHMARKS.get(quarter)
        if benchmarks is None:
            available = sorted(self.APRA_QUARTERLY_BENCHMARKS.keys())
            logger.warning(
                "APRA quarter %s not available — available quarters: %s. Falling back to latest.",
                quarter,
                available,
            )
            quarter = self._latest_apra_quarter()
            benchmarks = self.APRA_QUARTERLY_BENCHMARKS[quarter]

        logger.info(
            "Returning APRA benchmarks for %s (published %s)",
            quarter,
            benchmarks["published_date"],
        )
        return {**benchmarks, "quarter": quarter}

    def get_apra_state_arrears(self, state: str, quarter: str = None) -> float:
        """Get 90+ day arrears rate for a specific state from APRA data.

        Args:
            state: Australian state code (e.g. 'NSW', 'VIC').
            quarter: e.g. 'Q3_2025'. Defaults to latest available.

        Returns:
            90+ day arrears rate as a float (e.g. 0.0039 for NSW).

        Raises:
            ValueError: If the state code is not found in APRA data.
        """
        data = self.get_apra_quarterly_arrears(quarter)
        by_state = data.get("by_state", {})

        state_upper = state.upper()
        if state_upper not in by_state:
            valid_states = sorted(by_state.keys())
            raise ValueError(f"State {state!r} not found in APRA data. Valid states: {valid_states}")

        rate = by_state[state_upper]
        logger.info(
            "APRA 90+ day arrears for %s (%s): %.4f",
            state_upper,
            data["quarter"],
            rate,
        )
        return rate

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _clip(indicator: str, value: float) -> float:
        """Clip a value to the valid FEATURE_BOUNDS range for the given indicator."""
        bounds = _FEATURE_BOUNDS.get(indicator)
        if bounds:
            lo, hi = bounds
            clipped = max(lo, min(hi, value))
            if clipped != value:
                logger.warning(
                    "Clipped %s from %.2f to %.2f (bounds: %s)",
                    indicator,
                    value,
                    clipped,
                    bounds,
                )
            return float(clipped)
        return value
