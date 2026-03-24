from __future__ import annotations

"""Plaid sandbox integration — US banking data patterns for lending research.

IMPORTANT: This service connects to Plaid's US sandbox to extract behavioral
patterns from banking data. The patterns inform Australian lending models but
the raw US data is NOT used directly for Australian credit decisions.

Use cases:
- Understanding transaction categorization patterns
- Studying income stability detection algorithms
- Analyzing overdraft and savings behavior patterns
- Benchmarking our derived features against Plaid's computed fields

Sandbox: sandbox.plaid.com (free, unlimited, test credentials: user_good/pass_good)
"""
import logging
import os
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PlaidBehavioralPatterns:
    """Behavioral patterns extracted from Plaid sandbox data.

    These are PATTERNS, not direct feature values. They inform how we
    compute similar features from Australian open banking data.
    """
    income_streams_detected: int
    income_regularity_score: float  # 0-1
    recurring_expense_count: int
    discretionary_spend_ratio: float  # 0-1
    overdraft_frequency_90d: int
    average_daily_balance: float
    savings_trend: str  # 'increasing', 'stable', 'decreasing'
    transaction_categories: dict  # category → count
    insights: list[str]  # Human-readable insights about patterns


# Mapping from Plaid US patterns to equivalent Australian open banking fields.
# This is the canonical reference for cross-market feature translation.
PLAID_TO_AU_FEATURE_MAP = {
    'income_streams_detected': 'income_source_count',
    'income_regularity_score': 'salary_credit_regularity',
    'recurring_expense_count': 'recurring_obligations_count',
    'discretionary_spend_ratio': 'discretionary_to_income_ratio',
    'overdraft_frequency_90d': 'days_in_overdraft_12m',
    'average_daily_balance': 'avg_account_balance',
    'savings_trend': 'avg_monthly_savings_rate',
    'transaction_categories': 'expense_category_breakdown',
}

# Plaid transaction category groups used for pattern analysis.
_INCOME_CATEGORIES = {'Transfer', 'Payroll', 'Income', 'Deposit'}
_RECURRING_CATEGORIES = {
    'Rent', 'Utilities', 'Insurance', 'Subscription',
    'Loan Payment', 'Mortgage',
}
_DISCRETIONARY_CATEGORIES = {
    'Food and Drink', 'Entertainment', 'Shopping',
    'Travel', 'Recreation',
}


