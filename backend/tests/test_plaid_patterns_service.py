"""Tests for the Plaid sandbox patterns service.

All HTTP calls are mocked — no real API calls are made.
"""

import httpx
import pytest
from dataclasses import fields
from unittest.mock import patch, MagicMock

from apps.ml_engine.services.plaid_patterns_service import (
    PlaidBehavioralPatterns,
    PlaidPatternsService,
    PLAID_TO_AU_FEATURE_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    """PlaidPatternsService with fake credentials."""
    with patch.dict('os.environ', {
        'PLAID_CLIENT_ID': 'test-client-id',
        'PLAID_SANDBOX_SECRET': 'test-secret',
    }):
        yield PlaidPatternsService()


@pytest.fixture
def sample_transactions():
    """Sample Plaid-format transactions for pattern analysis."""
    return [
        # Income transactions (negative amounts in Plaid)
        {
            'amount': -3500.00,
            'date': '2025-12-01',
            'name': 'ACME Corp Payroll',
            'merchant_name': 'ACME Corp',
            'category': ['Transfer', 'Payroll'],
        },
        {
            'amount': -3500.00,
            'date': '2025-12-15',
            'name': 'ACME Corp Payroll',
            'merchant_name': 'ACME Corp',
            'category': ['Transfer', 'Payroll'],
        },
        {
            'amount': -500.00,
            'date': '2025-12-10',
            'name': 'Freelance Payment',
            'merchant_name': 'Client XYZ',
            'category': ['Transfer', 'Income'],
        },
        # Recurring expenses (positive amounts in Plaid)
        {
            'amount': 1800.00,
            'date': '2025-12-01',
            'name': 'Rent Payment',
            'category': ['Rent'],
        },
        {
            'amount': 150.00,
            'date': '2025-12-05',
            'name': 'Electric Company',
            'category': ['Utilities'],
        },
        {
            'amount': 12.99,
            'date': '2025-12-07',
            'name': 'Netflix',
            'category': ['Subscription'],
        },
        # Discretionary expenses
        {
            'amount': 85.00,
            'date': '2025-12-08',
            'name': 'Restaurant',
            'category': ['Food and Drink'],
        },
        {
            'amount': 200.00,
            'date': '2025-12-12',
            'name': 'Department Store',
            'category': ['Shopping'],
        },
        {
            'amount': 45.00,
            'date': '2025-12-14',
            'name': 'Cinema',
            'category': ['Entertainment'],
        },
        # Overdraft fee
        {
            'amount': -35.00,
            'date': '2025-12-20',
            'name': 'Overdraft Fee',
            'category': ['Bank Fees'],
        },
    ]


@pytest.fixture
def sample_patterns():
    """A complete PlaidBehavioralPatterns instance."""
    return PlaidBehavioralPatterns(
        income_streams_detected=2,
        income_regularity_score=0.75,
        recurring_expense_count=3,
        discretionary_spend_ratio=0.35,
        overdraft_frequency_90d=1,
        average_daily_balance=4500.0,
        savings_trend='stable',
        transaction_categories={
            'Transfer': 3,
            'Rent': 1,
            'Utilities': 1,
            'Subscription': 1,
            'Food and Drink': 1,
            'Shopping': 1,
            'Entertainment': 1,
            'Bank Fees': 1,
        },
        insights=['Test insight'],
    )


# ---------------------------------------------------------------------------
# Test PlaidBehavioralPatterns dataclass
# ---------------------------------------------------------------------------

class TestPlaidBehavioralPatterns:
    """Verify the PlaidBehavioralPatterns dataclass has all expected fields."""

    def test_has_all_expected_fields(self):
        expected_fields = {
            'income_streams_detected',
            'income_regularity_score',
            'recurring_expense_count',
            'discretionary_spend_ratio',
            'overdraft_frequency_90d',
            'average_daily_balance',
            'savings_trend',
            'transaction_categories',
            'insights',
        }
        actual_fields = {f.name for f in fields(PlaidBehavioralPatterns)}
        assert actual_fields == expected_fields

    def test_field_types(self):
        """Verify field type annotations are present and correct.

        Note: with `from __future__ import annotations`, f.type returns
        string representations, not actual type objects.
        """
        field_types = {f.name: f.type for f in fields(PlaidBehavioralPatterns)}
        assert 'int' in str(field_types['income_streams_detected'])
        assert 'float' in str(field_types['income_regularity_score'])
        assert 'int' in str(field_types['recurring_expense_count'])
        assert 'float' in str(field_types['discretionary_spend_ratio'])
        assert 'int' in str(field_types['overdraft_frequency_90d'])
        assert 'float' in str(field_types['average_daily_balance'])
        assert 'str' in str(field_types['savings_trend'])
        assert 'dict' in str(field_types['transaction_categories'])
        assert 'list' in str(field_types['insights'])


# ---------------------------------------------------------------------------
# Test _analyze_income_patterns
# ---------------------------------------------------------------------------

class TestAnalyzeIncomePatterns:

    def test_detects_multiple_income_streams(self, service, sample_transactions):
        result = service._analyze_income_patterns(sample_transactions)
        assert result['stream_count'] == 2  # ACME Corp + Client XYZ

    def test_computes_regularity_score(self, service, sample_transactions):
        result = service._analyze_income_patterns(sample_transactions)
        assert 0.0 <= result['regularity_score'] <= 1.0

    def test_empty_transactions_returns_zero(self, service):
        result = service._analyze_income_patterns([])
        assert result['stream_count'] == 0
        assert result['regularity_score'] == 0.0

    def test_no_income_transactions(self, service):
        expense_only = [
            {'amount': 50.0, 'date': '2025-12-01', 'name': 'Shop', 'category': ['Shopping']},
        ]
        result = service._analyze_income_patterns(expense_only)
        assert result['stream_count'] == 0


# ---------------------------------------------------------------------------
# Test _analyze_expense_patterns
# ---------------------------------------------------------------------------

class TestAnalyzeExpensePatterns:

    def test_counts_recurring_expenses(self, service, sample_transactions):
        result = service._analyze_expense_patterns(sample_transactions)
        # Rent, Utilities, Subscription = 3 recurring
        assert result['recurring_count'] == 3

    def test_discretionary_ratio_in_range(self, service, sample_transactions):
        result = service._analyze_expense_patterns(sample_transactions)
        assert 0.0 <= result['discretionary_ratio'] <= 1.0

    def test_empty_transactions(self, service):
        result = service._analyze_expense_patterns([])
        assert result['recurring_count'] == 0
        assert result['discretionary_ratio'] == 0.0

    def test_only_discretionary(self, service):
        txns = [
            {'amount': 100.0, 'date': '2025-12-01', 'name': 'Restaurant', 'category': ['Food and Drink']},
            {'amount': 50.0, 'date': '2025-12-02', 'name': 'Movie', 'category': ['Entertainment']},
        ]
        result = service._analyze_expense_patterns(txns)
        assert result['recurring_count'] == 0
        assert result['discretionary_ratio'] == 1.0


# ---------------------------------------------------------------------------
# Test compare_to_au_features
# ---------------------------------------------------------------------------

class TestCompareToAuFeatures:

    def test_mapping_is_complete(self, service, sample_patterns):
        mapping = service.compare_to_au_features(sample_patterns)
        # All PLAID_TO_AU_FEATURE_MAP keys must be present
        for key in PLAID_TO_AU_FEATURE_MAP:
            assert key in mapping, f'Missing mapping for {key}'

    def test_mapping_has_context(self, service, sample_patterns):
        mapping = service.compare_to_au_features(sample_patterns)
        assert '_context' in mapping
        assert 'income_streams_detected' in mapping['_context']
        assert 'overdraft_frequency_90d' in mapping['_context']

    def test_au_field_names_are_strings(self, service, sample_patterns):
        mapping = service.compare_to_au_features(sample_patterns)
        for key, value in mapping.items():
            if key != '_context':
                assert isinstance(value, str), f'{key} mapping should be a string'


# ---------------------------------------------------------------------------
# Test extract_patterns
# ---------------------------------------------------------------------------

class TestExtractPatterns:

    def test_returns_none_when_no_credentials(self):
        """extract_patterns returns None when API credentials are missing."""
        with patch.dict('os.environ', {
            'PLAID_CLIENT_ID': '',
            'PLAID_SANDBOX_SECRET': '',
        }, clear=False):
            svc = PlaidPatternsService()
            result = svc.extract_patterns()
            assert result is None

    def test_returns_none_when_sandbox_token_fails(self, service):
        """extract_patterns returns None when sandbox API is unavailable."""
        with patch('httpx.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.ConnectError('Connection refused')
            mock_client_cls.return_value = mock_client

            result = service.extract_patterns()
            assert result is None

    def test_returns_patterns_on_success(self, service, sample_transactions):
        """extract_patterns returns PlaidBehavioralPatterns when API succeeds."""
        with patch.object(service, '_create_sandbox_public_token', return_value='test-public-token'), \
             patch.object(service, '_exchange_public_token', return_value='test-access-token'), \
             patch.object(service, '_get_transactions', return_value=sample_transactions):

            result = service.extract_patterns()
            assert result is not None
            assert isinstance(result, PlaidBehavioralPatterns)
            assert result.income_streams_detected >= 1
            assert 0.0 <= result.income_regularity_score <= 1.0
            assert 0.0 <= result.discretionary_spend_ratio <= 1.0
            assert result.savings_trend in ('increasing', 'stable', 'decreasing')
            assert isinstance(result.transaction_categories, dict)
            assert len(result.insights) > 0


# ---------------------------------------------------------------------------
# Test _generate_insights
# ---------------------------------------------------------------------------

class TestGenerateInsights:

    def test_returns_non_empty_list(self, service, sample_transactions):
        insights = service._generate_insights(sample_transactions)
        assert isinstance(insights, list)
        assert len(insights) > 0

    def test_insights_are_strings(self, service, sample_transactions):
        insights = service._generate_insights(sample_transactions)
        for insight in insights:
            assert isinstance(insight, str)

    def test_empty_transactions_gives_insight(self, service):
        insights = service._generate_insights([])
        assert len(insights) >= 1
        assert 'No transactions' in insights[0]

    def test_mentions_au_equivalents(self, service, sample_transactions):
        insights = service._generate_insights(sample_transactions)
        # At least one insight should reference Australian equivalents
        au_refs = [i for i in insights if 'AU equivalent' in i or 'CDR' in i or 'open banking' in i]
        assert len(au_refs) > 0, 'Insights should reference AU equivalents'
