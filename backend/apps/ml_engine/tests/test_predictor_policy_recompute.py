"""Unit tests for _recompute_lvr_driven_policy_vars.

Guards the LVR → LMI premium → effective_loan_amount recomputation used
by the stress-test harness when property_value is mutated. Any change
to the LMI-rate schedule or purpose gating must update these tests.
"""

import pytest

from apps.ml_engine.services.predictor import _recompute_lvr_driven_policy_vars


class TestRecomputeLvrDrivenPolicyVars:
    def test_home_loan_lvr_below_80_no_lmi(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 700_000.0,  # LVR 0.70
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == 0.0
        assert row["effective_loan_amount"] == 700_000.0

    def test_home_loan_lvr_80_to_85_one_percent(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 820_000.0,  # LVR 0.82
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == pytest.approx(8_200.0)
        assert row["effective_loan_amount"] == pytest.approx(828_200.0)

    def test_home_loan_lvr_85_to_90_two_percent(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 870_000.0,  # LVR 0.87
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == pytest.approx(17_400.0)
        assert row["effective_loan_amount"] == pytest.approx(887_400.0)

    def test_home_loan_lvr_above_90_three_percent(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 950_000.0,  # LVR 0.95
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == pytest.approx(28_500.0)
        assert row["effective_loan_amount"] == pytest.approx(978_500.0)

    def test_investment_loan_treated_same_as_home_loan(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 900_000.0,  # LVR 0.90 → boundary, still 2% (not >0.90)
            "purpose": "investment",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == pytest.approx(18_000.0)
        assert row["effective_loan_amount"] == pytest.approx(918_000.0)

    def test_personal_loan_never_charged_lmi(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 950_000.0,  # High LVR would be 3% if home
            "purpose": "personal",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == 0.0
        assert row["effective_loan_amount"] == 950_000.0

    def test_zero_property_value_no_lmi_no_div_error(self):
        row = {
            "property_value": 0.0,
            "loan_amount": 500_000.0,
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == 0.0
        assert row["effective_loan_amount"] == 500_000.0

    def test_missing_property_value_defaults_to_zero(self):
        row = {
            "loan_amount": 500_000.0,
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == 0.0
        assert row["effective_loan_amount"] == 500_000.0

    def test_none_values_coerced_to_zero(self):
        row = {
            "property_value": None,
            "loan_amount": None,
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == 0.0
        assert row["effective_loan_amount"] == 0.0

    def test_large_loan_within_feature_bound(self):
        row = {
            "property_value": 5_000_000.0,
            "loan_amount": 4_800_000.0,  # LVR 0.96 → 3%
            "purpose": "home",
        }
        _recompute_lvr_driven_policy_vars(row)
        assert row["lmi_premium"] == pytest.approx(144_000.0)
        assert row["effective_loan_amount"] == pytest.approx(4_944_000.0)
        # Must remain under effective_loan_amount upper bound (5_200_000).
        assert row["effective_loan_amount"] < 5_200_000

    def test_mutation_in_place(self):
        row = {
            "property_value": 1_000_000.0,
            "loan_amount": 900_000.0,
            "purpose": "home",
        }
        returned = _recompute_lvr_driven_policy_vars(row)
        assert returned is None, "function mutates in-place, should return None"
        assert "lmi_premium" in row
        assert "effective_loan_amount" in row
