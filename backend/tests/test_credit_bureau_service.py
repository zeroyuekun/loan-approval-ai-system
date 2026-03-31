"""Tests for the credit bureau integration service."""

import os
from dataclasses import fields as dataclass_fields
from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.ml_engine.services.credit_bureau_service import (
    CREDIT_REPORT_BOUNDS,
    CreditBureauService,
    CreditReport,
)


# ---------------------------------------------------------------------------
# Sample fixtures — realistic sandbox response shapes
# ---------------------------------------------------------------------------

SAMPLE_EQUIFAX_RESPONSE = {
    "creditReport": {
        "scoreModels": [
            {"score": {"results": "742"}},
        ],
        "tradelines": [
            {
                "creditorName": "ANZ Bank",
                "accountStatus": "Open",
                "accountType": "CreditCard",
                "worstPaymentStatus": 1,
                "monthsReviewed": 96,
                "latePaymentCount24m": 2,
                "worstLatePaymentDays": 30,
                "creditLimit": 15000,
                "currentBalance": 4500,
                "hardshipFlag": False,
            },
            {
                "creditorName": "Westpac",
                "accountStatus": "Open",
                "accountType": "PersonalLoan",
                "worstPaymentStatus": 0,
                "monthsReviewed": 48,
                "latePaymentCount24m": 0,
                "worstLatePaymentDays": 0,
                "creditLimit": 30000,
                "currentBalance": 12000,
                "hardshipFlag": False,
            },
            {
                "creditorName": "Afterpay",
                "accountStatus": "Open",
                "accountType": "BuyNowPayLater",
                "worstPaymentStatus": 0,
                "monthsReviewed": 12,
                "latePaymentCount24m": 1,
                "worstLatePaymentDays": 14,
                "creditLimit": 2000,
                "currentBalance": 500,
                "hardshipFlag": False,
            },
        ],
        "inquiries": [
            {"date": "2025-01-15", "subscriber": "CBA"},
            {"date": "2025-03-01", "subscriber": "NAB"},
        ],
        "publicRecords": [
            {
                "type": "default",
                "monthsSinceDefault": 36,
            },
        ],
    },
}

