"""Unit tests for monotone_constraints.py — the XGBoost sign schedule.

These tests are cheap sanity gates, not statistical ones: they guard against
accidental drift between the constraint dict and its rationale, verify the
XGBoost tuple is emitted in the right order, and make sure we haven't
accidentally flipped the sign of a known driver.

The expensive downstream test — fitting a tiny XGBoost and verifying that
marginal predictions respect the constraint — lives in the trainer
regression suite.
"""

import pytest

from apps.ml_engine.services.monotone_constraints import (
    MONOTONE_CONSTRAINTS,
    NEGATIVE,
    POSITIVE,
    RATIONALE,
    UNCONSTRAINED,
    assert_rationale_coverage,
    build_xgboost_monotone_spec,
    constrained_feature_names,
)


class TestMonotoneConstraintRegistry:
    def test_every_constraint_has_rationale(self):
        assert_rationale_coverage()  # raises on mismatch

    def test_rationale_has_no_orphans(self):
        assert set(RATIONALE.keys()) == set(MONOTONE_CONSTRAINTS.keys())

    def test_signs_are_valid(self):
        for feat, sign in MONOTONE_CONSTRAINTS.items():
            assert sign in (POSITIVE, NEGATIVE, UNCONSTRAINED), (
                f"{feat} has invalid sign {sign}"
            )

    def test_positive_and_negative_are_disjoint(self):
        pos = {f for f, s in MONOTONE_CONSTRAINTS.items() if s == POSITIVE}
        neg = {f for f, s in MONOTONE_CONSTRAINTS.items() if s == NEGATIVE}
        assert pos.isdisjoint(neg)

    def test_minimum_constraint_count(self):
        # Plan targets ~55 signed features; we require ≥50 so drift alerts
        # rather than accepts silent shrinkage.
        signed = [s for s in MONOTONE_CONSTRAINTS.values() if s != UNCONSTRAINED]
        assert len(signed) >= 50, f"expected >=50 signed features, got {len(signed)}"


class TestKnownDriverSigns:
    """Pin the signs of the most regulator-visible drivers."""

    @pytest.mark.parametrize(
        "feature",
        [
            "credit_score",
            "annual_income",
            "savings_balance",
            "employment_length",
            "deposit_amount",
            "hem_surplus",
        ],
    )
    def test_core_positive_drivers(self, feature):
        assert MONOTONE_CONSTRAINTS[feature] == POSITIVE

    @pytest.mark.parametrize(
        "feature",
        [
            "debt_to_income",
            "num_defaults_5yr",
            "loan_amount",
            "lvr",
            "has_bankruptcy",
            "num_hardship_flags",
            "gambling_transaction_flag",
            "num_credit_enquiries_6m",
        ],
    )
    def test_core_negative_drivers(self, feature):
        assert MONOTONE_CONSTRAINTS[feature] == NEGATIVE

    def test_log_transforms_match_source_sign(self):
        assert MONOTONE_CONSTRAINTS["log_annual_income"] == MONOTONE_CONSTRAINTS["annual_income"]
        assert MONOTONE_CONSTRAINTS["log_loan_amount"] == MONOTONE_CONSTRAINTS["loan_amount"]


class TestBuildXgboostMonotoneSpec:
    def test_preserves_column_order(self):
        cols = ["credit_score", "debt_to_income", "loan_term_months", "annual_income"]
        spec = build_xgboost_monotone_spec(cols)
        assert spec == (POSITIVE, NEGATIVE, UNCONSTRAINED, POSITIVE)

    def test_unknown_columns_unconstrained(self):
        cols = ["purpose_home", "state_NSW", "industry_anzsic_F", "some_new_feature"]
        spec = build_xgboost_monotone_spec(cols)
        assert spec == (UNCONSTRAINED, UNCONSTRAINED, UNCONSTRAINED, UNCONSTRAINED)

    def test_empty_input_returns_empty_tuple(self):
        assert build_xgboost_monotone_spec([]) == ()

    def test_returns_tuple_not_list(self):
        # XGBoost handles both but tuple signals immutability; older xgb
        # versions have been known to mishandle lists in edge cases.
        assert isinstance(build_xgboost_monotone_spec(["credit_score"]), tuple)

    def test_mixed_known_and_unknown(self):
        cols = ["credit_score", "purpose_investment", "debt_to_income"]
        spec = build_xgboost_monotone_spec(cols)
        assert spec == (POSITIVE, UNCONSTRAINED, NEGATIVE)


class TestConstrainedFeatureNames:
    def test_sorted_and_unique(self):
        names = constrained_feature_names()
        assert names == sorted(names)
        assert len(names) == len(set(names))

    def test_contains_known_drivers(self):
        names = constrained_feature_names()
        for expected in ("credit_score", "debt_to_income", "lvr"):
            assert expected in names
