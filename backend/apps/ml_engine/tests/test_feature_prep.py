"""Unit tests for feature-prep helpers extracted from predictor.py.

Covers the free-function forms of safe_get_state and validate_input, which
were previously `@staticmethod` / instance-method on `ModelPredictor` but
are now reusable helpers.
"""

from __future__ import annotations

import math

import pytest

from apps.ml_engine.services.feature_prep import (
    ApplicationValidationError,
    safe_get_state,
    validate_input,
)


# ---------------------------------------------------------------------------
# safe_get_state
# ---------------------------------------------------------------------------


def test_safe_get_state_returns_provided_state():
    class _App:
        state = "VIC"

    assert safe_get_state(_App()) == "VIC"


def test_safe_get_state_falls_back_to_nsw_when_missing():
    class _App:
        pass

    assert safe_get_state(_App()) == "NSW"


def test_safe_get_state_falls_back_to_nsw_when_none():
    class _App:
        state = None

    assert safe_get_state(_App()) == "NSW"


def test_safe_get_state_survives_attribute_access_error():
    class _App:
        @property
        def state(self):
            raise RuntimeError("unmigrated db column")

    assert safe_get_state(_App()) == "NSW"


# ---------------------------------------------------------------------------
# validate_input
# ---------------------------------------------------------------------------


HARD = {
    "annual_income": (0, 10_000_000),
    "credit_score": (0, 1200),
    "loan_amount": (0, 5_000_000),
}


def test_validate_input_accepts_in_range_values():
    validate_input({"annual_income": 80_000, "credit_score": 700, "loan_amount": 50_000}, HARD)


def test_validate_input_rejects_negative_income():
    with pytest.raises(ApplicationValidationError, match="annual_income"):
        validate_input({"annual_income": -1000}, HARD)


def test_validate_input_rejects_credit_score_out_of_range():
    with pytest.raises(ApplicationValidationError, match="credit_score"):
        validate_input({"credit_score": 2000}, HARD)


def test_validate_input_rejects_nan():
    with pytest.raises(ApplicationValidationError, match="nan/inf"):
        validate_input({"annual_income": math.nan}, HARD)


def test_validate_input_rejects_non_numeric_string():
    with pytest.raises(ApplicationValidationError, match="cannot convert"):
        validate_input({"annual_income": "not a number"}, HARD)


def test_validate_input_skips_missing_values():
    # Absent keys are legitimate — only provided values are checked.
    validate_input({}, HARD)


def test_validate_input_user_bounds_can_only_widen():
    # data-driven user bounds must relax hard bounds, never narrow them.
    user = {"credit_score": (100, 900)}  # narrower than 0-1200
    # credit_score 1100 is in hard (0-1200) but outside user — must still pass
    validate_input({"credit_score": 1100}, HARD, user_bounds=user)


def test_validate_input_user_bounds_widen_below_hard_lo():
    # user_bounds can legitimately extend the range further
    user = {"credit_score": (-50, 1500)}  # wider than 0-1200
    validate_input({"credit_score": 1400}, HARD, user_bounds=user)


def test_validate_input_multiple_errors_reported_together():
    with pytest.raises(ApplicationValidationError) as exc_info:
        validate_input({"annual_income": -1, "credit_score": 5000}, HARD)
    msg = str(exc_info.value)
    assert "annual_income" in msg
    assert "credit_score" in msg
