"""SA3-level property price and rental data for synthetic loan data calibration.

Provides sub-state geographic granularity using ABS Statistical Area Level 3
(SA3) regions (~350 regions nationally, ~50 key regions seeded here).

Data sources:
- ABS Census 2021 (abs.gov.au): SA3 population weights, median house prices
- ABS Residential Property Price Index cat 6416.0 (data.api.abs.gov.au):
  quarterly capital city property price growth rates
- Domain/CoreLogic published median reports: cross-referenced for multipliers

Property and rental multipliers are relative to the STATE median house price
already defined in DataGenerator.STATE_PROFILES (data_generator.py). This
avoids double-counting: the state median sets the baseline, and the SA3
multiplier adjusts within that state.
"""

import copy
import logging
import math
from datetime import datetime, timedelta

import httpx
import numpy as np

logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 168  # 7 days — RPPI updates quarterly


# =====================================================================
# SA3 Seed Data — ABS Census 2021 + CoreLogic/Domain median reports
#
# Each entry:
#   code:             ABS SA3 5-digit code (string)
#   name:             Human-readable SA3 name
#   state:            Parent state/territory code
#   population_weight: Relative population within state (sums to ~1.0)
#   property_mult:    Property price multiplier vs state median
#   rental_mult:      Rental cost multiplier vs state median
# =====================================================================

