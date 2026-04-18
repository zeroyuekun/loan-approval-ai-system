"""Unit tests for the prediction-time feature-dict builder.

The builder pulls raw columns off a `LoanApplication` (with imputation for
nullable fields), then derives the two underwriter-internal features
(`hem_benchmark`, `hem_gap`) and the LVR-driven LMI policy variables
(`lmi_premium`, `effective_loan_amount`).

Mirrors the training-time feature generator so the served model sees the
same policy variables it learned from.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from apps.ml_engine.services.prediction_features import (
    build_prediction_features,
    derive_underwriter_features,
)


def _mk_app(**overrides):
    defaults = dict(
        annual_income=100_000,
        credit_score=750,
        loan_amount=400_000,
        loan_term_months=360,
        debt_to_income=4.0,
        employment_length=5,
        has_cosigner=False,
        purpose="home",
        home_ownership="own",
        number_of_dependants=0,
        employment_type="full_time",
        applicant_type="individual",
        has_hecs=False,
        has_bankruptcy=False,
        state="NSW",
        is_existing_customer=False,
        gambling_transaction_flag=False,
        property_value=500_000,
        deposit_amount=100_000,
        monthly_expenses=2500,
        existing_credit_card_limit=10_000,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _identity_state(application):
    return getattr(application, "state", "NSW")


# ---------------------------------------------------------------------------
# build_prediction_features
# ---------------------------------------------------------------------------


class TestBuildPredictionFeatures:
    def test_core_fields_mapped(self):
        app = _mk_app()
        feats = build_prediction_features(app, safe_get_state_fn=_identity_state, imputation_values={})
        assert feats["annual_income"] == 100_000.0
        assert feats["credit_score"] == 750
        assert feats["loan_amount"] == 400_000.0
        assert feats["state"] == "NSW"
        assert feats["purpose"] == "home"

    def test_boolean_flags_converted_to_int(self):
        app = _mk_app(has_cosigner=True, has_hecs=True, has_bankruptcy=False)
        feats = build_prediction_features(app, safe_get_state_fn=_identity_state, imputation_values={})
        assert feats["has_cosigner"] == 1
        assert feats["has_hecs"] == 1
        assert feats["has_bankruptcy"] == 0

    def test_imputation_fallback_used_when_attr_none(self):
        # Use a SimpleNamespace missing `property_value` (attr returns None via getattr default)
        app = _mk_app()
        app.property_value = None
        imputation = {"property_value": 450_000.0}
        feats = build_prediction_features(app, safe_get_state_fn=_identity_state, imputation_values=imputation)
        assert feats["property_value"] == 450_000.0

    def test_default_fallback_when_no_imputation(self):
        app = _mk_app()
        app.monthly_expenses = None
        # Default for monthly_expenses is 2500
        feats = build_prediction_features(app, safe_get_state_fn=_identity_state, imputation_values={})
        assert feats["monthly_expenses"] == 2500.0

    def test_categorical_default_applied(self):
        app = _mk_app()
        # savings_trend_3m not set on the SimpleNamespace — should default to "flat"
        feats = build_prediction_features(app, safe_get_state_fn=_identity_state, imputation_values={})
        assert feats["savings_trend_3m"] == "flat"

    def test_safe_get_state_callback_used(self):
        app = _mk_app(state=None)
        feats = build_prediction_features(
            app,
            safe_get_state_fn=lambda _a: "VIC",
            imputation_values={},
        )
        assert feats["state"] == "VIC"


# ---------------------------------------------------------------------------
# derive_underwriter_features
# ---------------------------------------------------------------------------


class TestDeriveUnderwriterFeatures:
    def test_low_lvr_home_loan_has_no_lmi(self):
        features = {
            "annual_income": 100_000.0,
            "loan_amount": 400_000.0,
            "property_value": 600_000.0,  # LVR 0.67
            "monthly_expenses": 2500.0,
            "applicant_type": "individual",
            "number_of_dependants": 0,
            "purpose": "home",
            "state": "NSW",
        }
        derive_underwriter_features(features)
        assert features["lmi_premium"] == 0.0
        assert features["effective_loan_amount"] == 400_000.0

    def test_high_lvr_home_loan_charges_3_percent_lmi(self):
        features = {
            "annual_income": 100_000.0,
            "loan_amount": 475_000.0,
            "property_value": 500_000.0,  # LVR 0.95
            "monthly_expenses": 2500.0,
            "applicant_type": "individual",
            "number_of_dependants": 0,
            "purpose": "home",
            "state": "NSW",
        }
        derive_underwriter_features(features)
        assert features["lmi_premium"] == round(475_000 * 0.03, 2)
        assert features["effective_loan_amount"] == round(475_000 + features["lmi_premium"], 2)

    def test_personal_loan_never_charges_lmi(self):
        features = {
            "annual_income": 100_000.0,
            "loan_amount": 50_000.0,
            "property_value": 0.0,
            "monthly_expenses": 2500.0,
            "applicant_type": "individual",
            "number_of_dependants": 0,
            "purpose": "personal",
            "state": "NSW",
        }
        derive_underwriter_features(features)
        assert features["lmi_premium"] == 0.0
        assert features["effective_loan_amount"] == 50_000.0

    def test_hem_gap_is_signed(self):
        features = {
            "annual_income": 100_000.0,
            "loan_amount": 400_000.0,
            "property_value": 600_000.0,
            "monthly_expenses": 5000.0,  # above HEM benchmark
            "applicant_type": "individual",
            "number_of_dependants": 0,
            "purpose": "home",
            "state": "NSW",
        }
        derive_underwriter_features(features)
        # hem_gap = monthly_expenses - hem_benchmark — should be positive
        assert features["hem_gap"] > 0
        assert features["hem_benchmark"] > 0

    def test_hem_lookup_failure_uses_fallback(self):
        features = {
            "annual_income": 100_000.0,
            "loan_amount": 400_000.0,
            "property_value": 600_000.0,
            "monthly_expenses": 2500.0,
            "applicant_type": "individual",
            "number_of_dependants": 0,
            "purpose": "home",
            "state": "NSW",
        }
        with patch(
            "apps.ml_engine.services.prediction_features.UnderwritingEngine",
            side_effect=RuntimeError("boom"),
        ):
            derive_underwriter_features(features)
        # Falls back to 2950.0
        assert features["hem_benchmark"] == 2950.0
