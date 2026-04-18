"""Unit tests for the hard credit policy overlay (D3).

Each rule has at least one positive (rule fires) and one negative (rule
silent) test. `evaluate` is exercised against dict inputs so tests are
independent of the Django ORM; a separate test covers attribute-style
access for LoanApplication-style objects.

`apply_overlay_to_decision` is tested as a decision matrix: every combo of
(decision, result-state, mode) so behaviour under shadow vs enforce is
provable rather than inferred from reading the code.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.ml_engine.services import credit_policy as cp

# ---------------------------------------------------------------------------
# Hard-fail rule coverage (P01-P07)
# ---------------------------------------------------------------------------


def test_p01_visa_ineligible_hits_on_bridging_visa():
    app = {"visa_status": "bridging"}
    result = cp.evaluate(app)
    assert "P01" in result.hard_fails


def test_p01_visa_eligible_permanent_resident_passes():
    app = {"visa_status": "permanent_resident"}
    result = cp.evaluate(app)
    assert "P01" not in result.hard_fails


def test_p01_missing_visa_field_is_not_evaluable():
    app = {}  # No visa field at all — skip, don't fail
    result = cp.evaluate(app)
    assert "P01" not in result.hard_fails


def test_p02_age_under_18_is_hard_fail():
    app = {"date_of_birth": date.today() - timedelta(days=16 * 365)}
    result = cp.evaluate(app)
    assert "P02" in result.hard_fails


def test_p02_age_at_maturity_over_75_is_hard_fail():
    # 70-year-old taking a 10-year loan → matures at 80
    app = {
        "date_of_birth": date.today() - timedelta(days=int(70 * 365.25)),
        "loan_term_months": 120,
    }
    result = cp.evaluate(app)
    assert "P02" in result.hard_fails


def test_p02_mid_working_age_passes():
    app = {
        "date_of_birth": date.today() - timedelta(days=int(35 * 365.25)),
        "loan_term_months": 360,  # matures at 65
    }
    result = cp.evaluate(app)
    assert "P02" not in result.hard_fails


def test_p03_bankruptcy_flag_is_hard_fail():
    assert "P03" in cp.evaluate({"has_bankruptcy": True}).hard_fails


def test_p03_no_bankruptcy_passes():
    assert "P03" not in cp.evaluate({"has_bankruptcy": False}).hard_fails


def test_p04_active_ato_debt_is_hard_fail():
    assert "P04" in cp.evaluate({"has_ato_debt_default": True}).hard_fails


def test_p04_ato_field_absent_is_not_evaluable():
    # ATO default feed not yet wired — absence must skip, not default-deny
    assert "P04" not in cp.evaluate({}).hard_fails


def test_p05_credit_score_below_floor_is_hard_fail():
    assert "P05" in cp.evaluate({"credit_score": 400}).hard_fails


def test_p05_credit_score_at_floor_passes():
    # Boundary: exactly MIN_CREDIT_SCORE passes (strict "<")
    assert "P05" not in cp.evaluate({"credit_score": cp.MIN_CREDIT_SCORE}).hard_fails


def test_p05_credit_score_missing_is_not_evaluable():
    # Score unavailable — skip, don't default-deny
    assert "P05" not in cp.evaluate({}).hard_fails


def test_p06_lvr_at_100pct_is_hard_fail_home():
    app = {
        "property_value": 500_000,
        "loan_amount": 500_000,
        "purpose": "home",
    }
    assert "P06" in cp.evaluate(app).hard_fails


def test_p06_lvr_above_95pct_home_is_hard_fail():
    app = {
        "property_value": 500_000,
        "loan_amount": 480_000,  # 96% LVR
        "purpose": "home",
    }
    assert "P06" in cp.evaluate(app).hard_fails


def test_p06_lvr_at_exact_95pct_home_passes():
    # 0.95 is <= ceiling, not >; boundary case should pass
    app = {
        "property_value": 500_000,
        "loan_amount": 475_000,  # 95% LVR exactly
        "purpose": "home",
    }
    assert "P06" not in cp.evaluate(app).hard_fails


def test_p06_no_property_value_skips_rule():
    # Personal loan / no security → rule does not apply
    app = {"property_value": 0, "loan_amount": 50_000, "purpose": "personal"}
    assert "P06" not in cp.evaluate(app).hard_fails


def test_p07_dti_above_apra_ceiling_is_hard_fail():
    assert "P07" in cp.evaluate({"debt_to_income": 9.0}).hard_fails


def test_p07_dti_at_apra_ceiling_passes():
    # MAX_DTI is strictly greater-than; exact ceiling is not a hit
    assert "P07" not in cp.evaluate({"debt_to_income": cp.MAX_DTI}).hard_fails


# ---------------------------------------------------------------------------
# Refer rule coverage (P08-P12)
# ---------------------------------------------------------------------------


def test_p08_lti_above_9x_is_refer():
    app = {"annual_income": 80_000, "loan_amount": 800_000}  # 10x LTI
    result = cp.evaluate(app)
    assert "P08" in result.refers
    assert result.has_refer
    assert not result.has_hard_fail


def test_p08_normal_lti_passes():
    app = {"annual_income": 100_000, "loan_amount": 500_000}  # 5x LTI
    assert "P08" not in cp.evaluate(app).refers


def test_p08_zero_income_does_not_divide_by_zero():
    app = {"annual_income": 0, "loan_amount": 100_000}
    result = cp.evaluate(app)
    # P08 can't evaluate w/o income; does not raise, just skips
    assert "P08" not in result.refers


def test_p09_high_postcode_default_rate_is_refer():
    assert "P09" in cp.evaluate({"postcode_default_rate": 0.12}).refers


def test_p09_normal_postcode_passes():
    assert "P09" not in cp.evaluate({"postcode_default_rate": 0.02}).refers


def test_p10_self_employed_under_24mo_is_refer():
    app = {"employment_type": "self_employed", "employment_length": 1.0}  # 12 months
    assert "P10" in cp.evaluate(app).refers


def test_p10_self_employed_over_24mo_passes():
    app = {"employment_type": "self_employed", "employment_length": 3.0}
    assert "P10" not in cp.evaluate(app).refers


def test_p10_full_time_employee_is_not_evaluated():
    app = {"employment_type": "full_time", "employment_length": 0.5}
    assert "P10" not in cp.evaluate(app).refers


def test_p11_any_hardship_flag_triggers_refer():
    assert "P11" in cp.evaluate({"num_hardship_flags": 1}).refers


def test_p11_no_hardship_flags_passes():
    assert "P11" not in cp.evaluate({"num_hardship_flags": 0}).refers


def test_p12_personal_loan_over_50k_is_refer():
    assert "P12" in cp.evaluate({"purpose": "personal", "loan_amount": 60_000}).refers


def test_p12_personal_loan_at_cap_passes():
    # Boundary: 50k is not > 50k
    assert "P12" not in cp.evaluate({"purpose": "personal", "loan_amount": 50_000}).refers


def test_p12_home_loan_over_50k_not_refer():
    assert "P12" not in cp.evaluate({"purpose": "home", "loan_amount": 500_000}).refers


# ---------------------------------------------------------------------------
# PolicyResult behaviour
# ---------------------------------------------------------------------------


def test_empty_result_is_passed():
    r = cp.PolicyResult()
    assert r.passed
    assert not r.has_hard_fail
    assert not r.has_refer


def test_result_with_only_refers_is_not_passed_but_is_not_hard_fail():
    r = cp.PolicyResult(refers=["P08"])
    assert not r.passed
    assert not r.has_hard_fail
    assert r.has_refer


def test_result_to_dict_round_trip():
    r = cp.PolicyResult(
        hard_fails=["P05"],
        refers=["P08"],
        rationale=["P05 (hard-fail): score below floor"],
        evaluated_rules=["_p05_credit_score_floor"],
    )
    d = r.to_dict()
    assert d["passed"] is False
    assert d["hard_fails"] == ["P05"]
    assert d["refers"] == ["P08"]
    assert d["rationale"] == ["P05 (hard-fail): score below floor"]
    # to_dict returns copies — mutations should not leak back into result
    d["hard_fails"].append("P99")
    assert r.hard_fails == ["P05"]


def test_evaluate_always_records_all_rules_even_on_clean_input():
    result = cp.evaluate({"credit_score": 800, "debt_to_income": 3.0})
    expected_rule_count = len(cp._HARD_FAIL_RULES) + len(cp._REFER_RULES)
    assert len(result.evaluated_rules) == expected_rule_count


def test_evaluate_accepts_attribute_style_application():
    """LoanApplication instances don't support .get() — overlay must handle
    both dict and attribute-style access without a type sniff on the caller.
    """

    class _App:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    app = _App(has_bankruptcy=True, credit_score=700, debt_to_income=3.0)
    result = cp.evaluate(app)
    assert "P03" in result.hard_fails


def test_evaluate_collects_multiple_simultaneous_hits():
    app = {
        "has_bankruptcy": True,       # P03 hard-fail
        "credit_score": 300,          # P05 hard-fail
        "num_hardship_flags": 2,      # P11 refer
    }
    result = cp.evaluate(app)
    assert set(result.hard_fails) >= {"P03", "P05"}
    assert "P11" in result.refers


# ---------------------------------------------------------------------------
# apply_overlay_to_decision — mode matrix
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_result():
    return cp.PolicyResult()


@pytest.fixture
def hardfail_result():
    return cp.PolicyResult(hard_fails=["P05"], rationale=["P05 (hard-fail): score"])


@pytest.fixture
def refer_result():
    return cp.PolicyResult(refers=["P08"], rationale=["P08 (refer): high LTI"])


def test_overlay_off_passes_decision_through_even_on_hardfail(hardfail_result):
    assert cp.apply_overlay_to_decision("approved", hardfail_result, cp.OVERLAY_MODE_OFF) == "approved"


def test_overlay_shadow_passes_decision_through(hardfail_result):
    # Shadow mode NEVER changes the decision — it only observes and logs.
    assert cp.apply_overlay_to_decision("approved", hardfail_result, cp.OVERLAY_MODE_SHADOW) == "approved"


def test_overlay_enforce_flips_approved_to_denied_on_hardfail(hardfail_result):
    assert cp.apply_overlay_to_decision("approved", hardfail_result, cp.OVERLAY_MODE_ENFORCE) == "denied"


def test_overlay_enforce_flips_denied_to_denied_on_hardfail(hardfail_result):
    # A denied-by-model + hard-fail stays denied under enforce.
    assert cp.apply_overlay_to_decision("denied", hardfail_result, cp.OVERLAY_MODE_ENFORCE) == "denied"


def test_overlay_enforce_flips_approved_to_review_on_refer(refer_result):
    assert cp.apply_overlay_to_decision("approved", refer_result, cp.OVERLAY_MODE_ENFORCE) == "review"


def test_overlay_enforce_does_not_flip_denied_to_review_on_refer(refer_result):
    # Refer only intercepts the approve path; a denied application stays denied.
    assert cp.apply_overlay_to_decision("denied", refer_result, cp.OVERLAY_MODE_ENFORCE) == "denied"


def test_overlay_enforce_passes_clean_decision_through(clean_result):
    assert cp.apply_overlay_to_decision("approved", clean_result, cp.OVERLAY_MODE_ENFORCE) == "approved"
    assert cp.apply_overlay_to_decision("denied", clean_result, cp.OVERLAY_MODE_ENFORCE) == "denied"


def test_overlay_enforce_prefers_hard_fail_over_refer():
    both = cp.PolicyResult(hard_fails=["P05"], refers=["P08"])
    # Hard-fail trumps refer → deny rather than review.
    assert cp.apply_overlay_to_decision("approved", both, cp.OVERLAY_MODE_ENFORCE) == "denied"


# ---------------------------------------------------------------------------
# current_mode — env/settings fallback
# ---------------------------------------------------------------------------


def test_current_mode_defaults_to_shadow_on_unknown_value(monkeypatch):
    # Clear any Django setting first so env var is what's read
    monkeypatch.setenv(cp.OVERLAY_MODE_ENV, "banana")
    from django.conf import settings as _settings
    monkeypatch.setattr(_settings, "CREDIT_POLICY_OVERLAY_MODE", "banana", raising=False)
    assert cp.current_mode() == cp.OVERLAY_MODE_SHADOW


def test_current_mode_reads_settings_first(monkeypatch):
    from django.conf import settings as _settings
    monkeypatch.setattr(_settings, "CREDIT_POLICY_OVERLAY_MODE", "off", raising=False)
    # Env says enforce, settings says off — settings wins
    monkeypatch.setenv(cp.OVERLAY_MODE_ENV, "enforce")
    assert cp.current_mode() == cp.OVERLAY_MODE_OFF


def test_current_mode_falls_back_to_env_when_settings_absent(monkeypatch):
    from django.conf import settings as _settings
    monkeypatch.setattr(_settings, "CREDIT_POLICY_OVERLAY_MODE", None, raising=False)
    monkeypatch.setenv(cp.OVERLAY_MODE_ENV, "enforce")
    assert cp.current_mode() == cp.OVERLAY_MODE_ENFORCE


def test_current_mode_defaults_to_shadow_when_nothing_is_set(monkeypatch):
    from django.conf import settings as _settings
    monkeypatch.setattr(_settings, "CREDIT_POLICY_OVERLAY_MODE", None, raising=False)
    monkeypatch.delenv(cp.OVERLAY_MODE_ENV, raising=False)
    assert cp.current_mode() == cp.OVERLAY_MODE_SHADOW
