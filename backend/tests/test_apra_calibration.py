"""Tests for APRA calibration — MacroDataService APRA methods + CalibrationValidator.

Pure computation tests, no Django DB required.
"""

from datetime import datetime

import pytest

from apps.ml_engine.services.macro_data_service import MacroDataService

# APRA benchmarks are a class attribute on MacroDataService
APRA_QUARTERLY_BENCHMARKS = MacroDataService.APRA_QUARTERLY_BENCHMARKS
from apps.ml_engine.services.calibration_validator import CalibrationValidator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def macro_svc():
    return MacroDataService()


@pytest.fixture(scope="module")
def latest_quarter_key():
    return max(APRA_QUARTERLY_BENCHMARKS.keys())


@pytest.fixture(scope="module")
def apra_data(latest_quarter_key):
    return APRA_QUARTERLY_BENCHMARKS[latest_quarter_key]


@pytest.fixture
def validator(apra_data):
    return CalibrationValidator(apra_benchmarks=apra_data)


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


# ===========================================================================
# CalibrationValidator Tests
# ===========================================================================


class TestValidatePredictionCalibration:
    def test_well_calibrated_system(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.0105,
            system_arrears_90_rate=0.0048,
            predicted_default_rate=0.0100,
            total_applications=1000,
        )
        assert result["internal_calibration"]["status"] == "well_calibrated"

    def test_optimistic_system_detected(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.05,
            system_arrears_90_rate=0.004,
            predicted_default_rate=0.005,
            total_applications=1000,
        )
        assert result["internal_calibration"]["status"] == "optimistic"

    def test_pessimistic_system_detected(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.005,
            system_arrears_90_rate=0.004,
            predicted_default_rate=0.05,
            total_applications=1000,
        )
        assert result["internal_calibration"]["status"] == "pessimistic"

    def test_above_apra_benchmark(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.10,
            system_arrears_90_rate=0.05,
            predicted_default_rate=0.10,
            total_applications=1000,
        )
        assert result["external_calibration"]["status"] == "above_benchmark"

    def test_below_apra_benchmark(self, validator):
        # arrears_90 must be more than 0.005 below APRA's ~0.0047 → use 0.0
        validator.validate_prediction_calibration(
            system_default_rate=0.0,
            system_arrears_90_rate=0.0,
            predicted_default_rate=0.0,
            total_applications=1000,
        )
        # Gap = 0.0 - 0.0047 = -0.0047 which is within 0.005 tolerance
        # So we need no arrears at all AND the acceptable_variance to be tighter
        result2 = validator.validate_prediction_calibration(
            system_default_rate=0.0,
            system_arrears_90_rate=0.0,
            predicted_default_rate=0.0,
            total_applications=1000,
            acceptable_variance=0.001,  # Tighter threshold catches the gap
        )
        assert result2["external_calibration"]["status"] == "below_benchmark"


class TestValidateByState:
    def test_matching_rates_all_aligned(self, validator, apra_data):
        state_outcomes = {state: {"default_rate": rate, "count": 100} for state, rate in apra_data["by_state"].items()}
        result = validator.validate_by_state(state_outcomes)
        for state, detail in result.items():
            assert detail["status"] == "aligned", f"{state} should be aligned"

    def test_divergent_rates_flags_states(self, validator, apra_data):
        state_outcomes = {state: {"default_rate": rate, "count": 100} for state, rate in apra_data["by_state"].items()}
        divergent = list(state_outcomes.keys())[0]
        state_outcomes[divergent] = {"default_rate": 0.50, "count": 100}
        result = validator.validate_by_state(state_outcomes)
        assert result[divergent]["status"] != "aligned"


class TestValidatePortfolioComposition:
    def test_within_apra_norms(self, validator, apra_data):
        result = validator.validate_portfolio_composition(
            lvr_80_plus_pct=apra_data["lvr_80_plus_pct"],
            dti_6_plus_pct=apra_data["dti_6_plus_pct"],
        )
        assert result["lvr_80_plus"]["status"] == "aligned"
        assert result["dti_6_plus"]["status"] == "aligned"

    def test_high_lvr_flags_deviation(self, validator, apra_data):
        result = validator.validate_portfolio_composition(
            lvr_80_plus_pct=0.90,
            dti_6_plus_pct=apra_data["dti_6_plus_pct"],
        )
        assert result["lvr_80_plus"]["status"] != "aligned"


class TestGenerateCalibrationReport:
    def _make_report(self, validator, apra_data):
        state_outcomes = {state: {"default_rate": rate, "count": 100} for state, rate in apra_data["by_state"].items()}
        return validator.generate_calibration_report(
            system_default_rate=0.012,
            system_arrears_90_rate=0.005,
            predicted_default_rate=0.011,
            total_applications=5000,
            state_outcomes=state_outcomes,
            lvr_80_plus_pct=0.25,
            dti_6_plus_pct=0.15,
        )

    def test_report_has_prediction_calibration(self, validator, apra_data):
        report = self._make_report(validator, apra_data)
        assert "prediction_calibration" in report

    def test_report_has_state_and_portfolio(self, validator, apra_data):
        report = self._make_report(validator, apra_data)
        assert "state_calibration" in report
        assert "portfolio_composition" in report

    def test_report_has_timestamp(self, validator, apra_data):
        report = self._make_report(validator, apra_data)
        ts = report.get("generated_at") or report.get("validated_at")
        assert ts is not None
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert isinstance(parsed, datetime)

    def test_report_has_apra_metadata(self, validator, apra_data):
        report = self._make_report(validator, apra_data)
        assert "apra_quarter" in report
        assert "apra_published_date" in report


class TestRecommendations:
    def test_recommendations_nonempty_when_failing(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.15,
            system_arrears_90_rate=0.08,
            predicted_default_rate=0.01,
            total_applications=1000,
        )
        assert len(result["recommendations"]) > 0

    def test_recommendations_include_pass_msg_when_calibrated(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.005,
            system_arrears_90_rate=0.0047,
            predicted_default_rate=0.005,
            total_applications=5000,
        )
        # When passing, should have a "no action required" type message
        assert any("acceptable" in r.lower() or "no action" in r.lower() for r in result["recommendations"])


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestEdgeCases:
    def test_zero_applications(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.01,
            system_arrears_90_rate=0.004,
            predicted_default_rate=0.01,
            total_applications=0,
        )
        assert result is not None
        assert "internal_calibration" in result

    def test_100_percent_default(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=1.0,
            system_arrears_90_rate=1.0,
            predicted_default_rate=1.0,
            total_applications=100,
        )
        assert result["external_calibration"]["status"] == "above_benchmark"

    def test_zero_default_rate(self, validator):
        result = validator.validate_prediction_calibration(
            system_default_rate=0.0,
            system_arrears_90_rate=0.0,
            predicted_default_rate=0.0,
            total_applications=500,
            acceptable_variance=0.001,  # Tighter threshold to detect gap vs APRA
        )
        assert result["external_calibration"]["status"] == "below_benchmark"

    def test_apra_data_integrity(self):
        for quarter, data in APRA_QUARTERLY_BENCHMARKS.items():
            assert REQUIRED_APRA_KEYS.issubset(set(data.keys())), (
                f"{quarter} missing keys: {REQUIRED_APRA_KEYS - set(data.keys())}"
            )
            assert isinstance(data["by_state"], dict)
            assert len(data["by_state"]) >= 6
            for state, rate in data["by_state"].items():
                assert 0 <= rate <= 1, f"{quarter}/{state}: {rate} outside [0,1]"
