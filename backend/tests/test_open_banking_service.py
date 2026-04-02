"""Tests for OpenBankingService — CDR/OBP transaction feature derivation."""

import dataclasses
from unittest.mock import patch

from apps.ml_engine.services.open_banking_service import (
    OpenBankingProfile,
    OpenBankingService,
    _clamp,
)
from apps.ml_engine.services.predictor import FEATURE_BOUNDS

# ---------------------------------------------------------------------------
# Sample transaction data (realistic Adatree / OBP format)
# ---------------------------------------------------------------------------
SAMPLE_TRANSACTIONS = [
    # Salary deposits (2 months)
    {
        "description": "PAYROLL - ACME CORP",
        "amount": 5200.00,
        "date": "2025-12-31",
        "balance": 8200.00,
        "counterparty": "ACME Corp",
        "type": "credit",
    },
    {
        "description": "PAYROLL - ACME CORP",
        "amount": 5200.00,
        "date": "2025-11-30",
        "balance": 6100.00,
        "counterparty": "ACME Corp",
        "type": "credit",
    },
    {
        "description": "DIVIDEND - VANGUARD",
        "amount": 120.00,
        "date": "2025-12-15",
        "balance": 4200.00,
        "counterparty": "Vanguard",
        "type": "credit",
    },
    # Rent
    {
        "description": "RENT - 42 SMITH ST",
        "amount": -1800.00,
        "date": "2025-12-01",
        "balance": 3000.00,
        "counterparty": "Ray White Real Estate",
        "type": "debit",
    },
    {
        "description": "RENT - 42 SMITH ST",
        "amount": -1800.00,
        "date": "2025-11-01",
        "balance": 2800.00,
        "counterparty": "Ray White Real Estate",
        "type": "debit",
    },
    # Utilities
    {
        "description": "AGL ENERGY",
        "amount": -180.00,
        "date": "2025-12-10",
        "balance": 4020.00,
        "counterparty": "AGL",
        "type": "debit",
    },
    {
        "description": "TELSTRA MOBILE",
        "amount": -89.00,
        "date": "2025-11-15",
        "balance": 3900.00,
        "counterparty": "Telstra",
        "type": "debit",
    },
    # Subscriptions
    {
        "description": "NETFLIX.COM",
        "amount": -22.99,
        "date": "2025-12-05",
        "balance": 4100.00,
        "counterparty": "Netflix",
        "type": "debit",
    },
    {
        "description": "SPOTIFY",
        "amount": -12.99,
        "date": "2025-12-05",
        "balance": 4077.01,
        "counterparty": "Spotify",
        "type": "debit",
    },
    # Essential spending
    {
        "description": "WOOLWORTHS 1234",
        "amount": -210.00,
        "date": "2025-12-08",
        "balance": 3867.01,
        "counterparty": "Woolworths",
        "type": "debit",
    },
    {
        "description": "COLES EXPRESS",
        "amount": -65.00,
        "date": "2025-12-12",
        "balance": 3802.01,
        "counterparty": "Coles",
        "type": "debit",
    },
    # Other spending
    {
        "description": "JB HI-FI ONLINE",
        "amount": -450.00,
        "date": "2025-12-20",
        "balance": 3352.01,
        "counterparty": "JB Hi-Fi",
        "type": "debit",
    },
    # Low balance day
    {
        "description": "TRANSFER OUT",
        "amount": -3000.00,
        "date": "2025-12-28",
        "balance": -150.00,
        "counterparty": "",
        "type": "debit",
    },
    # Bounced payment
    {
        "description": "DISHONOUR FEE - DD RETURN",
        "amount": -15.00,
        "date": "2025-12-29",
        "balance": -165.00,
        "counterparty": "",
        "type": "debit",
    },
]


# ---------------------------------------------------------------------------
# 1. OpenBankingProfile has all expected fields
# ---------------------------------------------------------------------------
class TestOpenBankingProfileFields:
    def test_has_all_expected_fields(self):
        expected_fields = {
            "income_source_count",
            "rent_payment_regularity",
            "utility_payment_regularity",
            "essential_to_total_spend",
            "subscription_burden",
            "balance_before_payday",
            "min_balance_30d",
            "days_negative_balance_90d",
            "avg_monthly_savings_rate",
            "salary_credit_regularity",
            "num_dishonours_12m",
            "days_in_overdraft_12m",
            "raw_transactions",
        }
        actual_fields = {f.name for f in dataclasses.fields(OpenBankingProfile)}
        assert expected_fields == actual_fields

    def test_profile_is_dataclass(self):
        assert dataclasses.is_dataclass(OpenBankingProfile)


