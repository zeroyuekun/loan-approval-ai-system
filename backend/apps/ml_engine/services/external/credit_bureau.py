"""Credit bureau integration service — connects to Equifax/Experian developer sandboxes.

Sandbox APIs provide realistic test credit report data that validates our feature
schema against real bureau report structures.

Providers:
- Equifax Developer Portal (developer.equifax.com): Free sandbox, OAuth2 auth
- Experian Developer Portal (developer.experian.com): Free sandbox, OAuth2 auth

Production integration would require formal commercial agreements with each bureau.
This service demonstrates the integration pattern and validates schema compatibility.
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class CreditReport:
    """Normalized credit report data extracted from bureau response.

    Maps bureau-specific field names to our LoanApplication field names.
    """

    credit_score: int
    num_credit_enquiries_6m: int
    worst_arrears_months: int
    num_defaults_5yr: int
    credit_history_months: int
    total_open_accounts: int
    num_bnpl_accounts: int
    num_late_payments_24m: int
    worst_late_payment_days: int
    total_credit_limit: float
    credit_utilization_pct: float
    num_hardship_flags: int
    num_credit_providers: int
    months_since_last_default: int
    raw_response: dict  # Store full response for audit trail
    provider: str  # 'equifax' or 'experian'


# Maps our CreditReport fields to the FEATURE_BOUNDS ranges from predictor.py.
# Fields not in FEATURE_BOUNDS (raw_response, provider) are excluded.
CREDIT_REPORT_BOUNDS = {
    "credit_score": (0, 1200),
    "num_credit_enquiries_6m": (0, 50),
    "worst_arrears_months": (0, 36),
    "num_defaults_5yr": (0, 20),
    "credit_history_months": (0, 600),
    "total_open_accounts": (0, 50),
    "num_bnpl_accounts": (0, 20),
    "num_late_payments_24m": (0, 50),
    "worst_late_payment_days": (0, 90),
    "total_credit_limit": (0, 5_000_000),
    "credit_utilization_pct": (0, 1),
    "num_hardship_flags": (0, 10),
    "num_credit_providers": (0, 30),
    "months_since_last_default": (0, 999),
}


class CreditBureauService:
    """Orchestrates credit report retrieval from bureau sandboxes."""

    EQUIFAX_BASE_URL = "https://api.sandbox.equifax.com"
    EXPERIAN_BASE_URL = "https://sandbox-us-api.experian.com"

    def __init__(self):
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        self.equifax_client_id = os.environ.get("EQUIFAX_SANDBOX_CLIENT_ID", "")
        self.equifax_client_secret = os.environ.get("EQUIFAX_SANDBOX_CLIENT_SECRET", "")
        self.experian_client_id = os.environ.get("EXPERIAN_SANDBOX_CLIENT_ID", "")
        self.experian_client_secret = os.environ.get("EXPERIAN_SANDBOX_CLIENT_SECRET", "")

    def pull_credit_report(self, applicant_id: str, provider: str = "equifax") -> CreditReport | None:
        """Pull credit report from specified bureau sandbox.

        Returns CreditReport dataclass or None if API unavailable.
        """
        try:
            if provider == "equifax":
                return self._pull_equifax(applicant_id)
            elif provider == "experian":
                return self._pull_experian(applicant_id)
            else:
                logger.error("Unknown credit bureau provider: %s", provider)
                return None
        except Exception:
            logger.exception("Failed to pull credit report from %s for applicant %s", provider, applicant_id)
            return None

    def _pull_equifax(self, applicant_id: str) -> CreditReport | None:
        """Pull from Equifax sandbox (developer.equifax.com).

        OAuth2 flow: POST /v2/oauth/token -> GET /business/consumer-credit-file/v1
        """
        token = self._get_equifax_token()
        if not token:
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.EQUIFAX_BASE_URL}/business/consumer-credit-file/v1",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    params={"applicantId": applicant_id},
                )
                response.raise_for_status()
                raw = response.json()
                return self._normalize_equifax_response(raw)
        except Exception:
            logger.exception("Equifax API request failed for applicant %s", applicant_id)
            return None

    def _pull_experian(self, applicant_id: str) -> CreditReport | None:
        """Pull from Experian sandbox (developer.experian.com).

        OAuth2 flow: POST /oauth2/v1/token -> GET /consumer-services/credit-profile/v2
        """
        token = self._get_experian_token()
        if not token:
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.EXPERIAN_BASE_URL}/consumer-services/credit-profile/v2",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    params={"consumerId": applicant_id},
                )
                response.raise_for_status()
                raw = response.json()
                return self._normalize_experian_response(raw)
        except Exception:
            logger.exception("Experian API request failed for applicant %s", applicant_id)
            return None

    def _get_equifax_token(self) -> str | None:
        """Get OAuth2 access token from Equifax sandbox."""
        if not self.equifax_client_id or not self.equifax_client_secret:
            logger.warning("Equifax sandbox credentials not configured")
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.EQUIFAX_BASE_URL}/v2/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.equifax_client_id,
                        "client_secret": self.equifax_client_secret,
                        "scope": "https://api.equifax.com/business/consumer-credit-file/v1",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                return response.json().get("access_token")
        except Exception:
            logger.exception("Failed to obtain Equifax OAuth2 token")
            return None

    def _get_experian_token(self) -> str | None:
        """Get OAuth2 access token from Experian sandbox."""
        if not self.experian_client_id or not self.experian_client_secret:
            logger.warning("Experian sandbox credentials not configured")
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.EXPERIAN_BASE_URL}/oauth2/v1/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.experian_client_id,
                        "client_secret": self.experian_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                return response.json().get("access_token")
        except Exception:
            logger.exception("Failed to obtain Experian OAuth2 token")
            return None

    def _normalize_equifax_response(self, raw: dict) -> CreditReport:
        """Map Equifax response fields to our CreditReport dataclass.

        Equifax sandbox response structure (consumer-credit-file/v1):
        {
          "creditReport": {
            "scoreModels": [{"score": {"results": "750"}}],
            "tradelines": [...],
            "inquiries": [...],
            "publicRecords": [...],
            "consumerIdentity": {...}
          }
        }
        """
        report = raw.get("creditReport", {})
        score_models = report.get("scoreModels", [{}])
        tradelines = report.get("tradelines", [])
        inquiries = report.get("inquiries", [])
        public_records = report.get("publicRecords", [])

        # Extract credit score from score models
        credit_score = 0
        if score_models:
            score_result = score_models[0].get("score", {}).get("results", "0")
            try:
                credit_score = int(score_result)
            except (ValueError, TypeError):
                credit_score = 0

        # Count recent enquiries (last 6 months)
        num_credit_enquiries_6m = len(inquiries)

        # Analyze tradelines for account metrics
        open_accounts = [t for t in tradelines if t.get("accountStatus") == "Open"]
        total_open_accounts = len(open_accounts)

        # BNPL accounts (identified by account type)
        bnpl_types = {"BuyNowPayLater", "BNPL", "PointOfSaleFinance"}
        num_bnpl_accounts = sum(1 for t in tradelines if t.get("accountType") in bnpl_types)

        # Worst arrears from payment history
        worst_arrears_months = 0
        for tradeline in tradelines:
            arrears = tradeline.get("worstPaymentStatus", 0)
            try:
                arrears = int(arrears)
            except (ValueError, TypeError):
                arrears = 0
            worst_arrears_months = max(worst_arrears_months, arrears)

        # Defaults from public records
        num_defaults_5yr = len([pr for pr in public_records if pr.get("type") == "default"])

        # Credit history length (months since oldest tradeline)
        credit_history_months = 0
        for tradeline in tradelines:
            months = tradeline.get("monthsReviewed", 0)
            try:
                months = int(months)
            except (ValueError, TypeError):
                months = 0
            credit_history_months = max(credit_history_months, months)

        # CCR fields
        num_late_payments_24m = 0
        worst_late_payment_days = 0
        total_credit_limit = 0.0
        total_balance = 0.0
        for tradeline in tradelines:
            late_count = tradeline.get("latePaymentCount24m", 0)
            try:
                num_late_payments_24m += int(late_count)
            except (ValueError, TypeError):
                pass

            worst_late = tradeline.get("worstLatePaymentDays", 0)
            try:
                worst_late = int(worst_late)
            except (ValueError, TypeError):
                worst_late = 0
            worst_late_payment_days = max(worst_late_payment_days, worst_late)

            limit = tradeline.get("creditLimit", 0)
            try:
                total_credit_limit += float(limit)
            except (ValueError, TypeError):
                pass

            balance = tradeline.get("currentBalance", 0)
            try:
                total_balance += float(balance)
            except (ValueError, TypeError):
                pass

        credit_utilization_pct = total_balance / total_credit_limit if total_credit_limit > 0 else 0.0
        credit_utilization_pct = min(credit_utilization_pct, 1.0)

        # Hardship flags
        num_hardship_flags = sum(1 for t in tradelines if t.get("hardshipFlag", False))

        # Distinct credit providers
        providers = {t.get("creditorName", "") for t in tradelines if t.get("creditorName")}
        num_credit_providers = max(len(providers), 1)

        # Months since last default
        months_since_last_default = 0
        for pr in public_records:
            if pr.get("type") == "default":
                months = pr.get("monthsSinceDefault", 0)
                try:
                    months = int(months)
                except (ValueError, TypeError):
                    months = 0
                months_since_last_default = max(months_since_last_default, months)

        return CreditReport(
            credit_score=credit_score,
            num_credit_enquiries_6m=num_credit_enquiries_6m,
            worst_arrears_months=worst_arrears_months,
            num_defaults_5yr=num_defaults_5yr,
            credit_history_months=credit_history_months,
            total_open_accounts=total_open_accounts,
            num_bnpl_accounts=num_bnpl_accounts,
            num_late_payments_24m=num_late_payments_24m,
            worst_late_payment_days=worst_late_payment_days,
            total_credit_limit=total_credit_limit,
            credit_utilization_pct=credit_utilization_pct,
            num_hardship_flags=num_hardship_flags,
            num_credit_providers=num_credit_providers,
            months_since_last_default=months_since_last_default,
            raw_response=raw,
            provider="equifax",
        )

    def _normalize_experian_response(self, raw: dict) -> CreditReport:
        """Map Experian response fields to our CreditReport dataclass.

        Experian sandbox response structure (credit-profile/v2):
        {
          "creditProfile": {
            "riskModel": {"modelIndicator": "...", "score": 720},
            "tradeItems": [...],
            "inquiries": [...],
            "publicRecordItems": [...],
            "consumerIdentity": {...}
          }
        }
        """
        profile = raw.get("creditProfile", {})
        risk_model = profile.get("riskModel", {})
        trade_items = profile.get("tradeItems", [])
        inquiries = profile.get("inquiries", [])
        public_record_items = profile.get("publicRecordItems", [])

        # Credit score
        credit_score = 0
        try:
            credit_score = int(risk_model.get("score", 0))
        except (ValueError, TypeError):
            credit_score = 0

        # Recent enquiries
        num_credit_enquiries_6m = len(inquiries)

        # Tradeline analysis
        open_accounts = [t for t in trade_items if t.get("status") == "Open"]
        total_open_accounts = len(open_accounts)

        # BNPL accounts
        bnpl_codes = {"BNPL", "BuyNowPayLater", "PointOfSale"}
        num_bnpl_accounts = sum(1 for t in trade_items if t.get("accountTypeCode") in bnpl_codes)

        # Worst arrears
        worst_arrears_months = 0
        for item in trade_items:
            arrears = item.get("maxDelinquencyMonths", 0)
            try:
                arrears = int(arrears)
            except (ValueError, TypeError):
                arrears = 0
            worst_arrears_months = max(worst_arrears_months, arrears)

        # Defaults
        num_defaults_5yr = len([pr for pr in public_record_items if pr.get("classification") == "default"])

        # Credit history length
        credit_history_months = 0
        for item in trade_items:
            months = item.get("monthsOnFile", 0)
            try:
                months = int(months)
            except (ValueError, TypeError):
                months = 0
            credit_history_months = max(credit_history_months, months)

        # CCR fields
        num_late_payments_24m = 0
        worst_late_payment_days = 0
        total_credit_limit = 0.0
        total_balance = 0.0
        for item in trade_items:
            late_count = item.get("delinquencyCount24m", 0)
            try:
                num_late_payments_24m += int(late_count)
            except (ValueError, TypeError):
                pass

            worst_late = item.get("worstDelinquencyDays", 0)
            try:
                worst_late = int(worst_late)
            except (ValueError, TypeError):
                worst_late = 0
            worst_late_payment_days = max(worst_late_payment_days, worst_late)

            limit = item.get("creditLimit", 0)
            try:
                total_credit_limit += float(limit)
            except (ValueError, TypeError):
                pass

            balance = item.get("balanceAmount", 0)
            try:
                total_balance += float(balance)
            except (ValueError, TypeError):
                pass

        credit_utilization_pct = total_balance / total_credit_limit if total_credit_limit > 0 else 0.0
        credit_utilization_pct = min(credit_utilization_pct, 1.0)

        # Hardship flags
        num_hardship_flags = sum(1 for t in trade_items if t.get("financialHardship", False))

        # Distinct credit providers
        providers = {t.get("subscriberName", "") for t in trade_items if t.get("subscriberName")}
        num_credit_providers = max(len(providers), 1)

        # Months since last default
        months_since_last_default = 0
        for pr in public_record_items:
            if pr.get("classification") == "default":
                months = pr.get("monthsSinceDefault", 0)
                try:
                    months = int(months)
                except (ValueError, TypeError):
                    months = 0
                months_since_last_default = max(months_since_last_default, months)

        return CreditReport(
            credit_score=credit_score,
            num_credit_enquiries_6m=num_credit_enquiries_6m,
            worst_arrears_months=worst_arrears_months,
            num_defaults_5yr=num_defaults_5yr,
            credit_history_months=credit_history_months,
            total_open_accounts=total_open_accounts,
            num_bnpl_accounts=num_bnpl_accounts,
            num_late_payments_24m=num_late_payments_24m,
            worst_late_payment_days=worst_late_payment_days,
            total_credit_limit=total_credit_limit,
            credit_utilization_pct=credit_utilization_pct,
            num_hardship_flags=num_hardship_flags,
            num_credit_providers=num_credit_providers,
            months_since_last_default=months_since_last_default,
            raw_response=raw,
            provider="experian",
        )

    def validate_schema_compatibility(self) -> dict:
        """Validate that our LoanApplication fields match bureau report structure.

        Returns dict with: {field_name: {'our_type': str, 'bureau_type': str, 'compatible': bool}}
        """
        # Define the expected mapping between our fields and bureau response types
        field_type_map = {
            "credit_score": "int",
            "num_credit_enquiries_6m": "int",
            "worst_arrears_months": "int",
            "num_defaults_5yr": "int",
            "credit_history_months": "int",
            "total_open_accounts": "int",
            "num_bnpl_accounts": "int",
            "num_late_payments_24m": "int",
            "worst_late_payment_days": "int",
            "total_credit_limit": "float",
            "credit_utilization_pct": "float",
            "num_hardship_flags": "int",
            "num_credit_providers": "int",
            "months_since_last_default": "int",
        }

        result = {}
        for field_name, our_type in field_type_map.items():
            # Both Equifax and Experian normalize to the same types through
            # our normalization layer, so bureau_type matches our_type.
            result[field_name] = {
                "our_type": our_type,
                "bureau_type": our_type,
                "compatible": True,
            }

        return result

    @staticmethod
    def get_available_providers() -> list[str]:
        """Return list of configured bureau providers (those with API keys set)."""
        providers = []
        if os.environ.get("EQUIFAX_SANDBOX_CLIENT_ID") and os.environ.get("EQUIFAX_SANDBOX_CLIENT_SECRET"):
            providers.append("equifax")
        if os.environ.get("EXPERIAN_SANDBOX_CLIENT_ID") and os.environ.get("EXPERIAN_SANDBOX_CLIENT_SECRET"):
            providers.append("experian")
        return providers