class PlaidPatternsService:
    """Extracts banking behavior patterns from Plaid US sandbox.

    NOT for direct use in credit decisions — for pattern research only.
    """

    def __init__(self):
        self.timeout = httpx.Timeout(20.0, connect=5.0)
        self.client_id = os.environ.get('PLAID_CLIENT_ID', '')
        self.secret = os.environ.get('PLAID_SANDBOX_SECRET', '')
        self.base_url = 'https://sandbox.plaid.com'

    def extract_patterns(self) -> PlaidBehavioralPatterns | None:
        """Connect to Plaid sandbox, fetch test data, extract patterns.

        Uses sandbox test credentials (user_good/pass_good).
        Returns None if the API is unavailable or credentials are missing.
        """
        if not self.client_id or not self.secret:
            logger.warning('Plaid sandbox credentials not configured')
            return None

        try:
            # Step 1: Create a sandbox public token directly
            public_token = self._create_sandbox_public_token()
            if not public_token:
                return None

            # Step 2: Exchange for access token
            access_token = self._exchange_public_token(public_token)
            if not access_token:
                return None

            # Step 3: Fetch transactions
            transactions = self._get_transactions(access_token, days=90)
            if transactions is None:
                return None

            # Step 4: Analyze patterns
            income_patterns = self._analyze_income_patterns(transactions)
            expense_patterns = self._analyze_expense_patterns(transactions)
            insights = self._generate_insights(transactions)

            # Step 5: Compute savings trend from balance changes
            savings_trend = self._compute_savings_trend(transactions)

            # Step 6: Count overdraft events (negative balances)
            overdraft_count = sum(
                1 for t in transactions
                if t.get('amount', 0) < 0
                and t.get('category', [''])[0] == 'Bank Fees'
            )

            # Step 7: Compute average daily balance proxy from transactions
            total_amounts = [t.get('amount', 0) for t in transactions]
            avg_balance = abs(sum(total_amounts) / max(len(total_amounts), 1))

            # Build category counts
            category_counts: dict[str, int] = {}
            for txn in transactions:
                cats = txn.get('category', [])
                primary_cat = cats[0] if cats else 'Uncategorized'
                category_counts[primary_cat] = category_counts.get(primary_cat, 0) + 1

            return PlaidBehavioralPatterns(
                income_streams_detected=income_patterns.get('stream_count', 0),
                income_regularity_score=income_patterns.get('regularity_score', 0.0),
                recurring_expense_count=expense_patterns.get('recurring_count', 0),
                discretionary_spend_ratio=expense_patterns.get('discretionary_ratio', 0.0),
                overdraft_frequency_90d=overdraft_count,
                average_daily_balance=avg_balance,
                savings_trend=savings_trend,
                transaction_categories=category_counts,
                insights=insights,
            )
        except Exception:
            logger.exception('Failed to extract patterns from Plaid sandbox')
            return None

    def _create_link_token(self) -> str | None:
        """Create a Plaid Link token for sandbox."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f'{self.base_url}/link/token/create',
                    json={
                        'client_id': self.client_id,
                        'secret': self.secret,
                        'user': {'client_user_id': 'pattern-research'},
                        'client_name': 'Loan Approval AI',
                        'products': ['transactions'],
                        'country_codes': ['US'],
                        'language': 'en',
                    },
                )
                response.raise_for_status()
                return response.json().get('link_token')
        except Exception:
            logger.exception('Failed to create Plaid link token')
            return None

    def _create_sandbox_public_token(self) -> str | None:
        """Create a sandbox public token directly (sandbox-only endpoint)."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f'{self.base_url}/sandbox/public_token/create',
                    json={
                        'client_id': self.client_id,
                        'secret': self.secret,
                        'institution_id': 'ins_109508',
                        'initial_products': ['transactions'],
                    },
                )
                response.raise_for_status()
                return response.json().get('public_token')
        except Exception:
            logger.exception('Failed to create Plaid sandbox public token')
            return None

    def _exchange_public_token(self, public_token: str) -> str | None:
        """Exchange public token for access token."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f'{self.base_url}/item/public_token/exchange',
                    json={
                        'client_id': self.client_id,
                        'secret': self.secret,
                        'public_token': public_token,
                    },
                )
                response.raise_for_status()
                return response.json().get('access_token')
        except Exception:
            logger.exception('Failed to exchange Plaid public token')
            return None

    def _get_transactions(self, access_token: str, days: int = 90) -> list | None:
        """Fetch transactions from sandbox account."""
        end_date = datetime.utcnow().strftime('%Y-%m-%d')
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f'{self.base_url}/transactions/get',
                    json={
                        'client_id': self.client_id,
                        'secret': self.secret,
                        'access_token': access_token,
                        'start_date': start_date,
                        'end_date': end_date,
                        'options': {'count': 500, 'offset': 0},
                    },
                )
                response.raise_for_status()
                return response.json().get('transactions', [])
        except Exception:
            logger.exception('Failed to fetch Plaid transactions')
            return None

    def _analyze_income_patterns(self, transactions: list) -> dict:
        """Analyze income regularity from transaction patterns.

        Detects number of distinct income streams and how regular they are
        (e.g., bi-weekly payroll vs. irregular freelance deposits).
        """
        income_txns = [
            t for t in transactions
            if t.get('amount', 0) < 0  # Plaid: negative = income
            and any(
                cat in _INCOME_CATEGORIES
                for cat in t.get('category', [])
            )
        ]

        if not income_txns:
            return {'stream_count': 0, 'regularity_score': 0.0}

        # Group income by merchant/name to count distinct streams
        income_sources: dict[str, list[float]] = {}
        for txn in income_txns:
            source = txn.get('name', txn.get('merchant_name', 'unknown'))
            income_sources.setdefault(source, []).append(abs(txn['amount']))

        stream_count = len(income_sources)

        # Regularity: ratio of income transactions to expected bi-weekly count (6-7 over 90d)
        expected_biweekly = 6.5
        actual_count = len(income_txns)
        regularity_score = min(1.0, actual_count / max(expected_biweekly, 1))

        return {
            'stream_count': stream_count,
            'regularity_score': round(regularity_score, 2),
        }

    def _analyze_expense_patterns(self, transactions: list) -> dict:
        """Analyze expense categorization and discretionary spending.

        Separates recurring (rent, utilities, subscriptions) from
        discretionary (dining, entertainment, shopping) spending.
        """
        expense_txns = [
            t for t in transactions
            if t.get('amount', 0) > 0  # Plaid: positive = expense
        ]

        if not expense_txns:
            return {'recurring_count': 0, 'discretionary_ratio': 0.0}

        recurring_count = 0
        discretionary_total = 0.0
        total_expenses = 0.0

        for txn in expense_txns:
            amount = txn.get('amount', 0)
            total_expenses += amount
            categories = set(txn.get('category', []))

            if categories & _RECURRING_CATEGORIES:
                recurring_count += 1
            if categories & _DISCRETIONARY_CATEGORIES:
                discretionary_total += amount

        discretionary_ratio = (
            discretionary_total / total_expenses
            if total_expenses > 0
            else 0.0
        )
        discretionary_ratio = min(1.0, max(0.0, discretionary_ratio))

        return {
            'recurring_count': recurring_count,
            'discretionary_ratio': round(discretionary_ratio, 2),
        }

    def _generate_insights(self, transactions: list) -> list[str]:
        """Generate human-readable insights about detected patterns.

        These insights inform how we should compute similar features
        from Australian banking data.
        """
        if not transactions:
            return ['No transactions available for analysis.']

        insights = []

        # Income insights
        income_patterns = self._analyze_income_patterns(transactions)
        stream_count = income_patterns.get('stream_count', 0)
        regularity = income_patterns.get('regularity_score', 0.0)

        if stream_count >= 2:
            insights.append(
                f'Multiple income streams detected ({stream_count}). '
                'AU equivalent: income_source_count from CDR bank feeds.'
            )
        if regularity >= 0.8:
            insights.append(
                'High income regularity detected. '
                'AU equivalent: salary_credit_regularity from open banking.'
            )
        elif regularity < 0.4:
            insights.append(
                'Irregular income pattern detected — possible gig/freelance. '
                'AU equivalent: low salary_credit_regularity flag.'
            )

        # Expense insights
        expense_patterns = self._analyze_expense_patterns(transactions)
        disc_ratio = expense_patterns.get('discretionary_ratio', 0.0)

        if disc_ratio > 0.5:
            insights.append(
                f'High discretionary spending ratio ({disc_ratio:.0%}). '
                'AU equivalent: elevated discretionary_to_income_ratio.'
            )

        # Transaction volume insight
        insights.append(
            f'Total transactions analyzed: {len(transactions)} over 90 days. '
            'Pattern density sufficient for behavioral scoring.'
        )

        return insights

    def _compute_savings_trend(self, transactions: list) -> str:
        """Compute savings trend from transaction flow over the period.

        Splits the 90-day period into thirds and compares net flow.
        """
        if not transactions:
            return 'stable'

        # Sort by date
        dated_txns = [
            t for t in transactions if t.get('date')
        ]
        if len(dated_txns) < 6:
            return 'stable'

        dated_txns.sort(key=lambda t: t['date'])

        # Split into thirds
        third = len(dated_txns) // 3
        if third == 0:
            return 'stable'

        def net_flow(txns: list) -> float:
            # Plaid: negative amount = income, positive = expense
            return sum(-t.get('amount', 0) for t in txns)

        early_flow = net_flow(dated_txns[:third])
        late_flow = net_flow(dated_txns[-third:])

        if late_flow > early_flow * 1.1:
            return 'increasing'
        elif late_flow < early_flow * 0.9:
            return 'decreasing'
        return 'stable'

    def compare_to_au_features(self, patterns: PlaidBehavioralPatterns) -> dict:
        """Map Plaid-derived patterns to equivalent Australian open banking features.

        Returns mapping: {plaid_pattern: au_equivalent_field}
        e.g. {'income_streams_detected': 'income_source_count',
               'overdraft_frequency_90d': 'days_in_overdraft_12m'}
        """
        mapping = dict(PLAID_TO_AU_FEATURE_MAP)

        # Add pattern-specific context based on actual values
        mapping['_context'] = {
            'income_streams_detected': (
                f'{patterns.income_streams_detected} US streams → '
                'map to CDR account count with regular credits'
            ),
            'income_regularity_score': (
                f'{patterns.income_regularity_score:.2f} regularity → '
                'equivalent to salary_credit_regularity from CDR feeds'
            ),
            'overdraft_frequency_90d': (
                f'{patterns.overdraft_frequency_90d} overdraft events → '
                'scale to 12m for days_in_overdraft_12m comparison'
            ),
            'savings_trend': (
                f'{patterns.savings_trend} trend → '
                'compute avg_monthly_savings_rate direction from CDR'
            ),
        }

        return mapping