# ---------------------------------------------------------------------------
# 2. _derive_features computes correct values from sample transactions
# ---------------------------------------------------------------------------
class TestDeriveFeatures:
    def setup_method(self):
        self.svc = OpenBankingService()

    def test_derive_features_basic(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        assert isinstance(profile, OpenBankingProfile)
        # Should detect 2 income sources: ACME Corp + Vanguard
        assert profile.income_source_count == 2
        # Should detect dishonour
        assert profile.num_dishonours_12m >= 1
        # Should detect negative balance days
        assert profile.days_negative_balance_90d >= 1

    def test_derive_features_rent_regularity(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        # Rent paid in both months → regularity = 1.0
        assert profile.rent_payment_regularity == 1.0

    def test_derive_features_utility_regularity(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        # Utilities in both months
        assert profile.utility_payment_regularity == 1.0

    def test_derive_features_essential_spend_ratio(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        # Essential spend should be > 0 and <= 1
        assert 0.0 < profile.essential_to_total_spend <= 1.0

    def test_derive_features_savings_rate(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        # With income > spend in at least one month, savings rate should be meaningful
        assert -1.0 <= profile.avg_monthly_savings_rate <= 1.0

    def test_derive_features_empty_transactions(self):
        profile = self.svc._derive_features([])
        assert profile.income_source_count == 1
        assert profile.rent_payment_regularity == 0.0
        assert profile.days_negative_balance_90d == 0

    def test_derive_features_min_balance(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        # The lowest balance in sample is -165.00
        assert profile.min_balance_30d <= 0


# ---------------------------------------------------------------------------
# 3. _classify_transaction categorization
# ---------------------------------------------------------------------------
class TestClassifyTransaction:
    def setup_method(self):
        self.svc = OpenBankingService()

    def test_classify_salary(self):
        t = {"description": "PAYROLL - ACME", "amount": 5000, "counterparty": "ACME"}
        assert self.svc._classify_transaction(t) == "income"

    def test_classify_dividend(self):
        t = {"description": "DIVIDEND PAYMENT", "amount": 100, "counterparty": "Vanguard"}
        assert self.svc._classify_transaction(t) == "income"

    def test_classify_rent(self):
        t = {"description": "RENT PAYMENT", "amount": -1800, "counterparty": "Real Estate Agent"}
        assert self.svc._classify_transaction(t) == "rent"

    def test_classify_utility(self):
        t = {"description": "AGL ENERGY BILL", "amount": -150, "counterparty": "AGL"}
        assert self.svc._classify_transaction(t) == "utility"

    def test_classify_subscription(self):
        t = {"description": "NETFLIX.COM", "amount": -22.99, "counterparty": "Netflix"}
        assert self.svc._classify_transaction(t) == "subscription"

    def test_classify_essential(self):
        t = {"description": "WOOLWORTHS 1234", "amount": -95, "counterparty": "Woolworths"}
        assert self.svc._classify_transaction(t) == "essential"

    def test_classify_other(self):
        t = {"description": "EBAY PURCHASE", "amount": -50, "counterparty": "eBay"}
        assert self.svc._classify_transaction(t) == "other"

    def test_classify_income_requires_positive_amount(self):
        # Salary keyword but negative amount should not be classified as income
        t = {"description": "SALARY REVERSAL", "amount": -100, "counterparty": ""}
        result = self.svc._classify_transaction(t)
        assert result != "income"

    def test_classify_centrelink(self):
        t = {"description": "CENTRELINK PAYMENT", "amount": 800, "counterparty": "Services Australia"}
        assert self.svc._classify_transaction(t) == "income"


# ---------------------------------------------------------------------------
# 4. get_banking_profile returns None when APIs unavailable
# ---------------------------------------------------------------------------
# TODO: should test NaN amounts in transaction list
class TestGetBankingProfileFallback:
    def test_returns_none_when_no_apis(self):
        svc = OpenBankingService()
        svc.adatree_api_key = ""
        with patch.object(svc, "_fetch_obp_data", return_value=None):
            result = svc.get_banking_profile("test-consent-123")
            assert result is None

    def test_returns_none_when_both_fail(self):
        svc = OpenBankingService()
        with (
            patch.object(svc, "_fetch_adatree_data", return_value=None),
            patch.object(svc, "_fetch_obp_data", return_value=None),
        ):
            result = svc.get_banking_profile("test-consent-123")
            assert result is None

    def test_uses_adatree_when_available(self):
        svc = OpenBankingService()
        with patch.object(svc, "_fetch_adatree_data", return_value={"transactions": SAMPLE_TRANSACTIONS}):
            result = svc.get_banking_profile("test-consent-123")
            assert result is not None
            assert isinstance(result, OpenBankingProfile)

    def test_falls_back_to_obp(self):
        svc = OpenBankingService()
        with (
            patch.object(svc, "_fetch_adatree_data", return_value=None),
            patch.object(svc, "_fetch_obp_data", return_value={"transactions": SAMPLE_TRANSACTIONS}),
        ):
            result = svc.get_banking_profile("test-consent-123")
            assert result is not None


# ---------------------------------------------------------------------------
# 5. Savings rate computation
# ---------------------------------------------------------------------------
class TestSavingsRate:
    def setup_method(self):
        self.svc = OpenBankingService()

    def test_positive_savings_rate(self):
        transactions = [
            ({"description": "SALARY", "amount": 5000, "date": "2025-12-01", "counterparty": "Employer"}, "income"),
            ({"description": "RENT", "amount": -2000, "date": "2025-12-05", "counterparty": ""}, "rent"),
            ({"description": "GROCERIES", "amount": -500, "date": "2025-12-10", "counterparty": ""}, "essential"),
        ]
        rate = self.svc._compute_savings_rate(transactions)
        # (5000 - 2500) / 5000 = 0.5
        assert 0.0 < rate <= 1.0

    def test_negative_savings_rate(self):
        transactions = [
            ({"description": "SALARY", "amount": 3000, "date": "2025-12-01", "counterparty": "Employer"}, "income"),
            ({"description": "RENT", "amount": -2000, "date": "2025-12-05", "counterparty": ""}, "rent"),
            ({"description": "SHOPPING", "amount": -2000, "date": "2025-12-10", "counterparty": ""}, "other"),
        ]
        rate = self.svc._compute_savings_rate(transactions)
        assert rate < 0.0

    def test_no_income_returns_zero(self):
        transactions = [
            ({"description": "RENT", "amount": -2000, "date": "2025-12-05", "counterparty": ""}, "rent"),
        ]
        rate = self.svc._compute_savings_rate(transactions)
        assert rate == 0.0


# ---------------------------------------------------------------------------
# 6. All feature values within FEATURE_BOUNDS
# ---------------------------------------------------------------------------
class TestFeatureBoundsCompliance:
    def setup_method(self):
        self.svc = OpenBankingService()

    def _check_bounds(self, profile: OpenBankingProfile):
        """Assert every feature on the profile is within FEATURE_BOUNDS."""
        mapping = {
            "income_source_count": profile.income_source_count,
            "rent_payment_regularity": profile.rent_payment_regularity,
            "utility_payment_regularity": profile.utility_payment_regularity,
            "essential_to_total_spend": profile.essential_to_total_spend,
            "subscription_burden": profile.subscription_burden,
            "balance_before_payday": profile.balance_before_payday,
            "min_balance_30d": profile.min_balance_30d,
            "days_negative_balance_90d": profile.days_negative_balance_90d,
            "avg_monthly_savings_rate": profile.avg_monthly_savings_rate,
            "salary_credit_regularity": profile.salary_credit_regularity,
            "num_dishonours_12m": profile.num_dishonours_12m,
            "days_in_overdraft_12m": profile.days_in_overdraft_12m,
        }
        for feat, val in mapping.items():
            bounds = FEATURE_BOUNDS.get(feat)
            if bounds:
                lo, hi = bounds
                assert lo <= val <= hi, f"{feat}={val} outside [{lo}, {hi}]"

    def test_sample_transactions_within_bounds(self):
        profile = self.svc._derive_features(SAMPLE_TRANSACTIONS)
        self._check_bounds(profile)

    def test_empty_transactions_within_bounds(self):
        profile = self.svc._derive_features([])
        self._check_bounds(profile)

    def test_extreme_transactions_within_bounds(self):
        """Extreme values should still be clamped to bounds."""
        extreme = [
            {
                "description": "SALARY",
                "amount": 999999,
                "date": "2025-12-01",
                "balance": 999999,
                "counterparty": f"Source{i}",
                "type": "credit",
            }
            for i in range(25)  # 25 income sources, should clamp to 20
        ]
        profile = self.svc._derive_features(extreme)
        self._check_bounds(profile)

    def test_clamp_function(self):
        assert _clamp(-5, "rent_payment_regularity") == 0.0
        assert _clamp(2.0, "rent_payment_regularity") == 1.0
        assert _clamp(0.5, "rent_payment_regularity") == 0.5
        assert _clamp(100, "days_negative_balance_90d") == 90
        assert _clamp(-20000, "balance_before_payday") == -10000
