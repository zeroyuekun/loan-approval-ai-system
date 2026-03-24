"""Tests for DataConsistencyChecker and _safe_float — pure Python, no DB."""

import math

import pytest

from apps.ml_engine.services.consistency import DataConsistencyChecker, _safe_float


# Base features representing a valid personal loan application (no warnings/errors)
BASE_FEATURES = {
    'purpose': 'personal',
    'loan_amount': 20000,
    'annual_income': 80000,
    'monthly_expenses': 2500,
    'deposit_amount': 0,
    'property_value': 0,
    'debt_to_income': 0.8,
    'existing_credit_card_limit': 5000,
    'employment_type': 'payg_permanent',
    'employment_length': 5,
    'has_bankruptcy': False,
    'credit_score': 720,
    'applicant_type': 'single',
    'has_cosigner': False,
    'number_of_dependants': 1,
}


@pytest.fixture
def checker():
    return DataConsistencyChecker()


# ------------------------------------------------------------------
# _safe_float
# ------------------------------------------------------------------

class TestSafeFloat:
    def test_normal_int(self):
        assert _safe_float(42) == 42.0

    def test_normal_float(self):
        assert _safe_float(3.14) == 3.14

    def test_string_number(self):
        assert _safe_float("99.5") == 99.5

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0

    def test_nan_returns_default(self):
        assert _safe_float(float('nan')) == 0.0

    def test_inf_returns_default(self):
        assert _safe_float(float('inf')) == 0.0

    def test_neg_inf_returns_default(self):
        assert _safe_float(float('-inf')) == 0.0

    def test_non_numeric_string(self):
        assert _safe_float("abc") == 0.0

    def test_empty_string(self):
        assert _safe_float("") == 0.0


# ------------------------------------------------------------------
# check_all: clean baseline
# ------------------------------------------------------------------

class TestConsistencyCleanBaseline:
    def test_valid_personal_loan_is_consistent(self, checker):
        """A well-formed personal loan should produce no errors or warnings."""
        result = checker.check_all(BASE_FEATURES)
        assert result['consistent'] is True
        assert result['errors'] == []
        assert result['warnings'] == []

    def test_valid_home_loan_is_consistent(self, checker):
        """A well-formed home loan with sensible values should be clean."""
        features = {
            **BASE_FEATURES,
            'purpose': 'home',
            'loan_amount': 400000,
            'property_value': 500000,
            'deposit_amount': 100000,
            'annual_income': 120000,
            'debt_to_income': 3.5,
            'monthly_expenses': 4000,
        }
        result = checker.check_all(features)
        assert result['consistent'] is True
        assert result['errors'] == []
        assert result['warnings'] == []


# ------------------------------------------------------------------
# Individual check tests
# ------------------------------------------------------------------

class TestHomeLoanProperty:
    def test_home_loan_no_property_value_error(self, checker):
        features = {**BASE_FEATURES, 'purpose': 'home', 'property_value': 0}
        result = checker.check_all(features)
        assert result['consistent'] is False
        assert any('property value' in e['message'].lower() for e in result['errors'])

    def test_non_home_loan_skips_property_check(self, checker):
        features = {**BASE_FEATURES, 'purpose': 'personal', 'property_value': 0}
        result = checker.check_all(features)
        # Should not error about missing property value
        assert not any('property value' in e['message'].lower() for e in result['errors'])


class TestDepositVsProperty:
    def test_deposit_exceeds_property_error(self, checker):
        features = {
            **BASE_FEATURES,
            'purpose': 'home',
            'property_value': 500000,
            'deposit_amount': 600000,
            'loan_amount': 200000,
            'debt_to_income': 2.0,
            'monthly_expenses': 4000,
            'annual_income': 120000,
        }
        result = checker.check_all(features)
        assert result['consistent'] is False
        assert any('deposit' in e['message'].lower() and 'property' in e['message'].lower()
                    for e in result['errors'])

    def test_non_home_skips_deposit_vs_property(self, checker):
        features = {**BASE_FEATURES, 'deposit_amount': 999999, 'property_value': 100}
        result = checker.check_all(features)
        # personal loan: deposit_vs_property check is skipped
        assert not any('deposit' in e['message'].lower() and 'property' in e['message'].lower()
                        for e in result['errors'])


class TestDepositVsLoan:
    def test_deposit_much_larger_than_loan_warning(self, checker):
        features = {**BASE_FEATURES, 'deposit_amount': 50000, 'loan_amount': 20000}
        result = checker.check_all(features)
        assert any('deposit' in w['message'].lower() and 'loan' in w['message'].lower()
                    for w in result['warnings'])

    def test_deposit_within_threshold_no_warning(self, checker):
        features = {**BASE_FEATURES, 'deposit_amount': 25000, 'loan_amount': 20000}
        result = checker.check_all(features)
        # 25000 <= 20000 * 1.5 = 30000, so no warning
        assert not any('deposit' in w['message'].lower() and 'significantly larger' in w['message'].lower()
                        for w in result['warnings'])


class TestLvrSanity:
    def test_lvr_above_100_error(self, checker):
        features = {
            **BASE_FEATURES,
            'purpose': 'home',
            'loan_amount': 600000,
            'property_value': 500000,
            'deposit_amount': 50000,
            'debt_to_income': 5.0,
            'annual_income': 120000,
            'monthly_expenses': 4000,
        }
        result = checker.check_all(features)
        assert result['consistent'] is False
        assert any('lvr' in e['message'].lower() or 'exceeds property' in e['message'].lower()
                    for e in result['errors'])


