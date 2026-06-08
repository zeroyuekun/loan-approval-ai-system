"""Open Banking / CDR data service — fetches transaction-derived features from banking APIs.

Integrates with Australian Consumer Data Right (CDR) sandbox and Open Bank Project
to derive behavioral lending features from bank transaction data.

Sources:
- Adatree CDR Sandbox: CDR-compliant test data (Australian-specific)
- Open Bank Project (openbankproject.com): Free banking API sandbox

These populate CDR/Open Banking features on LoanApplication that feed the ML model.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from apps.ml_engine.services.predictor import FEATURE_BOUNDS

logger = logging.getLogger(__name__)

# Transaction classification keywords
_INCOME_KEYWORDS = {"salary", "wage", "payroll", "commission", "dividend", "interest", "pension", "centrelink"}
_RENT_KEYWORDS = {"rent", "lease", "rental", "real estate", "realestate", "property"}
_UTILITY_KEYWORDS = {
    "electricity",
    "gas",
    "water",
    "energy",
    "agl",
    "origin",
    "telstra",
    "optus",
    "vodafone",
    "nbn",
    "internet",
}
_SUBSCRIPTION_KEYWORDS = {
    "netflix",
    "spotify",
    "disney",
    "apple.com",
    "google storage",
    "amazon prime",
    "stan",
    "binge",
    "kayo",
    "gym",
    "membership",
}
_ESSENTIAL_KEYWORDS = (
    _RENT_KEYWORDS
    | _UTILITY_KEYWORDS
    | {
        "woolworths",
        "coles",
        "aldi",
        "iga",
        "grocery",
        "chemist",
        "pharmacy",
        "medical",
        "doctor",
        "health",
        "insurance",
        "petrol",
        "fuel",
        "transport",
        "opal",
        "myki",
    }
)


@dataclass
class OpenBankingProfile:
    """Transaction-derived features from open banking data."""

    income_source_count: int
    rent_payment_regularity: float  # 0-1
    utility_payment_regularity: float  # 0-1
    essential_to_total_spend: float  # 0-1
    subscription_burden: float  # 0-1
    balance_before_payday: float
    min_balance_30d: float
    days_negative_balance_90d: int
    avg_monthly_savings_rate: float  # -1 to 1
    salary_credit_regularity: float  # 0-1
    num_dishonours_12m: int
    days_in_overdraft_12m: int
    raw_transactions: list = field(default_factory=list)  # For audit trail


def _clamp(value: float, feature_name: str) -> float:
    """Clamp a value to FEATURE_BOUNDS if the feature is defined there."""
    bounds = FEATURE_BOUNDS.get(feature_name)
    if bounds is None:
        return value
    lo, hi = bounds
    return max(lo, min(hi, value))


class OpenBankingService:
    """Fetches and processes open banking data for lending features."""

    def __init__(self):
        self.timeout = httpx.Timeout(20.0, connect=5.0)
        self.adatree_api_key = os.environ.get("ADATREE_SANDBOX_KEY", "")
        self.obp_base_url = os.environ.get("OBP_BASE_URL", "https://apisandbox.openbankproject.com")

    def get_banking_profile(self, consent_id: str) -> OpenBankingProfile | None:
        """Fetch open banking profile from CDR or OBP sandbox.

        Requires consumer consent_id (CDR consent token).
        Returns derived features or None if unavailable.
        """
        # Try Adatree CDR sandbox first
        data = self._fetch_adatree_data(consent_id)
        if data and data.get("transactions"):
            logger.info("Using Adatree CDR data for consent_id=%s", consent_id)
            return self._derive_features(data["transactions"])

        # Fall back to Open Bank Project sandbox
        data = self._fetch_obp_data(consent_id)
        if data and data.get("transactions"):
            logger.info("Using OBP data for account_id=%s", consent_id)
            return self._derive_features(data["transactions"])

        logger.warning("No open banking data available for consent_id=%s", consent_id)
        return None

    def _fetch_adatree_data(self, consent_id: str) -> dict | None:
        """Fetch CDR data from Adatree sandbox."""
        if not self.adatree_api_key:
            logger.debug("Adatree API key not configured, skipping")
            return None

        url = "https://cdr-sandbox.adatree.com.au/data/banking/accounts/transactions"
        headers = {
            "Authorization": f"Bearer {self.adatree_api_key}",
            "x-cds-client-headers": consent_id,
            "x-v": "1",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                transactions = body.get("data", {}).get("transactions", [])
                return {"transactions": transactions}
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("Adatree fetch failed: %s", exc)
            return None

    def _fetch_obp_data(self, account_id: str) -> dict | None:
        """Fetch transaction data from Open Bank Project sandbox."""
        url = f"{self.obp_base_url}/obp/v4.0.0/my/banks/au.01.sandbox/accounts/{account_id}/transactions"
        headers = {
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                raw_txns = body.get("transactions", [])
                # Normalize OBP format to our internal format
                transactions = []
                for t in raw_txns:
                    details = t.get("details", {})
                    other = t.get("other_account", {})
                    transactions.append(
                        {
                            "description": details.get("description", ""),
                            "amount": float(details.get("value", {}).get("amount", 0)),
                            "date": details.get("completed", ""),
                            "type": details.get("type", ""),
                            "balance": float(t.get("details", {}).get("new_balance", {}).get("amount", 0)),
                            "counterparty": other.get("holder", {}).get("name", ""),
                        }
                    )
                return {"transactions": transactions}
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("OBP fetch failed: %s", exc)
            return None

    def _derive_features(self, transactions: list) -> OpenBankingProfile:
        """Derive lending features from raw transaction data.

        Computes: income regularity, expense patterns, savings rate,
        overdraft frequency, etc. from transaction history.
        """
        if not transactions:
            return self._empty_profile()

        # Classify transactions
        classified = [(t, self._classify_transaction(t)) for t in transactions]

        # Income source count: distinct counterparties for income transactions
        income_sources = set()
        income_txns_by_month: dict[str, list] = {}
        for t, cat in classified:
            if cat == "income":
                cp = t.get("counterparty", "") or t.get("description", "")
                if cp:
                    income_sources.add(cp.lower().strip())
                date_str = t.get("date", "")[:7]  # YYYY-MM
                if date_str:
                    income_txns_by_month.setdefault(date_str, []).append(t)

        income_source_count = int(_clamp(max(len(income_sources), 1), "income_source_count"))

        # Rent payment regularity
        rent_payment_regularity = self._compute_regularity(classified, "rent")

        # Utility payment regularity
        utility_payment_regularity = self._compute_regularity(classified, "utility")

        # Essential to total spend
        total_spend = 0.0
        essential_spend = 0.0
        for t, cat in classified:
            amount = abs(float(t.get("amount", 0)))
            if float(t.get("amount", 0)) < 0:  # debits
                total_spend += amount
                if cat in ("rent", "utility", "essential"):
                    essential_spend += amount
        essential_to_total_spend = (essential_spend / total_spend) if total_spend > 0 else 0.5
        essential_to_total_spend = _clamp(essential_to_total_spend, "essential_to_total_spend")

        # Subscription burden (subscriptions / monthly income)
        subscription_total = sum(abs(float(t.get("amount", 0))) for t, cat in classified if cat == "subscription")
        total_income = sum(float(t.get("amount", 0)) for t, cat in classified if cat == "income")
        months = max(len(income_txns_by_month), 1)
        monthly_income = total_income / months if total_income > 0 else 1.0
        subscription_burden = (subscription_total / months) / monthly_income if monthly_income > 0 else 0.0
        subscription_burden = _clamp(subscription_burden, "subscription_burden")

        # Balance before payday: average balance on transactions 3 days before income
        balances_before_payday = self._get_balances_before_payday(transactions, classified)
        balance_before_payday = (
            sum(balances_before_payday) / len(balances_before_payday) if balances_before_payday else 0.0
        )
        balance_before_payday = _clamp(balance_before_payday, "balance_before_payday")

        # Min balance 30d: lowest balance in last 30 days
        balances = [float(t.get("balance", 0)) for t in transactions if t.get("balance") is not None]
        min_balance_30d = min(balances) if balances else 0.0
        min_balance_30d = _clamp(min_balance_30d, "min_balance_30d")

        # Days negative balance 90d
        negative_days = sum(1 for b in balances if b < 0)
        days_negative_balance_90d = int(_clamp(negative_days, "days_negative_balance_90d"))

        # Savings rate
        avg_monthly_savings_rate = self._compute_savings_rate(classified)
        avg_monthly_savings_rate = _clamp(avg_monthly_savings_rate, "avg_monthly_savings_rate")

        # Salary credit regularity
        salary_credit_regularity = self._compute_salary_regularity(income_txns_by_month)
        salary_credit_regularity = _clamp(salary_credit_regularity, "salary_credit_regularity")

        # Dishonours (bounced payments)
        num_dishonours_12m = sum(
            1
            for t in transactions
            if any(
                kw in (t.get("description", "") or "").lower()
                for kw in ("dishonour", "bounced", "returned", "insufficient funds", "nsf")
            )
        )
        num_dishonours_12m = int(_clamp(num_dishonours_12m, "num_dishonours_12m"))

        # Days in overdraft
        days_in_overdraft_12m = sum(1 for b in balances if b < 0)
        days_in_overdraft_12m = int(_clamp(days_in_overdraft_12m, "days_in_overdraft_12m"))

        return OpenBankingProfile(
            income_source_count=income_source_count,
            rent_payment_regularity=rent_payment_regularity,
            utility_payment_regularity=utility_payment_regularity,
            essential_to_total_spend=essential_to_total_spend,
            subscription_burden=subscription_burden,
            balance_before_payday=balance_before_payday,
            min_balance_30d=min_balance_30d,
            days_negative_balance_90d=days_negative_balance_90d,
            avg_monthly_savings_rate=avg_monthly_savings_rate,
            salary_credit_regularity=salary_credit_regularity,
            num_dishonours_12m=num_dishonours_12m,
            days_in_overdraft_12m=days_in_overdraft_12m,
            raw_transactions=transactions,
        )

    def _classify_transaction(self, transaction: dict) -> str:
        """Classify a transaction as income/rent/utility/subscription/essential/other."""
        description = (transaction.get("description", "") or "").lower()
        counterparty = (transaction.get("counterparty", "") or "").lower()
        combined = f"{description} {counterparty}"
        amount = float(transaction.get("amount", 0))

        # Income: positive amounts with income keywords
        if amount > 0 and any(kw in combined for kw in _INCOME_KEYWORDS):
            return "income"

        # Rent
        if any(kw in combined for kw in _RENT_KEYWORDS):
            return "rent"

        # Utility
        if any(kw in combined for kw in _UTILITY_KEYWORDS):
            return "utility"

        # Subscription
        if any(kw in combined for kw in _SUBSCRIPTION_KEYWORDS):
            return "subscription"

        # Essential spending
        if any(kw in combined for kw in _ESSENTIAL_KEYWORDS):
            return "essential"

        return "other"

    def _compute_savings_rate(self, classified: list) -> float:
        """Compute average monthly savings rate from transactions.

        Savings rate = (total income - total spend) / total income per month.
        """
        monthly_income: dict[str, float] = {}
        monthly_spend: dict[str, float] = {}

        for t, cat in classified:
            date_str = (t.get("date", "") or "")[:7]
            if not date_str:
                continue
            amount = float(t.get("amount", 0))
            if cat == "income" and amount > 0:
                monthly_income[date_str] = monthly_income.get(date_str, 0) + amount
            elif amount < 0:
                monthly_spend[date_str] = monthly_spend.get(date_str, 0) + abs(amount)

        if not monthly_income:
            return 0.0

        rates = []
        for month, inc in monthly_income.items():
            spend = monthly_spend.get(month, 0)
            if inc > 0:
                rates.append((inc - spend) / inc)

        if not rates:
            return 0.0

        return sum(rates) / len(rates)

    def _compute_regularity(self, classified: list, category: str) -> float:
        """Compute payment regularity (0-1) for a given category.

        Regularity = number of months with payment / total months in data.
        """
        months_with_payment: set[str] = set()
        all_months: set[str] = set()

        for t, cat in classified:
            date_str = (t.get("date", "") or "")[:7]
            if date_str:
                all_months.add(date_str)
                if cat == category:
                    months_with_payment.add(date_str)

        if not all_months:
            return 0.0

        regularity = len(months_with_payment) / len(all_months)
        return _clamp(regularity, f"{category}_payment_regularity" if category != "rent" else "rent_payment_regularity")

    def _compute_salary_regularity(self, income_txns_by_month: dict) -> float:
        """Compute salary credit regularity from monthly income transactions.

        High regularity = consistent number of salary credits each month.
        """
        if not income_txns_by_month:
            return 0.0

        counts = [len(txns) for txns in income_txns_by_month.values()]
        if len(counts) < 2:
            return 1.0 if counts else 0.0

        avg = sum(counts) / len(counts)
        if avg == 0:
            return 0.0

        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        std = variance**0.5
        cv = std / avg  # coefficient of variation

        # Low CV = high regularity
        regularity = max(0.0, 1.0 - cv)
        return min(regularity, 1.0)

    def _get_balances_before_payday(self, transactions: list, classified: list) -> list:
        """Get account balances from 3 days before income transactions."""
        # Find income dates
        income_dates = set()
        for t, cat in classified:
            if cat == "income":
                date_str = t.get("date", "")[:10]
                if date_str:
                    income_dates.add(date_str)

        if not income_dates:
            return []

        # Build a date-to-balance lookup
        date_balances: dict[str, float] = {}
        for t in transactions:
            date_str = (t.get("date", "") or "")[:10]
            if date_str and t.get("balance") is not None:
                date_balances[date_str] = float(t["balance"])

        # Look up balances 3 days before each income date
        result = []
        for d_str in income_dates:
            try:
                d = datetime.strptime(d_str, "%Y-%m-%d")
                for offset in range(1, 4):
                    check = (d - timedelta(days=offset)).strftime("%Y-%m-%d")
                    if check in date_balances:
                        result.append(date_balances[check])
                        break
            except (ValueError, TypeError):
                continue

        return result

    def _empty_profile(self) -> OpenBankingProfile:
        """Return a profile with safe default values."""
        return OpenBankingProfile(
            income_source_count=1,
            rent_payment_regularity=0.0,
            utility_payment_regularity=0.0,
            essential_to_total_spend=0.5,
            subscription_burden=0.0,
            balance_before_payday=0.0,
            min_balance_30d=0.0,
            days_negative_balance_90d=0,
            avg_monthly_savings_rate=0.0,
            salary_credit_regularity=0.0,
            num_dishonours_12m=0,
            days_in_overdraft_12m=0,
            raw_transactions=[],
        )