_SA3_SEED_DATA: list[dict] = [
    # --- NSW (pop weights sum to 1.00) ---
    {
        "code": "11703",
        "name": "Sydney City and Inner South",
        "state": "NSW",
        "population_weight": 0.08,
        "property_mult": 1.85,
        "rental_mult": 1.75,
    },
    {
        "code": "11602",
        "name": "Eastern Suburbs - North",
        "state": "NSW",
        "population_weight": 0.05,
        "property_mult": 2.10,
        "rental_mult": 1.90,
    },
    {
        "code": "11501",
        "name": "Inner West",
        "state": "NSW",
        "population_weight": 0.06,
        "property_mult": 1.45,
        "rental_mult": 1.35,
    },
    {
        "code": "11201",
        "name": "North Sydney - Mosman",
        "state": "NSW",
        "population_weight": 0.07,
        "property_mult": 1.70,
        "rental_mult": 1.55,
    },
    {
        "code": "11801",
        "name": "Parramatta",
        "state": "NSW",
        "population_weight": 0.09,
        "property_mult": 0.85,
        "rental_mult": 0.90,
    },
    {
        "code": "11101",
        "name": "Blacktown - North",
        "state": "NSW",
        "population_weight": 0.10,
        "property_mult": 0.65,
        "rental_mult": 0.70,
    },
    {
        "code": "10201",
        "name": "Central Coast - Gosford",
        "state": "NSW",
        "population_weight": 0.08,
        "property_mult": 0.55,
        "rental_mult": 0.60,
    },
    {
        "code": "11301",
        "name": "Newcastle",
        "state": "NSW",
        "population_weight": 0.09,
        "property_mult": 0.60,
        "rental_mult": 0.65,
    },
    {
        "code": "10401",
        "name": "Illawarra",
        "state": "NSW",
        "population_weight": 0.07,
        "property_mult": 0.65,
        "rental_mult": 0.70,
    },
    {
        "code": "19999",
        "name": "Rest of NSW",
        "state": "NSW",
        "population_weight": 0.31,
        "property_mult": 0.50,
        "rental_mult": 0.55,
    },
    # --- VIC (pop weights sum to 1.00) ---
    {
        "code": "20604",
        "name": "Melbourne City",
        "state": "VIC",
        "population_weight": 0.10,
        "property_mult": 1.80,
        "rental_mult": 1.70,
    },
    {
        "code": "20901",
        "name": "Boroondara",
        "state": "VIC",
        "population_weight": 0.08,
        "property_mult": 1.90,
        "rental_mult": 1.65,
    },
    {
        "code": "21001",
        "name": "Stonnington - West",
        "state": "VIC",
        "population_weight": 0.07,
        "property_mult": 1.65,
        "rental_mult": 1.55,
    },
    {
        "code": "21201",
        "name": "Maroondah - Ringwood",
        "state": "VIC",
        "population_weight": 0.12,
        "property_mult": 0.85,
        "rental_mult": 0.80,
    },
    {
        "code": "21401",
        "name": "Melton - Bacchus Marsh",
        "state": "VIC",
        "population_weight": 0.14,
        "property_mult": 0.65,
        "rental_mult": 0.65,
    },
    {
        "code": "20201",
        "name": "Geelong",
        "state": "VIC",
        "population_weight": 0.10,
        "property_mult": 0.60,
        "rental_mult": 0.60,
    },
    {
        "code": "29999",
        "name": "Rest of VIC",
        "state": "VIC",
        "population_weight": 0.39,
        "property_mult": 0.50,
        "rental_mult": 0.50,
    },
    # --- QLD (pop weights sum to 1.00) ---
    {
        "code": "30101",
        "name": "Brisbane Inner City",
        "state": "QLD",
        "population_weight": 0.08,
        "property_mult": 1.40,
        "rental_mult": 1.35,
    },
    {
        "code": "30301",
        "name": "Brisbane South",
        "state": "QLD",
        "population_weight": 0.10,
        "property_mult": 0.90,
        "rental_mult": 0.90,
    },
    {
        "code": "30201",
        "name": "Brisbane North",
        "state": "QLD",
        "population_weight": 0.10,
        "property_mult": 0.95,
        "rental_mult": 0.92,
    },
    {
        "code": "31001",
        "name": "Gold Coast - North",
        "state": "QLD",
        "population_weight": 0.12,
        "property_mult": 1.10,
        "rental_mult": 1.05,
    },
    {
        "code": "31601",
        "name": "Sunshine Coast",
        "state": "QLD",
        "population_weight": 0.08,
        "property_mult": 1.05,
        "rental_mult": 1.00,
    },
    {
        "code": "30601",
        "name": "Cairns",
        "state": "QLD",
        "population_weight": 0.06,
        "property_mult": 0.55,
        "rental_mult": 0.55,
    },
    {
        "code": "31801",
        "name": "Townsville",
        "state": "QLD",
        "population_weight": 0.06,
        "property_mult": 0.50,
        "rental_mult": 0.50,
    },
    {
        "code": "39999",
        "name": "Rest of QLD",
        "state": "QLD",
        "population_weight": 0.40,
        "property_mult": 0.45,
        "rental_mult": 0.45,
    },
    # --- WA (pop weights sum to 1.00) ---
    {
        "code": "50302",
        "name": "Perth City",
        "state": "WA",
        "population_weight": 0.10,
        "property_mult": 1.50,
        "rental_mult": 1.40,
    },
    {
        "code": "50402",
        "name": "Stirling",
        "state": "WA",
        "population_weight": 0.15,
        "property_mult": 1.10,
        "rental_mult": 1.05,
    },
    {
        "code": "50601",
        "name": "Gosnells",
        "state": "WA",
        "population_weight": 0.15,
        "property_mult": 0.75,
        "rental_mult": 0.75,
    },
    {
        "code": "50101",
        "name": "Mandurah",
        "state": "WA",
        "population_weight": 0.10,
        "property_mult": 0.60,
        "rental_mult": 0.60,
    },
    {
        "code": "59999",
        "name": "Rest of WA",
        "state": "WA",
        "population_weight": 0.50,
        "property_mult": 0.50,
        "rental_mult": 0.50,
    },
    # --- SA (pop weights sum to 1.00) ---
    {
        "code": "40101",
        "name": "Adelaide City",
        "state": "SA",
        "population_weight": 0.10,
        "property_mult": 1.40,
        "rental_mult": 1.35,
    },
    {
        "code": "40201",
        "name": "Adelaide Hills",
        "state": "SA",
        "population_weight": 0.10,
        "property_mult": 1.30,
        "rental_mult": 1.15,
    },
    {
        "code": "40501",
        "name": "Charles Sturt",
        "state": "SA",
        "population_weight": 0.15,
        "property_mult": 0.85,
        "rental_mult": 0.85,
    },
    {
        "code": "40601",
        "name": "Salisbury",
        "state": "SA",
        "population_weight": 0.15,
        "property_mult": 0.65,
        "rental_mult": 0.65,
    },
    {
        "code": "49999",
        "name": "Rest of SA",
        "state": "SA",
        "population_weight": 0.50,
        "property_mult": 0.50,
        "rental_mult": 0.50,
    },
    # --- TAS (pop weights sum to 1.00) ---
    {
        "code": "60101",
        "name": "Hobart Inner",
        "state": "TAS",
        "population_weight": 0.15,
        "property_mult": 1.35,
        "rental_mult": 1.30,
    },
    {
        "code": "60102",
        "name": "Hobart - South and West",
        "state": "TAS",
        "population_weight": 0.15,
        "property_mult": 1.00,
        "rental_mult": 1.00,
    },
    {
        "code": "60201",
        "name": "Launceston",
        "state": "TAS",
        "population_weight": 0.15,
        "property_mult": 0.70,
        "rental_mult": 0.70,
    },
    {
        "code": "69999",
        "name": "Rest of TAS",
        "state": "TAS",
        "population_weight": 0.55,
        "property_mult": 0.55,
        "rental_mult": 0.55,
    },
    # --- ACT (pop weights sum to 1.00) ---
    {
        "code": "80101",
        "name": "North Canberra",
        "state": "ACT",
        "population_weight": 0.20,
        "property_mult": 1.20,
        "rental_mult": 1.15,
    },
    {
        "code": "80102",
        "name": "South Canberra",
        "state": "ACT",
        "population_weight": 0.20,
        "property_mult": 1.10,
        "rental_mult": 1.10,
    },
    {
        "code": "80103",
        "name": "Woden Valley",
        "state": "ACT",
        "population_weight": 0.15,
        "property_mult": 1.05,
        "rental_mult": 1.05,
    },
    {
        "code": "80104",
        "name": "Tuggeranong",
        "state": "ACT",
        "population_weight": 0.25,
        "property_mult": 0.80,
        "rental_mult": 0.80,
    },
    {
        "code": "80105",
        "name": "Belconnen",
        "state": "ACT",
        "population_weight": 0.20,
        "property_mult": 0.85,
        "rental_mult": 0.85,
    },
    # --- NT (pop weights sum to 1.00) ---
    {
        "code": "70101",
        "name": "Darwin City",
        "state": "NT",
        "population_weight": 0.45,
        "property_mult": 1.10,
        "rental_mult": 1.10,
    },
    {
        "code": "79999",
        "name": "Rest of NT",
        "state": "NT",
        "population_weight": 0.55,
        "property_mult": 0.60,
        "rental_mult": 0.60,
    },
]