class TestDtiSanity:
    def test_low_declared_dti_warning(self, checker):
        """DTI declared much lower than loan/income should warn."""
        features = {
            **BASE_FEATURES,
            'loan_amount': 80000,
            'annual_income': 80000,
            'debt_to_income': 0.1,  # min_expected = 1.0, 0.1 < 1.0 * 0.5
        }
        result = checker.check_all(features)
        assert any('dti' in w['message'].lower() for w in result['warnings'])


class TestExpensesVsIncome:
    def test_very_low_expenses_warning(self, checker):
        features = {
            **BASE_FEATURES,
            'annual_income': 120000,
            'monthly_expenses': 500,  # 500 < (120000/12)*0.15 = 1500
        }
        result = checker.check_all(features)
        assert any('expenses' in w['message'].lower() for w in result['warnings'])

    def test_very_high_expenses_warning(self, checker):
        features = {
            **BASE_FEATURES,
            'annual_income': 60000,
            'monthly_expenses': 4600,  # 4600 > (60000/12)*0.90 = 4500
        }
        result = checker.check_all(features)
        assert any('expenses' in w['message'].lower() and 'consume' in w['message'].lower()
                    for w in result['warnings'])


class TestCreditCardVsIncome:
    def test_cc_limit_exceeds_80pct_income_warning(self, checker):
        features = {**BASE_FEATURES, 'existing_credit_card_limit': 70000, 'annual_income': 80000}
        result = checker.check_all(features)
        assert any('credit card' in w['message'].lower() for w in result['warnings'])

    def test_cc_limit_within_threshold_no_warning(self, checker):
        features = {**BASE_FEATURES, 'existing_credit_card_limit': 5000, 'annual_income': 80000}
        result = checker.check_all(features)
        assert not any('credit card' in w['message'].lower() for w in result['warnings'])


class TestEmploymentConsistency:
    def test_casual_over_10yr_warning(self, checker):
        features = {**BASE_FEATURES, 'employment_type': 'payg_casual', 'employment_length': 12}
        result = checker.check_all(features)
        assert any('casual' in w['message'].lower() for w in result['warnings'])

    def test_contract_over_15yr_warning(self, checker):
        features = {**BASE_FEATURES, 'employment_type': 'contract', 'employment_length': 16}
        result = checker.check_all(features)
        assert any('contract' in w['message'].lower() for w in result['warnings'])

    def test_permanent_long_tenure_no_warning(self, checker):
        features = {**BASE_FEATURES, 'employment_type': 'payg_permanent', 'employment_length': 20}
        result = checker.check_all(features)
        assert not any('employment' in w['message'].lower() for w in result['warnings'])


class TestBankruptcyVsCredit:
    def test_bankruptcy_high_credit_error(self, checker):
        features = {**BASE_FEATURES, 'has_bankruptcy': True, 'credit_score': 750}
        result = checker.check_all(features)
        assert result['consistent'] is False
        assert any('bankruptcy' in e['message'].lower() for e in result['errors'])

    def test_bankruptcy_mid_credit_warning(self, checker):
        features = {**BASE_FEATURES, 'has_bankruptcy': True, 'credit_score': 650}
        result = checker.check_all(features)
        assert result['consistent'] is True  # warning, not error
        assert any('bankruptcy' in w['message'].lower() for w in result['warnings'])

    def test_bankruptcy_low_credit_no_finding(self, checker):
        features = {**BASE_FEATURES, 'has_bankruptcy': True, 'credit_score': 500}
        result = checker.check_all(features)
        assert not any('bankruptcy' in e['message'].lower() for e in result['errors'])
        assert not any('bankruptcy' in w['message'].lower() for w in result['warnings'])


class TestLoanAmountVsIncome:
    def test_non_home_loan_over_3x_income_warning(self, checker):
        features = {**BASE_FEATURES, 'purpose': 'personal', 'loan_amount': 300000, 'annual_income': 80000}
        result = checker.check_all(features)
        assert any('3' in w['message'] and 'income' in w['message'].lower() for w in result['warnings'])

    def test_home_loan_over_3x_no_warning(self, checker):
        """Home loans are exempt from the 3x income check."""
        features = {
            **BASE_FEATURES,
            'purpose': 'home',
            'loan_amount': 400000,
            'property_value': 500000,
            'deposit_amount': 100000,
            'annual_income': 120000,
            'debt_to_income': 3.5,
            'monthly_expenses': 4000,
        }
        result = checker.check_all(features)
        assert not any('non-home' in w['message'].lower() for w in result['warnings'])


class TestCoupleIncome:
    def test_couple_low_income_warning(self, checker):
        features = {**BASE_FEATURES, 'applicant_type': 'couple', 'annual_income': 40000}
        result = checker.check_all(features)
        assert any('couple' in w['message'].lower() for w in result['warnings'])

    def test_couple_adequate_income_no_warning(self, checker):
        features = {**BASE_FEATURES, 'applicant_type': 'couple', 'annual_income': 80000}
        result = checker.check_all(features)
        assert not any('couple' in w['message'].lower() for w in result['warnings'])


# ------------------------------------------------------------------
# Multiple issues at once
# ------------------------------------------------------------------

class TestMultipleIssues:
    def test_multiple_errors_and_warnings_reported(self, checker):
        """An application with several problems should report all of them."""
        features = {
            **BASE_FEATURES,
            'purpose': 'home',
            'property_value': 0,           # error: no property value
            'has_bankruptcy': True,
            'credit_score': 750,           # error: bankruptcy + high credit
            'employment_type': 'payg_casual',
            'employment_length': 12,       # warning: casual > 10yr
            'applicant_type': 'couple',
            'annual_income': 40000,        # warning: couple low income
        }
        result = checker.check_all(features)
        assert result['consistent'] is False
        assert len(result['errors']) >= 2
        assert len(result['warnings']) >= 2
