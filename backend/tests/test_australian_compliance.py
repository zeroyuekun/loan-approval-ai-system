"""Tests for Australian regulatory compliance: APRA, ASIC, NCCP, CCR, Banking Code 2025."""
import pytest
import numpy as np


class TestAPRAServiceabilityBuffer:
    """APRA mandates 3% interest rate buffer on all new housing loans."""

    def test_buffer_rate_is_3_percent(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        assert gen.ASSESSMENT_BUFFER == 0.03, f'APRA buffer should be 3%, got {gen.ASSESSMENT_BUFFER}'

    def test_stressed_repayment_higher_than_normal(self):
        loan = 500000
        term = 360
        normal_rate = 0.065 / 12
        stressed_rate = 0.095 / 12
        normal_pmt = loan * (normal_rate * (1 + normal_rate)**term) / ((1 + normal_rate)**term - 1)
        stressed_pmt = loan * (stressed_rate * (1 + stressed_rate)**term) / ((1 + stressed_rate)**term - 1)
        assert stressed_pmt > normal_pmt * 1.15, \
            f'Stressed ${stressed_pmt:,.0f} should be >15% above normal ${normal_pmt:,.0f}'


class TestCCRCompliance:
    """Comprehensive Credit Reporting compliance (mandatory since 2018)."""

    def test_late_payment_window_is_24_months(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        df = gen.generate(num_records=1000)
        if 'num_late_payments_24m' in df.columns:
            assert df['num_late_payments_24m'].max() <= 24, \
                'Late payments cannot exceed 24-month CCR window'

    def test_arrears_categories_match_ccr(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        df = gen.generate(num_records=1000)
        if 'worst_late_payment_days' in df.columns:
            valid = {0, 14, 30, 60, 90}
            actual = set(df['worst_late_payment_days'].unique())
            assert actual.issubset(valid), f'Arrears must match CCR categories {valid}, got {actual}'


class TestBNPLNCCPCompliance:
    """BNPL under NCCP Act since June 2025."""

    def test_bnpl_has_credit_product_fields(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        df = gen.generate(num_records=1000)
        fields = ['bnpl_active_count', 'bnpl_total_limit', 'bnpl_utilization_pct',
                  'bnpl_late_payments_12m', 'bnpl_monthly_commitment']
        for f in fields:
            if f not in df.columns:
                pytest.skip(f'{f} not yet implemented')
        active = df[df['bnpl_active_count'] > 0]
        if len(active) > 0:
            assert active['bnpl_total_limit'].mean() > 0, \
                'Active BNPL accounts should have credit limits (NCCP requirement)'


class TestEquifaxScoreRange:
    """Equifax Australia score validation (0-1200 range)."""

    def test_score_range_0_to_1200(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        df = gen.generate(num_records=2000)
        assert df['credit_score'].min() >= 0
        assert df['credit_score'].max() <= 1200

    def test_mean_score_near_national_average(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        df = gen.generate(num_records=3000)
        mean = df['credit_score'].mean()
        assert 750 <= mean <= 950, f'Mean score {mean:.0f} too far from Equifax avg 864'


class TestHEMBenchmarks:
    """Melbourne Institute Household Expenditure Measure."""

    def test_hem_table_structure(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        assert len(gen.HEM_TABLE) == 50, f'HEM table should have 50 entries, got {len(gen.HEM_TABLE)}'

    def test_hem_increases_with_dependants(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        for bracket in ['mid', 'high']:
            for t in ['single', 'couple']:
                hem_0 = gen.HEM_TABLE.get((t, 0, bracket), 0)
                hem_2 = gen.HEM_TABLE.get((t, 2, bracket), 0)
                assert hem_2 > hem_0

    def test_hem_couples_higher_than_singles(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        for bracket in ['mid', 'high']:
            single = gen.HEM_TABLE.get(('single', 0, bracket), 0)
            couple = gen.HEM_TABLE.get(('couple', 0, bracket), 0)
            assert couple > single


class TestStateHEMMultipliers:
    """Geographic cost-of-living multipliers."""

    def test_sydney_most_expensive(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        assert gen.STATE_HEM_MULTIPLIER['NSW'] == max(gen.STATE_HEM_MULTIPLIER.values()), \
            'NSW should have highest HEM multiplier (Sydney COL)'

    def test_tasmania_lowest(self):
        from apps.ml_engine.services.data_generator import DataGenerator
        gen = DataGenerator()
        assert gen.STATE_HEM_MULTIPLIER['TAS'] == min(gen.STATE_HEM_MULTIPLIER.values()), \
            'TAS should have lowest HEM multiplier'
