"""Unit tests for template_fallback helper functions.

These cover the deterministic helpers used when the LLM email path is disabled.
No DB, no Celery, no settings — pure functions.
"""

import pytest

from apps.email_engine.services.template_fallback import _loan_type


class TestLoanTypeMapping:
    """Known purposes map to canonical labels."""

    def test_home(self):
        assert _loan_type("home") == "Home Purchase"

    def test_home_improvement(self):
        assert _loan_type("home_improvement") == "Home Improvement"

    def test_auto(self):
        assert _loan_type("auto") == "Vehicle"

    def test_personal(self):
        assert _loan_type("personal") == "Personal"

    def test_business(self):
        assert _loan_type("business") == "Business"

    def test_education(self):
        assert _loan_type("education") == "Education"


class TestLoanTypeCaseInsensitivity:
    """Mapping lookups must be case-insensitive."""

    def test_uppercase_home(self):
        assert _loan_type("HOME") == "Home Purchase"

    def test_titlecase_home(self):
        assert _loan_type("Home") == "Home Purchase"

    def test_uppercase_home_improvement(self):
        assert _loan_type("HOME_IMPROVEMENT") == "Home Improvement"

    def test_titlecase_home_improvement(self):
        assert _loan_type("Home_Improvement") == "Home Improvement"


class TestLoanTypeFallback:
    """Unknown purposes fall back to title-cased, underscore-stripped form."""

    def test_unknown_single_word(self):
        assert _loan_type("investment") == "Investment"

    def test_unknown_with_underscore(self):
        assert _loan_type("home_renovation") == "Home Renovation"

    def test_unknown_multi_underscore(self):
        assert _loan_type("debt_consolidation") == "Debt Consolidation"

    def test_unknown_three_words(self):
        assert _loan_type("solar_panel_installation") == "Solar Panel Installation"

    def test_unknown_uppercase_input(self):
        # Regression guard: legacy/unexpected ALL_CAPS values must title-case,
        # not preserve the original casing.
        assert _loan_type("HOME_RENOVATION") == "Home Renovation"

    def test_unknown_mixed_case_input(self):
        assert _loan_type("HoMe_RenOvAtIon") == "Home Renovation"


@pytest.mark.parametrize(
    "purpose,expected",
    [
        # Known purposes
        ("home", "Home Purchase"),
        ("home_improvement", "Home Improvement"),
        ("auto", "Vehicle"),
        ("personal", "Personal"),
        ("business", "Business"),
        ("education", "Education"),
        # Case variants on known purposes
        ("HOME", "Home Purchase"),
        ("Home", "Home Purchase"),
        ("HOME_IMPROVEMENT", "Home Improvement"),
        ("Home_Improvement", "Home Improvement"),
        # Unknown purposes — fallback path
        ("investment", "Investment"),
        ("home_renovation", "Home Renovation"),
        ("HOME_RENOVATION", "Home Renovation"),
        ("debt_consolidation", "Debt Consolidation"),
        ("solar_panel_installation", "Solar Panel Installation"),
        ("green_loan", "Green Loan"),
        ("xyz_unknown", "Xyz Unknown"),
        ("HoMe_RenOvAtIon", "Home Renovation"),
    ],
)
def test_loan_type_parity_with_frontend_format_purpose(purpose, expected):
    """Source of truth for the JS formatPurpose helper.

    The same input/output pairs are asserted in
    frontend/src/__tests__/lib/utils.test.ts. Keep the two suites in sync
    so the email-body label and the dashboard label can never diverge.
    """
    assert _loan_type(purpose) == expected
