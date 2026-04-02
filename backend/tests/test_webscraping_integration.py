"""Tests for webscraping data integration — SA3 geography, industry income, F6 rates, HELP debt.

These tests verify that the new data sources integrate correctly into
the DataGenerator and produce more realistic synthetic loan data.
"""

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.data_generator import DataGenerator


@pytest.fixture(scope="module")
def generator():
    return DataGenerator()


@pytest.fixture(scope="module")
def df(generator):
    """Generate a dataset of 2000 records for testing new features."""
    return generator.generate(num_records=2000, random_seed=42)


class TestSA3GeographyIntegration:
    """SA3 sub-state geography features in generated data."""

    def test_sa3_region_column_exists(self, df):
        assert "sa3_region" in df.columns

    def test_sa3_name_column_exists(self, df):
        assert "sa3_name" in df.columns

    def test_sa3_codes_are_valid(self, df):
        """SA3 codes should be 5-character strings."""
        codes = df["sa3_region"].unique()
        for code in codes:
            assert len(str(code)) == 5, f"Invalid SA3 code length: {code}"

    def test_sa3_varies_within_state(self, df):
        """NSW should have multiple different SA3 regions."""
        nsw = df[df["state"] == "NSW"]
        unique_sa3 = nsw["sa3_region"].nunique()
        assert unique_sa3 >= 3, f"NSW has only {unique_sa3} unique SA3 regions"

    def test_property_values_vary_within_state(self, df):
        """Home loan property values should show intra-state variation."""
        nsw_homes = df[(df["state"] == "NSW") & (df["purpose"] == "home")]
        if len(nsw_homes) > 10:
            cv = nsw_homes["property_value"].std() / nsw_homes["property_value"].mean()
            assert cv > 0.2, (
                f"NSW property value CV {cv:.3f} too low — SA3 variation not working"
            )

    def test_different_sa3_have_different_property_values(self, df):
        """Different SA3 regions within NSW should have different median property values."""
        nsw_homes = df[(df["state"] == "NSW") & (df["purpose"] == "home")]
        if len(nsw_homes) > 50:
            by_sa3 = nsw_homes.groupby("sa3_region")["property_value"].median()
            if len(by_sa3) >= 2:
                assert by_sa3.max() / by_sa3.min() > 1.3, (
                    "SA3 property value medians not differentiated enough"
                )


class TestIndustryIntegration:
    """ANZSIC industry assignment and income modulation."""

    def test_industry_column_exists(self, df):
        assert "industry_anzsic" in df.columns

    def test_industry_codes_are_valid(self, df):
        """All ANZSIC codes should be single uppercase letters."""
        valid_codes = set("ABCEGHIJKMNOPQS")
        for code in df["industry_anzsic"].unique():
            assert code in valid_codes, f"Invalid ANZSIC code: {code}"

    def test_industry_distribution_varies_by_state(self, df):
        """WA should have more mining (B) than NSW."""
        wa = df[df["state"] == "WA"]
        nsw = df[df["state"] == "NSW"]
        if len(wa) > 50 and len(nsw) > 50:
            wa_mining = (wa["industry_anzsic"] == "B").mean()
            nsw_mining = (nsw["industry_anzsic"] == "B").mean()
            assert wa_mining > nsw_mining, (
                f"WA mining ({wa_mining:.3f}) should exceed NSW ({nsw_mining:.3f})"
            )

    def test_act_has_more_public_admin(self, df):
        """ACT should have the highest public administration share."""
        act = df[df["state"] == "ACT"]
        if len(act) > 20:
            act_pubadmin = (act["industry_anzsic"] == "O").mean()
            assert act_pubadmin > 0.10, (
                f"ACT public admin share {act_pubadmin:.3f} too low"
            )

    def test_industry_risk_tier_correlated_with_industry(self, df):
        """Finance/healthcare should have more 'low' risk tiers than mining/construction."""
        safe = df[df["industry_anzsic"].isin(["K", "O", "P", "Q"])]
        risky = df[df["industry_anzsic"].isin(["A", "B", "E", "H"])]
        if len(safe) > 50 and len(risky) > 50:
            safe_low = (safe["industry_risk_tier"] == "low").mean()
            risky_low = (risky["industry_risk_tier"] == "low").mean()
            assert safe_low > risky_low, (
                f"Safe industries low tier ({safe_low:.3f}) should exceed "
                f"risky industries ({risky_low:.3f})"
            )


class TestHELPDebtIntegration:
    """HELP/HECS debt repayment features."""

    def test_help_repayment_column_exists(self, df):
        assert "help_repayment_monthly" in df.columns

    def test_help_repayment_zero_without_hecs(self, df):
        """Applicants without HECS should have zero HELP repayment."""
        no_hecs = df[df["has_hecs"] == 0]
        assert (no_hecs["help_repayment_monthly"] == 0).all(), (
            "Some non-HECS applicants have HELP repayment > 0"
        )

    def test_help_repayment_positive_for_high_income_hecs(self, df):
        """High-income HECS holders should have positive repayment."""
        high_income_hecs = df[(df["has_hecs"] == 1) & (df["annual_income"] > 60000)]
        if len(high_income_hecs) > 10:
            pct_positive = (high_income_hecs["help_repayment_monthly"] > 0).mean()
            assert pct_positive > 0.5, (
                f"Only {pct_positive:.1%} of high-income HECS holders have repayment"
            )

    def test_help_repayment_below_threshold_is_zero(self, df):
        """Incomes below $54,435 should have zero HELP repayment rate."""
        low_income_hecs = df[(df["has_hecs"] == 1) & (df["annual_income"] < 54000)]
        if len(low_income_hecs) > 0:
            assert (low_income_hecs["help_repayment_monthly"] == 0).all()


class TestProductRateTiering:
    """Product rate should vary by loan type."""

    def test_product_rate_column_exists(self, df):
        assert "product_rate" in df.columns
        assert "stress_test_rate" in df.columns

    def test_stress_rate_above_product_rate(self, df):
        """Stress test rate should always exceed product rate."""
        assert (df["stress_test_rate"] >= df["product_rate"]).all()

    def test_product_rate_in_realistic_range(self, df):
        """Product rates should be between 4% and 12%."""
        assert df["product_rate"].min() >= 3.0
        assert df["product_rate"].max() <= 15.0


class TestBackwardsCompatibility:
    """Verify that core distributions remain realistic after changes."""

    def test_approval_rate_unchanged(self, df):
        """Approval rate should still be in the 50-75% range."""
        rate = df["approved"].mean()
        assert 0.45 <= rate <= 0.80, f"Approval rate {rate:.2%} outside expected range"

    def test_income_range_unchanged(self, df):
        assert df["annual_income"].min() >= 30000
        assert df["annual_income"].max() <= 600000

    def test_credit_score_range_unchanged(self, df):
        assert df["credit_score"].min() >= 300
        assert df["credit_score"].max() <= 1200

    def test_state_distribution_unchanged(self, df):
        """NSW should still be the most common state."""
        top = df["state"].value_counts().index[0]
        assert top == "NSW"

    def test_record_count_unchanged(self, df):
        assert len(df) == 2000
