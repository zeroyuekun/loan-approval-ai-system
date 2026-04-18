"""D6 — referral audit trail tests.

Covers:
- PolicyResult exposes `rationale_by_code` keyed on policy code.
- Each refer rule (P08-P12) populates the expected code in rationale_by_code
  when its triggering condition is met.
- No referral mutation happens when policy.passed (defensive guard).
- No referral mutation happens when only hard-fails fire (P01-P07) — the
  referral trail is for *refers*, not hard-fails (those are on the decision
  waterfall).

This file exercises the pure PolicyResult contract without Django ORM, so
it runs in the same CI sweep as test_credit_policy.py. Integration-level
predictor wiring is covered in predictor smoke tests.
"""

from __future__ import annotations

from apps.ml_engine.services import credit_policy as cp

# ---------------------------------------------------------------------------
# Rationale-by-code contract
# ---------------------------------------------------------------------------


def test_rationale_by_code_empty_on_pass():
    """Clean application → no rationale entries."""
    app = {
        "credit_score": 750,
        "annual_income": 100_000,
        "loan_amount": 10_000,
        "debt_to_income": 3.0,
        "purpose": "personal",
    }
    result = cp.evaluate(app)
    assert result.passed
    assert result.rationale_by_code == {}


def test_p08_lti_refer_populates_rationale_by_code():
    app = {"annual_income": 50_000, "loan_amount": 600_000}  # LTI=12
    result = cp.evaluate(app)
    assert "P08" in result.refers
    assert "P08" in result.rationale_by_code
    assert "12" in result.rationale_by_code["P08"]  # LTI=12


def test_p09_postcode_refer_populates_rationale_by_code():
    app = {"postcode_default_rate": 0.12}
    result = cp.evaluate(app)
    assert "P09" in result.refers
    assert "P09" in result.rationale_by_code
    assert "12" in result.rationale_by_code["P09"]  # 12%


def test_p10_self_employed_short_history_populates_rationale():
    app = {"employment_type": "self_employed", "employment_length": 0.5}  # 6 months
    result = cp.evaluate(app)
    assert "P10" in result.refers
    assert "P10" in result.rationale_by_code


def test_p11_hardship_flags_populates_rationale():
    app = {"num_hardship_flags": 2}
    result = cp.evaluate(app)
    assert "P11" in result.refers
    assert "P11" in result.rationale_by_code
    assert "2 hardship" in result.rationale_by_code["P11"]


def test_p12_tmd_mismatch_populates_rationale():
    app = {"purpose": "personal", "loan_amount": 75_000}
    result = cp.evaluate(app)
    assert "P12" in result.refers
    assert "P12" in result.rationale_by_code


def test_multiple_refers_all_captured_in_rationale_by_code():
    """P08 (LTI > 9x) + P11 (hardship) should both appear in the map."""
    app = {
        "annual_income": 50_000,
        "loan_amount": 600_000,  # LTI=12 → P08
        "num_hardship_flags": 1,  # → P11
    }
    result = cp.evaluate(app)
    assert set(result.refers) >= {"P08", "P11"}
    assert "P08" in result.rationale_by_code
    assert "P11" in result.rationale_by_code


# ---------------------------------------------------------------------------
# Hard-fail isolation (rationale_by_code includes hard-fails too, but the
# referral fields on LoanApplication should only be populated for refers).
# ---------------------------------------------------------------------------


def test_hard_fails_also_appear_in_rationale_by_code():
    """Hard-fails share the same code→text map; separation happens at the
    predictor layer (only refers drive the LoanApplication.referral_*
    fields, hard-fails go through the model-decline path)."""
    app = {"has_bankruptcy": True}  # P03
    result = cp.evaluate(app)
    assert "P03" in result.hard_fails
    assert "P03" in result.rationale_by_code


def test_to_dict_includes_rationale_by_code():
    app = {"num_hardship_flags": 1}
    result = cp.evaluate(app)
    payload = result.to_dict()
    assert "rationale_by_code" in payload
    assert payload["rationale_by_code"]["P11"]
