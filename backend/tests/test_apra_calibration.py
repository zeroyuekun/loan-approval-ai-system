"""Tests for APRA calibration data — MacroDataService APRA methods and benchmarks.

Pure computation tests, no Django DB required.
"""

import pytest

from apps.ml_engine.services.external.macro_data import MacroDataService

# APRA benchmarks are a class attribute on MacroDataService
APRA_QUARTERLY_BENCHMARKS = MacroDataService.APRA_QUARTERLY_BENCHMARKS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def macro_svc():
    return MacroDataService()


REQUIRED_APRA_KEYS = {
    "npl_rate",
    "arrears_30_rate",
    "arrears_60_rate",
    "arrears_90_rate",
    "total_arrears_rate",
    "lvr_80_plus_pct",
    "dti_6_plus_pct",
    "by_state",
    "published_date",
}

AUSTRALIAN_STATES = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"]


# ===========================================================================
# APRA Data Tests (MacroDataService)
# ===========================================================================


class TestGetApraQuarterlyArrears:
    def test_returns_latest_quarter_by_default(self, macro_svc):
        result = macro_svc.get_apra_quarterly_arrears()
        assert isinstance(result, dict)
        assert "npl_rate" in result

    def test_returns_specific_quarter(self, macro_svc):
        known_key = list(APRA_QUARTERLY_BENCHMARKS.keys())[0]
        result = macro_svc.get_apra_quarterly_arrears(known_key)
        assert result["npl_rate"] == APRA_QUARTERLY_BENCHMARKS[known_key]["npl_rate"]

    def test_invalid_quarter_returns_fallback(self, macro_svc):
        result = macro_svc.get_apra_quarterly_arrears("Q99_2099")
        assert isinstance(result, dict)
        assert "npl_rate" in result

    def test_returned_dict_has_all_expected_keys(self, macro_svc):
        result = macro_svc.get_apra_quarterly_arrears()
        assert REQUIRED_APRA_KEYS.issubset(set(result.keys()))

    def test_all_rates_between_zero_and_one(self, macro_svc):
        result = macro_svc.get_apra_quarterly_arrears()
        for key in [
            "npl_rate",
            "arrears_30_rate",
            "arrears_60_rate",
            "arrears_90_rate",
            "total_arrears_rate",
            "lvr_80_plus_pct",
            "dti_6_plus_pct",
        ]:
            assert 0 <= result[key] <= 1, f"{key}={result[key]} outside [0,1]"


class TestGetApraStateArrears:
    def test_valid_state_returns_float(self, macro_svc):
        result = macro_svc.get_apra_state_arrears("NSW")
        assert isinstance(result, float)
        assert result > 0

    def test_all_states_return_floats(self, macro_svc):
        for state in AUSTRALIAN_STATES:
            result = macro_svc.get_apra_state_arrears(state)
            assert isinstance(result, float)
            assert 0 <= result <= 1

    def test_invalid_state_handles_gracefully(self, macro_svc):
        try:
            result = macro_svc.get_apra_state_arrears("INVALID")
            assert result is None or isinstance(result, (int, float))
        except (KeyError, ValueError):
            pass  # Acceptable: explicitly raising for invalid state


class TestApraBenchmarkData:
    def test_apra_data_integrity(self):
        for quarter, data in APRA_QUARTERLY_BENCHMARKS.items():
            assert REQUIRED_APRA_KEYS.issubset(set(data.keys())), (
                f"{quarter} missing keys: {REQUIRED_APRA_KEYS - set(data.keys())}"
            )
            assert isinstance(data["by_state"], dict)
            assert len(data["by_state"]) >= 6
            for state, rate in data["by_state"].items():
                assert 0 <= rate <= 1, f"{quarter}/{state}: {rate} outside [0,1]"