# =====================================================================
# SA4-to-SA3 mapping — links SA4 unemployment data to SA3 regions
#
# SA4 codes from ABS ASGS 2021. Each SA4 maps to the SA3 codes above
# that fall within its boundary. SA3s using catch-all "rest-of" codes
# (x9999) are included in broad regional SA4s.
# =====================================================================

_SA4_TO_SA3: dict[str, list[str]] = {
    # NSW
    "117": ["11703"],  # Sydney - City and Inner South
    "116": ["11602"],  # Sydney - Eastern Suburbs
    "115": ["11501"],  # Sydney - Inner West
    "112": ["11201"],  # Sydney - Northern Beaches / North Sydney
    "118": ["11801"],  # Sydney - Parramatta
    "111": ["11101"],  # Sydney - South West / Blacktown
    "102": ["10201"],  # Central Coast
    "113": ["11301"],  # Hunter Valley exc Newcastle / Newcastle
    "104": ["10401"],  # Illawarra
    "199": ["19999"],  # Rest of NSW (regional)
    # VIC
    "206": ["20604"],  # Melbourne - Inner
    "209": ["20901"],  # Melbourne - Inner East
    "210": ["21001"],  # Melbourne - Inner South
    "212": ["21201"],  # Melbourne - Outer East
    "214": ["21401"],  # Melbourne - West
    "202": ["20201"],  # Geelong
    "299": ["29999"],  # Rest of VIC (regional)
    # QLD
    "301": ["30101"],  # Brisbane Inner City
    "303": ["30301"],  # Brisbane - South
    "302": ["30201"],  # Brisbane - North
    "310": ["31001"],  # Gold Coast
    "316": ["31601"],  # Sunshine Coast
    "306": ["30601"],  # Cairns
    "318": ["31801"],  # Townsville
    "399": ["39999"],  # Rest of QLD (regional)
    # WA
    "503": ["50302"],  # Perth - Inner
    "504": ["50402"],  # Perth - North West
    "506": ["50601"],  # Perth - South East
    "501": ["50101"],  # Mandurah
    "599": ["59999"],  # Rest of WA (regional)
    # SA
    "401": ["40101"],  # Adelaide - Central and Hills
    "402": ["40201"],  # Adelaide - North
    "405": ["40501"],  # Adelaide - West
    "406": ["40601"],  # Adelaide - South
    "499": ["49999"],  # Rest of SA (regional)
    # TAS
    "601": ["60101", "60102"],  # Greater Hobart
    "602": ["60201"],  # Launceston and North East
    "699": ["69999"],  # Rest of TAS (regional)
    # ACT
    "801": ["80101", "80102", "80103", "80104", "80105"],  # Australian Capital Territory
    # NT
    "701": ["70101"],  # Darwin
    "799": ["79999"],  # Rest of NT (regional)
}


# =====================================================================
# Capital city to state mapping for RPPI growth application
# =====================================================================

