"""Tests for PropertyDataService — SA3-level property price data."""

import numpy as np
import pytest

from apps.ml_engine.services.property_data_service import PropertyDataService


@pytest.fixture(scope="module")
def service():
    return PropertyDataService()


@pytest.fixture(scope="module")
def rng():
    return np.random.default_rng(42)


class TestPropertyDataService:
    """Tests for SA3 region data and assignment."""

    def test_all_states_have_sa3_regions(self, service):
        """Every Australian state/territory must have at least one SA3 region."""
        for state in ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]:
            regions = service.get_state_sa3s(state)
            assert len(regions) > 0, f"No SA3 regions for {state}"

    def test_population_weights_sum_to_one(self, service):
        """Population weights within each state must sum to ~1.0."""
        for state in ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]:
            regions = service.get_state_sa3s(state)
            total = sum(r["population_weight"] for r in regions)
            assert abs(total - 1.0) < 0.02, f"{state} population weights sum to {total:.3f}, expected ~1.0"

    def test_assign_sa3_returns_valid_tuple(self, service, rng):
        """assign_sa3 returns (code, name, property_mult, rental_mult)."""
        code, name, p_mult, r_mult = service.assign_sa3("NSW", rng)
        assert isinstance(code, str)
        assert len(code) == 5
        assert isinstance(name, str)
        assert len(name) > 0
        assert isinstance(p_mult, float)
        assert isinstance(r_mult, float)
        assert p_mult > 0
        assert r_mult > 0

    def test_assign_sa3_distribution_varies(self, service):
        """Over many samples, different SA3 regions should be assigned."""
        rng = np.random.default_rng(123)
        codes = set()
        for _ in range(500):
            code, _, _, _ = service.assign_sa3("NSW", rng)
            codes.add(code)
        # NSW has ~10 SA3 regions, expect at least 5 different ones
        assert len(codes) >= 5, f"Only {len(codes)} unique SA3 codes assigned for NSW"

    def test_assign_sa3_unknown_state_returns_fallback(self, service, rng):
        """Unknown state should return a sensible fallback."""
        code, name, p_mult, r_mult = service.assign_sa3("XX", rng)
        assert p_mult == 1.0
        assert r_mult == 1.0

    def test_property_multipliers_have_realistic_range(self, service):
        """Property multipliers should range from ~0.4x to ~2.5x."""
        for state in ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]:
            regions = service.get_state_sa3s(state)
            mults = [r["property_mult"] for r in regions]
            assert min(mults) >= 0.3, f"{state} min property_mult too low: {min(mults)}"
            assert max(mults) <= 3.0, f"{state} max property_mult too high: {max(mults)}"

    def test_rental_multipliers_correlated_with_property(self, service):
        """Rental multipliers should roughly correlate with property multipliers."""
        for state in ["NSW", "VIC"]:
            regions = service.get_state_sa3s(state)
            for r in regions:
                # Rental mult should be within 50% of property mult
                ratio = r["rental_mult"] / r["property_mult"]
                assert 0.5 <= ratio <= 1.5, f"{r['name']}: rental/property ratio {ratio:.2f} outside 0.5-1.5"

    def test_get_sa3_data_by_code(self, service):
        """get_sa3_data returns correct data for a known code."""
        # Sydney City (NSW) code from seed data
        data = service.get_sa3_data("11703")
        assert data is not None
        assert data["state"] == "NSW"
        assert data["property_mult"] > 1.0  # Inner city is above median

    def test_get_sa3_data_unknown_code(self, service):
        """get_sa3_data returns None for unknown code."""
        assert service.get_sa3_data("99999") is None

    def test_get_calibration_data_structure(self, service):
        """get_calibration_data returns expected dict structure."""
        data = service.get_calibration_data()
        assert "sa3_regions" in data
        assert "sa4_to_sa3" in data
        assert "generated_at" in data
        assert isinstance(data["sa3_regions"], dict)
        assert isinstance(data["sa4_to_sa3"], dict)
        assert len(data["sa3_regions"]) > 0

    def test_sa4_to_sa3_mapping_exists(self, service):
        """SA4-to-SA3 mapping should cover major regions."""
        data = service.get_calibration_data()
        sa4_map = data["sa4_to_sa3"]
        assert len(sa4_map) > 0
        # Each SA4 should map to at least one SA3
        for sa4_code, sa3_list in sa4_map.items():
            assert len(sa3_list) > 0, f"SA4 {sa4_code} has no SA3 codes"

    def test_apply_growth_modifies_multipliers(self, service):
        """apply_growth should adjust property multipliers."""
        # Snapshot originals for exact restore
        nsw_regions = service.get_state_sa3s("NSW")
        orig_snapshot = {r["code"]: (r["property_mult"], r["rental_mult"]) for r in nsw_regions}

        # Apply 5% growth to Sydney
        service.apply_growth({"Sydney": 0.05})

        # NSW multipliers should have changed
        nsw_regions_after = service.get_state_sa3s("NSW")
        new_mults = {r["code"]: r["property_mult"] for r in nsw_regions_after}

        changed = sum(1 for code in orig_snapshot if abs(new_mults[code] - orig_snapshot[code][0]) > 0.001)
        assert changed > 0, "apply_growth did not change any NSW multipliers"

        # Restore exact originals (not multiplicative inverse which is lossy)
        for r in nsw_regions_after:
            if r["code"] in orig_snapshot:
                r["property_mult"] = orig_snapshot[r["code"]][0]
                r["rental_mult"] = orig_snapshot[r["code"]][1]
