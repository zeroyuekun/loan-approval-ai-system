"""Unit tests for the LVR-driven policy recompute helper.

Verifies that LMI premium + effective_loan_amount are recomputed consistently
from loan_amount / property_value / purpose after any upstream mutation
(stress test, counterfactual, etc.).
"""

from __future__ import annotations

from apps.ml_engine.services.policy_recompute import recompute_lvr_driven_policy_vars


def test_low_lvr_charges_no_lmi():
    row = {"loan_amount": 400_000, "property_value": 600_000, "purpose": "home"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == 0.0
    assert row["effective_loan_amount"] == 400_000.0


def test_lvr_above_90_charges_3_percent():
    row = {"loan_amount": 475_000, "property_value": 500_000, "purpose": "home"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == round(475_000 * 0.03, 2)
    assert row["effective_loan_amount"] == round(475_000 + 475_000 * 0.03, 2)


def test_lvr_85_to_90_charges_2_percent():
    row = {"loan_amount": 435_000, "property_value": 500_000, "purpose": "home"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == round(435_000 * 0.02, 2)


def test_lvr_80_to_85_charges_1_percent():
    row = {"loan_amount": 410_000, "property_value": 500_000, "purpose": "home"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == round(410_000 * 0.01, 2)


def test_personal_loan_never_charges_lmi():
    row = {"loan_amount": 50_000, "property_value": 0, "purpose": "personal"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == 0.0
    assert row["effective_loan_amount"] == 50_000.0


def test_investment_loan_at_high_lvr_is_charged_lmi():
    row = {"loan_amount": 475_000, "property_value": 500_000, "purpose": "investment"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == round(475_000 * 0.03, 2)


def test_missing_property_value_gracefully_returns_zero_lmi():
    row = {"loan_amount": 100_000, "property_value": 0, "purpose": "home"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == 0.0
    assert row["effective_loan_amount"] == 100_000.0


def test_none_property_value_treated_as_zero():
    row = {"loan_amount": 100_000, "property_value": None, "purpose": "home"}
    recompute_lvr_driven_policy_vars(row)
    assert row["lmi_premium"] == 0.0


def test_returns_none_contract_for_in_place_mutation():
    row = {"loan_amount": 50_000, "property_value": 0, "purpose": "personal"}
    assert recompute_lvr_driven_policy_vars(row) is None