_CAPITAL_CITY_STATE_MAP: dict[str, str] = {
    "Sydney": "NSW",
    "Melbourne": "VIC",
    "Brisbane": "QLD",
    "Perth": "WA",
    "Adelaide": "SA",
    "Hobart": "TAS",
    "Canberra": "ACT",
    "Darwin": "NT",
}


class PropertyDataService:
    """Provides sub-state property price and rental data at SA3 level.

    Used by DataGenerator to assign realistic geographic variation within
    each state. Property and rental multipliers are relative to the state
    median house price defined in STATE_PROFILES.

    Usage:
        svc = PropertyDataService()
        sa3_code, sa3_name, prop_mult, rent_mult = svc.assign_sa3("NSW", rng)
    """

    def __init__(self):
        self.timeout = httpx.Timeout(20.0, connect=5.0)
        self._cache: dict = {}
        self._cache_timestamps: dict[str, datetime] = {}

        # Build lookup structures from seed data
        self._sa3_by_code: dict[str, dict] = {}
        self._sa3_by_state: dict[str, list[dict]] = {}

        for entry in _SA3_SEED_DATA:
            entry_copy = copy.copy(entry)  # shallow copy — all values are scalars
            self._sa3_by_code[entry_copy["code"]] = entry_copy
            self._sa3_by_state.setdefault(entry_copy["state"], []).append(entry_copy)

        # Expose SA4→SA3 mapping as instance attribute for data_generator access
        self._sa4_to_sa3: dict[str, list[str]] = dict(_SA4_TO_SA3)

    # ------------------------------------------------------------------
    # Caching (same pattern as RealWorldBenchmarks / MacroDataService)
    # ------------------------------------------------------------------

    def _get_cached(self, cache_key: str) -> dict | None:
        """Return cached value if still within TTL, else None."""
        now = datetime.utcnow()
        ts = self._cache_timestamps.get(cache_key)
        if ts and cache_key in self._cache:
            if (now - ts) < timedelta(hours=_CACHE_TTL_HOURS):
                return self._cache[cache_key]
        return None

    def _set_cached(self, cache_key: str, value: dict) -> None:
        """Store value in cache with current timestamp."""
        self._cache[cache_key] = value
        self._cache_timestamps[cache_key] = datetime.utcnow()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def assign_sa3(self, state: str, rng: np.random.Generator) -> tuple[str, str, float, float]:
        """Assign an SA3 region within a state, weighted by population.

        Args:
            state: Australian state/territory code (e.g. "NSW", "VIC").
            rng: numpy random Generator instance for reproducible sampling.

        Returns:
            Tuple of (sa3_code, sa3_name, property_mult, rental_mult).
        """
        regions = self._sa3_by_state.get(state)
        if not regions:
            logger.warning("No SA3 data for state %s — returning neutral multipliers", state)
            return ("00000", f"Unknown ({state})", 1.0, 1.0)

        weights = np.array([r["population_weight"] for r in regions])
        # Normalise in case weights don't sum to exactly 1.0
        weights = weights / weights.sum()

        idx = rng.choice(len(regions), p=weights)
        chosen = regions[idx]
        return (
            chosen["code"],
            chosen["name"],
            chosen["property_mult"],
            chosen["rental_mult"],
        )

    def get_sa3_data(self, sa3_code: str) -> dict | None:
        """Get full SA3 data for a given code.

        Returns:
            Dict with keys: code, name, state, population_weight,
            property_mult, rental_mult. None if code not found.
        """
        return self._sa3_by_code.get(sa3_code)

    def get_state_sa3s(self, state: str) -> list[dict]:
        """Get all SA3 regions for a state.

        Args:
            state: Australian state/territory code (e.g. "NSW").

        Returns:
            List of SA3 dicts for the state, or empty list if unknown.
        """
        return self._sa3_by_state.get(state, [])

    async def fetch_rppi_growth(self) -> dict:
        """Fetch ABS Residential Property Price Index quarterly growth rates.

        Source: ABS cat 6416.0 via SDMX Data API.
        URL: https://data.api.abs.gov.au/rest/data/ABS,RPPI/...

        Returns:
            Dict mapping capital city name -> quarterly growth rate (float),
            e.g. {"Sydney": 0.012, "Melbourne": -0.003, ...}.
            Falls back to empty dict on any failure.
        """
        cached = self._get_cached("rppi_growth")
        if cached is not None:
            return cached

        try:
            # ABS RPPI dataflow: ABS,RPPI
            # Key: MEASURE.REGION.FREQ
            # Measure 1 = Index number, 2 = % change (quarterly)
            # Region: 1=Sydney, 2=Melbourne, 3=Brisbane, 4=Adelaide,
            #         5=Perth, 6=Hobart, 7=Darwin, 8=Canberra
            # Freq: Q = quarterly
            url = "https://data.api.abs.gov.au/rest/data/ABS,RPPI/2...Q"
            headers = {"Accept": "application/vnd.sdmx.data+json;version=2.0.0"}

            logger.info("Fetching ABS RPPI growth rates: %s", url)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()

            result = self._parse_rppi_response(data)
            if result:
                self._set_cached("rppi_growth", result)
                logger.info("RPPI growth rates fetched: %s", result)
                return result

        except Exception as exc:
            logger.warning("ABS RPPI fetch failed: %s — returning empty dict", exc)

        # Serve stale cache if available
        stale = self._cache.get("rppi_growth")
        if stale:
            logger.info("Serving stale RPPI cache")
            return stale

        return {}

    def _parse_rppi_response(self, data: dict) -> dict | None:
        """Parse ABS SDMX-JSON RPPI response into city -> growth dict.

        ABS RPPI regions are indexed 0-7 in the series dimension,
        corresponding to the 8 capital cities.
        """
        city_index_map = {
            0: "Sydney",
            1: "Melbourne",
            2: "Brisbane",
            3: "Adelaide",
            4: "Perth",
            5: "Hobart",
            6: "Darwin",
            7: "Canberra",
        }

        try:
            datasets = data.get("data", {}).get("dataSets", [])
            if not datasets:
                return None

            series = datasets[0].get("series", {})
            if not series:
                return None

            result = {}
            for series_key, series_data in series.items():
                # Series key format: "measure_idx:region_idx:freq_idx"
                # Region is always dimension position 1 in ABS RPPI dataflow
                parts = series_key.split(":")
                if len(parts) < 2:
                    continue
                try:
                    idx = int(parts[1])
                except (ValueError, TypeError):
                    continue
                if idx not in city_index_map:
                    continue
                observations = series_data.get("observations", {})
                if observations:
                    last_key = max(observations.keys(), key=lambda k: int(k.split(":")[-1]))
                    value = observations[last_key]
                    if value and value[0] is not None:
                        growth = float(value[0]) / 100.0
                        # Security: clamp to ±15% quarterly to prevent poisoned data
                        if math.isfinite(growth) and -0.15 <= growth <= 0.15:
                            result[city_index_map[idx]] = growth
                        else:
                            logger.warning(
                                "RPPI growth %.4f for %s outside ±15%% — skipped",
                                growth,
                                city_index_map.get(idx, idx),
                            )

            return result if result else None

        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse RPPI response: %s", exc)
            return None

    def apply_growth(self, capital_city_growth: dict) -> None:
        """Apply RPPI quarterly growth rates to update property multipliers.

        Adjusts property_mult for all SA3 regions in states whose capital
        city has a reported growth rate. Rental multipliers are adjusted
        at 60% of property growth (rents lag property prices).

        Args:
            capital_city_growth: Dict mapping capital city name to quarterly
                growth rate as a decimal (e.g. 0.012 for 1.2% growth).
        """
        if not capital_city_growth:
            return

        for city, growth_rate in capital_city_growth.items():
            state = _CAPITAL_CITY_STATE_MAP.get(city)
            if not state:
                continue

            regions = self._sa3_by_state.get(state, [])
            for region in regions:
                # Apply growth proportionally — higher-value areas move more
                region["property_mult"] = round(region["property_mult"] * (1.0 + growth_rate), 4)
                # Rents lag property prices — apply 60% of growth
                region["rental_mult"] = round(region["rental_mult"] * (1.0 + growth_rate * 0.6), 4)

            if regions:
                logger.info(
                    "Applied %.2f%% RPPI growth to %d SA3 regions in %s (%s)",
                    growth_rate * 100,
                    len(regions),
                    state,
                    city,
                )

    def get_calibration_data(self) -> dict:
        """Return full SA3 dataset as a dict for the calibration snapshot.

        Returns:
            Dict with keys:
            - "sa3_regions": dict of sa3_code -> region data
            - "sa4_to_sa3": dict of sa4_code -> list of sa3_codes
            - "generated_at": ISO timestamp
        """
        return {
            "sa3_regions": {
                code: {
                    "name": data["name"],
                    "state": data["state"],
                    "population_weight": data["population_weight"],
                    "property_mult": data["property_mult"],
                    "rental_mult": data["rental_mult"],
                }
                for code, data in self._sa3_by_code.items()
            },
            "sa4_to_sa3": dict(_SA4_TO_SA3),
            "generated_at": datetime.now(tz=None).isoformat(),
        }