SAMPLE_EXPERIAN_RESPONSE = {
    "creditProfile": {
        "riskModel": {"modelIndicator": "VantageScore3", "score": 685},
        "tradeItems": [
            {
                "subscriberName": "CBA",
                "status": "Open",
                "accountTypeCode": "Mortgage",
                "maxDelinquencyMonths": 0,
                "monthsOnFile": 120,
                "delinquencyCount24m": 0,
                "worstDelinquencyDays": 0,
                "creditLimit": 500000,
                "balanceAmount": 320000,
                "financialHardship": False,
            },
            {
                "subscriberName": "NAB",
                "status": "Open",
                "accountTypeCode": "CreditCard",
                "maxDelinquencyMonths": 2,
                "monthsOnFile": 60,
                "delinquencyCount24m": 3,
                "worstDelinquencyDays": 60,
                "creditLimit": 10000,
                "balanceAmount": 7500,
                "financialHardship": True,
            },
            {
                "subscriberName": "Zip",
                "status": "Open",
                "accountTypeCode": "BNPL",
                "maxDelinquencyMonths": 0,
                "monthsOnFile": 6,
                "delinquencyCount24m": 0,
                "worstDelinquencyDays": 0,
                "creditLimit": 1500,
                "balanceAmount": 200,
                "financialHardship": False,
            },
        ],
        "inquiries": [
            {"date": "2025-02-20", "subscriber": "Westpac"},
        ],
        "publicRecordItems": [
            {
                "classification": "default",
                "monthsSinceDefault": 48,
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Test CreditReport dataclass
# ---------------------------------------------------------------------------


class TestCreditReportDataclass:
    """Test CreditReport dataclass has all expected fields."""

    EXPECTED_FIELDS = {
        "credit_score",
        "num_credit_enquiries_6m",
        "worst_arrears_months",
        "num_defaults_5yr",
        "credit_history_months",
        "total_open_accounts",
        "num_bnpl_accounts",
        "num_late_payments_24m",
        "worst_late_payment_days",
        "total_credit_limit",
        "credit_utilization_pct",
        "num_hardship_flags",
        "num_credit_providers",
        "months_since_last_default",
        "raw_response",
        "provider",
    }

    def test_all_expected_fields_exist(self):
        actual_fields = {f.name for f in dataclass_fields(CreditReport)}
        assert actual_fields == self.EXPECTED_FIELDS

    def test_can_instantiate_with_all_fields(self):
        report = CreditReport(
            credit_score=750,
            num_credit_enquiries_6m=2,
            worst_arrears_months=0,
            num_defaults_5yr=0,
            credit_history_months=120,
            total_open_accounts=5,
            num_bnpl_accounts=1,
            num_late_payments_24m=0,
            worst_late_payment_days=0,
            total_credit_limit=50000.0,
            credit_utilization_pct=0.35,
            num_hardship_flags=0,
            num_credit_providers=3,
            months_since_last_default=0,
            raw_response={},
            provider="equifax",
        )
        assert report.credit_score == 750
        assert report.provider == "equifax"


# ---------------------------------------------------------------------------
# Test Equifax normalization
# ---------------------------------------------------------------------------


class TestNormalizeEquifaxResponse:
    """Test normalize_equifax_response maps correctly."""

    def setup_method(self):
        self.service = CreditBureauService()

    def test_credit_score_extracted(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.credit_score == 742

    def test_enquiries_counted(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.num_credit_enquiries_6m == 2

    def test_open_accounts_counted(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        # All 3 tradelines have accountStatus == 'Open'
        assert report.total_open_accounts == 3

    def test_bnpl_accounts_identified(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.num_bnpl_accounts == 1

    def test_worst_arrears(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.worst_arrears_months == 1

    def test_defaults_counted(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.num_defaults_5yr == 1

    def test_credit_history_months(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.credit_history_months == 96

    def test_late_payments_aggregated(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        # 2 + 0 + 1 = 3
        assert report.num_late_payments_24m == 3

    def test_worst_late_payment_days(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.worst_late_payment_days == 30

    def test_credit_limit_summed(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.total_credit_limit == 47000.0

    def test_credit_utilization_calculated(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        # (4500 + 12000 + 500) / 47000 = 0.3617...
        expected = 17000.0 / 47000.0
        assert abs(report.credit_utilization_pct - expected) < 0.001

    def test_hardship_flags(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.num_hardship_flags == 0

    def test_credit_providers_counted(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        # ANZ Bank, Westpac, Afterpay = 3
        assert report.num_credit_providers == 3

    def test_months_since_last_default(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.months_since_last_default == 36

    def test_raw_response_preserved(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.raw_response == SAMPLE_EQUIFAX_RESPONSE

    def test_provider_set(self):
        report = self.service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        assert report.provider == "equifax"

    def test_empty_response_handled(self):
        report = self.service._normalize_equifax_response({})
        assert report.credit_score == 0
        assert report.total_open_accounts == 0
        assert report.num_credit_providers == 1  # min 1


# ---------------------------------------------------------------------------
# Test Experian normalization
# ---------------------------------------------------------------------------


class TestNormalizeExperianResponse:
    """Test normalize_experian_response maps correctly."""

    def setup_method(self):
        self.service = CreditBureauService()

    def test_credit_score_extracted(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.credit_score == 685

    def test_enquiries_counted(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.num_credit_enquiries_6m == 1

    def test_open_accounts_counted(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.total_open_accounts == 3

    def test_bnpl_accounts_identified(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.num_bnpl_accounts == 1

    def test_worst_arrears(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.worst_arrears_months == 2

    def test_defaults_counted(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.num_defaults_5yr == 1

    def test_credit_history_months(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.credit_history_months == 120

    def test_late_payments_aggregated(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        # 0 + 3 + 0 = 3
        assert report.num_late_payments_24m == 3

    def test_worst_late_payment_days(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.worst_late_payment_days == 60

    def test_credit_limit_summed(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.total_credit_limit == 511500.0

    def test_credit_utilization_calculated(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        expected = 327700.0 / 511500.0
        assert abs(report.credit_utilization_pct - expected) < 0.001

    def test_hardship_flags(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        # Only NAB tradeline has financialHardship=True
        assert report.num_hardship_flags == 1

    def test_credit_providers_counted(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        # CBA, NAB, Zip = 3
        assert report.num_credit_providers == 3

    def test_months_since_last_default(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.months_since_last_default == 48

    def test_raw_response_preserved(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.raw_response == SAMPLE_EXPERIAN_RESPONSE

    def test_provider_set(self):
        report = self.service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        assert report.provider == "experian"

    def test_empty_response_handled(self):
        report = self.service._normalize_experian_response({})
        assert report.credit_score == 0
        assert report.total_open_accounts == 0


# ---------------------------------------------------------------------------
# Test pull_credit_report returns None on failure
# ---------------------------------------------------------------------------


class TestPullCreditReportFailures:
    """Test pull_credit_report returns None when API unavailable."""

    def setup_method(self):
        self.service = CreditBureauService()

    def test_returns_none_for_unknown_provider(self):
        result = self.service.pull_credit_report("applicant-1", provider="unknown")
        assert result is None

    @patch.object(CreditBureauService, "_get_equifax_token", return_value=None)
    def test_returns_none_when_equifax_token_fails(self, mock_token):
        result = self.service.pull_credit_report("applicant-1", provider="equifax")
        assert result is None

    @patch.object(CreditBureauService, "_get_experian_token", return_value=None)
    def test_returns_none_when_experian_token_fails(self, mock_token):
        result = self.service.pull_credit_report("applicant-1", provider="experian")
        assert result is None

    @patch.object(CreditBureauService, "_get_equifax_token", return_value="test-token")
    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    def test_returns_none_when_equifax_api_raises(self, mock_client_cls, mock_token):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = self.service.pull_credit_report("applicant-1", provider="equifax")
        assert result is None

    @patch.object(CreditBureauService, "_get_experian_token", return_value="test-token")
    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    def test_returns_none_when_experian_api_raises(self, mock_client_cls, mock_token):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = self.service.pull_credit_report("applicant-1", provider="experian")
        assert result is None


# ---------------------------------------------------------------------------
# Test validate_schema_compatibility
# ---------------------------------------------------------------------------


class TestValidateSchemaCompatibility:
    """Test validate_schema_compatibility returns all LoanApplication bureau fields."""

    BUREAU_FIELDS = {
        "credit_score",
        "num_credit_enquiries_6m",
        "worst_arrears_months",
        "num_defaults_5yr",
        "credit_history_months",
        "total_open_accounts",
        "num_bnpl_accounts",
        "num_late_payments_24m",
        "worst_late_payment_days",
        "total_credit_limit",
        "credit_utilization_pct",
        "num_hardship_flags",
        "num_credit_providers",
        "months_since_last_default",
    }

    def test_returns_all_bureau_fields(self):
        service = CreditBureauService()
        result = service.validate_schema_compatibility()
        assert set(result.keys()) == self.BUREAU_FIELDS

    def test_all_fields_compatible(self):
        service = CreditBureauService()
        result = service.validate_schema_compatibility()
        for field_name, info in result.items():
            assert info["compatible"] is True, f"{field_name} should be compatible"

    def test_type_info_present(self):
        service = CreditBureauService()
        result = service.validate_schema_compatibility()
        for field_name, info in result.items():
            assert "our_type" in info
            assert "bureau_type" in info
            assert info["our_type"] in ("int", "float")


# ---------------------------------------------------------------------------
# Test get_available_providers
# ---------------------------------------------------------------------------


class TestGetAvailableProviders:
    """Test get_available_providers with/without env vars."""

    def test_no_providers_without_env_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            providers = CreditBureauService.get_available_providers()
            assert providers == []

    def test_equifax_only(self):
        env = {
            "EQUIFAX_SANDBOX_CLIENT_ID": "test-id",
            "EQUIFAX_SANDBOX_CLIENT_SECRET": "test-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = CreditBureauService.get_available_providers()
            assert providers == ["equifax"]

    def test_experian_only(self):
        env = {
            "EXPERIAN_SANDBOX_CLIENT_ID": "test-id",
            "EXPERIAN_SANDBOX_CLIENT_SECRET": "test-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = CreditBureauService.get_available_providers()
            assert providers == ["experian"]

    def test_both_providers(self):
        env = {
            "EQUIFAX_SANDBOX_CLIENT_ID": "eq-id",
            "EQUIFAX_SANDBOX_CLIENT_SECRET": "eq-secret",
            "EXPERIAN_SANDBOX_CLIENT_ID": "ex-id",
            "EXPERIAN_SANDBOX_CLIENT_SECRET": "ex-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = CreditBureauService.get_available_providers()
            assert providers == ["equifax", "experian"]

    def test_partial_credentials_not_listed(self):
        env = {
            "EQUIFAX_SANDBOX_CLIENT_ID": "eq-id",
            # Missing EQUIFAX_SANDBOX_CLIENT_SECRET
        }
        with patch.dict(os.environ, env, clear=True):
            providers = CreditBureauService.get_available_providers()
            assert "equifax" not in providers


# ---------------------------------------------------------------------------
# Test OAuth2 token retrieval (mocked)
# ---------------------------------------------------------------------------


class TestOAuth2TokenRetrieval:
    """Test OAuth2 token retrieval for both bureaus."""

    def setup_method(self):
        self.service = CreditBureauService()

    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    def test_equifax_token_success(self, mock_client_cls):
        self.service.equifax_client_id = "test-id"
        self.service.equifax_client_secret = "test-secret"

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "equifax-token-123"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        token = self.service._get_equifax_token()
        assert token == "equifax-token-123"
        mock_client.post.assert_called_once()

    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    def test_experian_token_success(self, mock_client_cls):
        self.service.experian_client_id = "test-id"
        self.service.experian_client_secret = "test-secret"

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "experian-token-456"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        token = self.service._get_experian_token()
        assert token == "experian-token-456"

    def test_equifax_token_returns_none_without_credentials(self):
        self.service.equifax_client_id = ""
        self.service.equifax_client_secret = ""
        token = self.service._get_equifax_token()
        assert token is None

    def test_experian_token_returns_none_without_credentials(self):
        self.service.experian_client_id = ""
        self.service.experian_client_secret = ""
        token = self.service._get_experian_token()
        assert token is None

    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    def test_equifax_token_returns_none_on_http_error(self, mock_client_cls):
        self.service.equifax_client_id = "test-id"
        self.service.equifax_client_secret = "test-secret"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        token = self.service._get_equifax_token()
        assert token is None

    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    def test_experian_token_returns_none_on_http_error(self, mock_client_cls):
        self.service.experian_client_id = "test-id"
        self.service.experian_client_secret = "test-secret"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        token = self.service._get_experian_token()
        assert token is None


# ---------------------------------------------------------------------------
# Test CreditReport fields within FEATURE_BOUNDS ranges
# ---------------------------------------------------------------------------


class TestCreditReportFieldBounds:
    """Test that all CreditReport fields from sample fixtures are within FEATURE_BOUNDS."""

    def _check_bounds(self, report: CreditReport):
        """Assert every numeric CreditReport field is within CREDIT_REPORT_BOUNDS."""
        for field_name, (lo, hi) in CREDIT_REPORT_BOUNDS.items():
            value = getattr(report, field_name)
            assert lo <= value <= hi, f"{field_name}={value} is outside FEATURE_BOUNDS [{lo}, {hi}]"

    def test_equifax_sample_within_bounds(self):
        service = CreditBureauService()
        report = service._normalize_equifax_response(SAMPLE_EQUIFAX_RESPONSE)
        self._check_bounds(report)

    def test_experian_sample_within_bounds(self):
        service = CreditBureauService()
        report = service._normalize_experian_response(SAMPLE_EXPERIAN_RESPONSE)
        self._check_bounds(report)

    def test_empty_equifax_within_bounds(self):
        service = CreditBureauService()
        report = service._normalize_equifax_response({})
        self._check_bounds(report)

    def test_empty_experian_within_bounds(self):
        service = CreditBureauService()
        report = service._normalize_experian_response({})
        self._check_bounds(report)

    def test_all_credit_report_numeric_fields_have_bounds(self):
        """Every numeric field on CreditReport should appear in CREDIT_REPORT_BOUNDS."""
        skip = {"raw_response", "provider"}
        for f in dataclass_fields(CreditReport):
            if f.name in skip:
                continue
            assert f.name in CREDIT_REPORT_BOUNDS, f"CreditReport.{f.name} has no entry in CREDIT_REPORT_BOUNDS"


# ---------------------------------------------------------------------------
# Test full pull flow (mocked end-to-end)
# ---------------------------------------------------------------------------


class TestPullCreditReportEndToEnd:
    """Test the full pull_credit_report flow with mocked HTTP."""

    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    @patch.object(CreditBureauService, "_get_equifax_token", return_value="mock-token")
    def test_equifax_full_flow(self, mock_token, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EQUIFAX_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        service = CreditBureauService()
        report = service.pull_credit_report("applicant-123", provider="equifax")

        assert report is not None
        assert report.credit_score == 742
        assert report.provider == "equifax"
        assert report.raw_response == SAMPLE_EQUIFAX_RESPONSE

    @patch("apps.ml_engine.services.credit_bureau_service.httpx.Client")
    @patch.object(CreditBureauService, "_get_experian_token", return_value="mock-token")
    def test_experian_full_flow(self, mock_token, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_EXPERIAN_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        service = CreditBureauService()
        report = service.pull_credit_report("applicant-456", provider="experian")

        assert report is not None
        assert report.credit_score == 685
        assert report.provider == "experian"
        assert report.raw_response == SAMPLE_EXPERIAN_RESPONSE
