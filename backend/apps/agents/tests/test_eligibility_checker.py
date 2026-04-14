"""Tests for EligibilityChecker — age-at-loan-maturity policy gate."""
import datetime
from types import SimpleNamespace

import pytest

from apps.agents.services.eligibility_checker import EligibilityChecker


def _make_application(age_years: int | None, loan_term_months: int):
    """Build a minimal duck-typed application for the pure checker.

    EligibilityChecker is deliberately pure: it reads only date_of_birth_date
    and loan_term_months, so we don't need a Django model instance.
    """
    dob = None
    if age_years is not None:
        today = datetime.date.today()
        dob = today.replace(year=today.year - age_years)
    profile = SimpleNamespace(date_of_birth_date=dob)
    applicant = SimpleNamespace(profile=profile)
    return SimpleNamespace(applicant=applicant, loan_term_months=loan_term_months)


def test_passes_when_maturity_age_under_67():
    app = _make_application(age_years=30, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is True
    assert result.reason_code is None


def test_denies_when_maturity_age_over_67():
    app = _make_application(age_years=65, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is False
    assert result.reason_code == "R50"
    assert "67" in (result.detail or "")


def test_boundary_exactly_67_passes():
    app = _make_application(age_years=62, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is True


def test_passes_when_date_of_birth_missing():
    app = _make_application(age_years=None, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is True
