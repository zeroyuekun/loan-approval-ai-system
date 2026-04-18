"""Tests for the synthetic data generator producing realistic Australian distributions."""

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.data_generator import DataGenerator


@pytest.fixture(scope="module")
def generator():
    return DataGenerator()


@pytest.fixture(scope="module")
def df(generator):
    """Generate a dataset of 2000 records for distribution testing."""
    return generator.generate(num_records=2000, random_seed=42)


@pytest.fixture(scope="module")
def reject_labels(generator, df):
    """Access reject inference labels after generation."""
    return generator.reject_inference_labels


class TestDataGenerator:
    # TODO: test with empty dataframe (num_records=0)

    def test_generates_correct_number_of_records(self, df):
        assert len(df) == 2000

    def test_has_all_expected_columns(self, df):
        expected_columns = [
            "annual_income",
            "credit_score",
            "loan_amount",
            "loan_term_months",
            "debt_to_income",
            "employment_length",
            "purpose",
            "home_ownership",
            "has_cosigner",
            "property_value",
            "deposit_amount",
            "monthly_expenses",
            "existing_credit_card_limit",
            "number_of_dependants",
            "employment_type",
            "applicant_type",
            "has_hecs",
            "has_bankruptcy",
            "state",
            "application_quarter",
            "rba_cash_rate",
            "unemployment_rate",
            "property_growth_12m",
            "consumer_confidence",
            "num_credit_enquiries_6m",
            "worst_arrears_months",
            "num_defaults_5yr",
            "credit_history_months",
            "total_open_accounts",
            "num_bnpl_accounts",
            "is_existing_customer",
            "savings_balance",
            "salary_credit_regularity",
            "num_dishonours_12m",
            "avg_monthly_savings_rate",
            "days_in_overdraft_12m",
            "is_fraud_signal",
            "income_verification_gap",
            "address_tenure_months",
            "document_consistency_score",
            "approved",
            "default_probability",
            # Webscraping enhancement features
            "sa3_region",
            "sa3_name",
            "industry_anzsic",
            "help_repayment_monthly",
            # Underwriter-internal features exposed to the model
            "hem_benchmark",
            "hem_gap",
            "lmi_premium",
            "effective_loan_amount",
        ]
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"
        assert len(df.columns) >= 46

    def test_approval_rate_in_realistic_range(self, df):
        approval_rate = df["approved"].mean()
        assert 0.50 <= approval_rate <= 0.75, f"Approval rate {approval_rate:.2%} outside expected 50-75% range"

    def test_default_probability_in_realistic_range(self, df):
        mean_default = df["default_probability"].mean()
        # Range widened to 2-10% after SA3 sub-state property variation introduced
        # more extreme LVR scenarios (inner-city vs outer suburban price differences)
        assert 0.02 <= mean_default <= 0.10, f"Mean default probability {mean_default:.3f} outside expected 2-10% range"

    def test_credit_scores_in_valid_range(self, df):
        assert df["credit_score"].min() >= 300
        assert df["credit_score"].max() <= 1200

    def test_income_in_valid_range(self, df):
        assert df["annual_income"].min() >= 30000
        assert df["annual_income"].max() <= 600000

    def test_state_distribution_matches_population(self, df):
        state_counts = df["state"].value_counts(normalize=True)
        # NSW should be the largest state (population-weighted)
        assert state_counts.index[0] == "NSW", f"Expected NSW as largest, got {state_counts.index[0]}"
        # NSW should be roughly 30-38%
        assert 0.25 <= state_counts["NSW"] <= 0.42

    def test_employment_type_distribution(self, df):
        emp_counts = df["employment_type"].value_counts(normalize=True)
        # Permanent should be the most common
        assert emp_counts.index[0] == "payg_permanent", (
            f"Expected payg_permanent as most common, got {emp_counts.index[0]}"
        )
        assert emp_counts["payg_permanent"] >= 0.50

    def test_bureau_features_correlated_with_credit(self, df):
        # Low credit score borrowers should have more enquiries on average
        low_credit = df[df["credit_score"] < 750]
        high_credit = df[df["credit_score"] >= 900]
        if len(low_credit) > 10 and len(high_credit) > 10:
            assert low_credit["num_credit_enquiries_6m"].mean() > high_credit["num_credit_enquiries_6m"].mean()

    def test_behavioural_features_nan_for_non_customers(self, df):
        non_customers = df[df["is_existing_customer"] == 0]
        assert non_customers["savings_balance"].isna().all(), "Non-existing customers should have NaN savings_balance"
        assert non_customers["salary_credit_regularity"].isna().all()
        assert non_customers["num_dishonours_12m"].isna().all()

    def test_macro_variables_in_valid_range(self, df):
        assert df["rba_cash_rate"].min() >= 3.0
        assert df["rba_cash_rate"].max() <= 5.0
        assert df["unemployment_rate"].min() >= 2.0
        assert df["unemployment_rate"].max() <= 6.0
        assert df["consumer_confidence"].min() >= 70
        assert df["consumer_confidence"].max() <= 110

    def test_fraud_rate_approximately_2_percent(self, df):
        fraud_rate = df["is_fraud_signal"].mean()
        assert 0.005 <= fraud_rate <= 0.05, f"Fraud rate {fraud_rate:.3f} outside expected 0.5-5% range"

    def test_reject_inference_labels_available(self, reject_labels):
        assert reject_labels is not None
        # Should have labels for denied applications
        non_null = reject_labels.dropna()
        assert len(non_null) > 0, "Reject inference labels should have non-null values for denied apps"
        # Values should be 0 or 1
        assert set(non_null.unique()).issubset({0, 1})

    def test_reproducible_with_same_seed(self, generator):
        df1 = generator.generate(num_records=100, random_seed=123)
        df2 = generator.generate(num_records=100, random_seed=123)
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_with_different_seed(self, generator):
        df1 = generator.generate(num_records=100, random_seed=123)
        df2 = generator.generate(num_records=100, random_seed=456)
        # Approval columns should differ
        assert not (df1["approved"] == df2["approved"]).all()

    # ── Data realism tests ─────────────────────────────────────────────

    def test_bureau_missing_for_non_customers(self, df):
        """Non-existing customers should have some NaN in bureau columns."""
        non_existing = df[df["is_existing_customer"] == 0]
        if len(non_existing) < 10:
            pytest.skip("Not enough non-existing customers")
        # At least one bureau column should have some NaN
        bureau_cols = ["num_credit_enquiries_6m", "worst_arrears_months", "num_defaults_5yr", "total_open_accounts"]
        any_missing = any(non_existing[col].isna().any() for col in bureau_cols)
        assert any_missing, "Bureau columns should have some NaN for non-existing customers"

    def test_mnar_missing_correlated_with_credit(self, df):
        """Low credit applicants should have higher missing rates than high credit."""
        low_credit = df[df["credit_score"] < 750]
        high_credit = df[df["credit_score"] >= 900]
        if len(low_credit) < 20 or len(high_credit) < 20:
            pytest.skip("Not enough data in credit groups")
        low_miss = low_credit["monthly_expenses"].isna().mean()
        high_miss = high_credit["monthly_expenses"].isna().mean()
        # Low credit should have equal or higher missing rate
        assert low_miss >= high_miss * 0.8, (
            f"MNAR expected: low credit missing {low_miss:.2%} should be >= high credit missing {high_miss:.2%}"
        )

    def test_label_noise_reduces_approval_rate(self, generator):
        """Approval rate with label noise should be lower than without."""
        df_no_noise = generator.generate(num_records=2000, random_seed=42, label_noise_rate=0.0)
        df_with_noise = generator.generate(num_records=2000, random_seed=42, label_noise_rate=0.05)
        assert df_with_noise["approved"].mean() < df_no_noise["approved"].mean()

    def test_thin_file_segment_exists(self, df):
        """Some applicants should have short credit history (thin-file)."""
        thin_file = df[df["credit_history_months"] < 36]
        assert len(thin_file) > 0, "Should have thin-file applicants (credit_history < 36 months)"

    def test_seasonal_quarter_distribution(self, generator):
        """Q4 quarters should have more records than Q2 (seasonal weighting)."""
        df_large = generator.generate(num_records=5000, random_seed=42)
        q_counts = df_large["application_quarter"].value_counts()
        q4_total = sum(v for k, v in q_counts.items() if k.endswith("Q4"))
        q2_total = sum(v for k, v in q_counts.items() if k.endswith("Q2"))
        assert q4_total > q2_total, f"Q4 total ({q4_total}) should exceed Q2 total ({q2_total})"


class TestRealWorldDistributions:
    """Validate data generator against real Australian statistics."""

    @pytest.fixture
    def generated_data(self, generator):
        return generator.generate(num_records=5000, random_seed=99)

    def test_approval_rate_matches_apra(self, generated_data):
        """Approval rate should be 45-70% (APRA personal loan range)."""
        approval_rate = generated_data["approved"].mean()
        assert 0.45 <= approval_rate <= 0.70, f"Approval rate {approval_rate:.1%} outside APRA range (45-70%)"

    def test_mean_income_realistic(self, generated_data):
        """Mean income for loan applicants should be $50K-$180K (applicants skew higher than ABS median due to home loan qualification requirements)."""
        mean_income = generated_data["annual_income"].mean()
        assert 50000 <= mean_income <= 180000, f"Mean income ${mean_income:,.0f} outside realistic applicant range"

    def test_credit_score_distribution(self, generated_data):
        """Mean credit score should be near Equifax average (~864)."""
        mean_score = generated_data["credit_score"].mean()
        assert 750 <= mean_score <= 950, f"Mean credit score {mean_score:.0f} outside realistic range (750-950)"

    def test_employment_type_proportions(self, generated_data):
        """Employment type proportions should roughly match ABS."""
        proportions = generated_data["employment_type"].value_counts(normalize=True)

        if "payg_permanent" in proportions:
            assert 0.50 <= proportions.get("payg_permanent", 0) <= 0.80, (
                f"Permanent employment {proportions.get('payg_permanent', 0):.1%} outside range"
            )

    def test_open_banking_features_present(self, generated_data):
        """New open banking features should be generated."""
        expected_cols = [
            "salary_credit_regularity",
            "savings_trend_3m",
            "discretionary_spend_ratio",
            "gambling_transaction_flag",
            "bnpl_active_count",
            "overdraft_frequency_90d",
            "income_verification_score",
        ]
        for col in expected_cols:
            assert col in generated_data.columns, f"Missing open banking feature: {col}"

    def test_salary_regularity_range(self, generated_data):
        """Salary regularity should be 0-1."""
        if "salary_credit_regularity" in generated_data.columns:
            valid = generated_data["salary_credit_regularity"].dropna()
            assert valid.min() >= 0, f"salary_credit_regularity min {valid.min()} < 0"
            assert valid.max() <= 1, f"salary_credit_regularity max {valid.max()} > 1"

    def test_gambling_flag_prevalence(self, generated_data):
        """Gambling flag prevalence (Roy Morgan 2025 tiered: ~16% overall with age/state multipliers)."""
        if "gambling_transaction_flag" in generated_data.columns:
            rate = generated_data["gambling_transaction_flag"].mean()
            assert 0.05 <= rate <= 0.30, f"Gambling flag rate {rate:.1%} outside expected range (5-30%)"

    def test_dti_range_realistic(self, generated_data):
        """Debt-to-income ratio should be in plausible range."""
        mean_dti = generated_data["debt_to_income"].mean()
        assert 1.0 <= mean_dti <= 6.0, f"Mean DTI {mean_dti:.2f} outside realistic range (1.0-6.0)"

    def test_loan_amount_range(self, generated_data):
        """Loan amounts should span personal and home loan ranges."""
        min_loan = generated_data["loan_amount"].min()
        max_loan = generated_data["loan_amount"].max()
        assert min_loan >= 1000, f"Min loan ${min_loan:,.0f} below $1000"
        assert max_loan <= 5_000_000, f"Max loan ${max_loan:,.0f} above $5M"

    def test_state_proportions_population_weighted(self, generated_data):
        """State proportions should be roughly population-weighted."""
        proportions = generated_data["state"].value_counts(normalize=True)
        # NSW + VIC should account for ~55-65% of applications
        nsw_vic = proportions.get("NSW", 0) + proportions.get("VIC", 0)
        assert 0.45 <= nsw_vic <= 0.70, f"NSW+VIC proportion {nsw_vic:.1%} outside expected range (45-70%)"


class TestAustralianFeatures:
    """Validate Australian-specific features: CCR, BNPL, CDR, APRA stress test."""

    @pytest.fixture
    def generated_data(self):
        from apps.ml_engine.services.data_generator import DataGenerator

        gen = DataGenerator()
        return gen.generate(num_records=3000)

    def test_ccr_late_payments_range(self, generated_data):
        assert generated_data["num_late_payments_24m"].min() >= 0
        assert generated_data["num_late_payments_24m"].max() <= 24

    def test_ccr_late_payments_correlated_with_credit(self, generated_data):
        low = generated_data[generated_data["credit_score"] < 750]["num_late_payments_24m"].mean()
        high = generated_data[generated_data["credit_score"] > 900]["num_late_payments_24m"].mean()
        if np.isnan(low) or np.isnan(high):
            pytest.skip("Not enough data in credit score ranges")
        assert low > high, f"Low credit ({low:.2f}) should have more late payments than high ({high:.2f})"

    def test_worst_arrears_categories(self, generated_data):
        valid = {0, 14, 30, 60, 90}
        actual = set(generated_data["worst_late_payment_days"].unique())
        assert actual.issubset(valid), f"Invalid arrears: {actual - valid}"

    def test_credit_utilization_range(self, generated_data):
        assert generated_data["credit_utilization_pct"].min() >= 0
        assert generated_data["credit_utilization_pct"].max() <= 1

    def test_hardship_flags_rare(self, generated_data):
        rate = (generated_data["num_hardship_flags"] > 0).mean()
        assert rate < 0.15, f"Hardship rate {rate:.1%} too high"

    def test_bnpl_limit_correlated_with_accounts(self, generated_data):
        # More BNPL accounts should correlate with higher total limits
        low_bnpl = generated_data[generated_data["bnpl_active_count"] <= 1]["bnpl_total_limit"].mean()
        high_bnpl = generated_data[generated_data["bnpl_active_count"] >= 3]["bnpl_total_limit"].mean()
        if len(generated_data[generated_data["bnpl_active_count"] >= 3]) > 10:
            assert high_bnpl > low_bnpl, (
                f"High BNPL count ({high_bnpl:.0f}) should have higher limits than low ({low_bnpl:.0f})"
            )

    def test_bnpl_utilization_range(self, generated_data):
        assert generated_data["bnpl_utilization_pct"].min() >= 0
        assert generated_data["bnpl_utilization_pct"].max() <= 1

    def test_income_source_count_reasonable(self, generated_data):
        assert generated_data["income_source_count"].min() >= 1, "Everyone should have at least 1 income source"
        assert generated_data["income_source_count"].max() <= 10, "Income sources capped at reasonable max"
        mean_sources = generated_data["income_source_count"].mean()
        assert 1.0 <= mean_sources <= 3.0, f"Mean income sources {mean_sources:.1f} outside range"

    def test_rent_regularity_nan_for_owners(self, generated_data):
        owners = generated_data[generated_data["home_ownership"] == "own"]
        if len(owners) > 0:
            nan_rate = owners["rent_payment_regularity"].isna().mean()
            assert nan_rate > 0.8, f"Owners should have NaN rent regularity, got {nan_rate:.1%} NaN"

    def test_essential_spend_ratio_range(self, generated_data):
        assert generated_data["essential_to_total_spend"].min() >= 0.20
        assert generated_data["essential_to_total_spend"].max() <= 0.90

    def test_stressed_dsr_positive_for_loans(self, generated_data):
        with_loan = generated_data[generated_data["loan_amount"] > 0]
        assert with_loan["stressed_dsr"].mean() > 0

    def test_stress_index_range(self, generated_data):
        assert generated_data["stress_index"].min() >= 0
        assert generated_data["stress_index"].max() <= 100

    def test_log_transforms_finite(self, generated_data):
        assert np.all(np.isfinite(generated_data["log_annual_income"]))
        assert np.all(np.isfinite(generated_data["log_loan_amount"]))

    def test_postcode_default_rate_range(self, generated_data):
        assert generated_data["postcode_default_rate"].min() >= 0.001
        assert generated_data["postcode_default_rate"].max() <= 0.06

    def test_industry_risk_tier_values(self, generated_data):
        valid = {"low", "medium", "high", "very_high"}
        actual = set(generated_data["industry_risk_tier"].unique())
        assert actual.issubset(valid)


class TestBehavioralRealism:
    """Validate behavioral realism enhancements to the data generator."""

    @pytest.fixture
    def generated_data(self):
        from apps.ml_engine.services.data_generator import DataGenerator

        gen = DataGenerator()
        return gen.generate(num_records=5000, random_seed=42)

    def test_round_number_distribution(self, generated_data):
        """Loan amounts should show strong round-number bias (MIT/Wharton).

        65% round to $5K, 22% to $1K pre-optimism-bias. After optimism bias
        (10-25% boost on ~27%), some $5K multiples shift to $1K multiples.
        Test: $1K-multiple rate >55% (captures both $5K and $1K rounding).
        """
        round_1k_rate = (generated_data["loan_amount"] % 1000 == 0).mean()
        assert round_1k_rate > 0.55, f"Round $1K rate {round_1k_rate:.1%} too low (expect >55%)"

    def test_new_behavioral_columns_exist(self, generated_data):
        """All 6 new behavioral columns should be present."""
        expected = [
            "application_channel",
            "optimism_bias_flag",
            "financial_literacy_score",
            "prepayment_buffer_months",
            "negative_equity_flag",
            "loan_trigger_event",
        ]
        for col in expected:
            assert col in generated_data.columns, f"Missing behavioral column: {col}"

    def test_approval_rate_still_realistic(self, generated_data):
        """Approval rate should remain in realistic range after enhancements."""
        approval_rate = generated_data["approved"].mean()
        assert 0.50 <= approval_rate <= 0.75, f"Approval rate {approval_rate:.2%} outside expected 50-75% range"

    def test_optimism_bias_rate_near_target(self, generated_data):
        """Optimism bias rate should be near 27% (Philadelphia Fed)."""
        bias_rate = generated_data["optimism_bias_flag"].mean()
        assert 0.15 <= bias_rate <= 0.40, f"Optimism bias rate {bias_rate:.2%} outside expected 15-40% range"

    def test_financial_literacy_in_valid_range(self, generated_data):
        """Financial literacy score should be between 0.05 and 0.95."""
        assert generated_data["financial_literacy_score"].between(0.05, 0.95).all(), (
            "Financial literacy scores outside valid range [0.05, 0.95]"
        )

    def test_application_channel_valid_values(self, generated_data):
        """Application channel should be one of the 4 valid values."""
        valid = {"digital", "mobile", "branch", "broker"}
        actual = set(generated_data["application_channel"].unique())
        assert actual.issubset(valid), f"Invalid application channels: {actual - valid}"

    def test_loan_trigger_event_not_empty(self, generated_data):
        """All records should have a non-empty loan trigger event."""
        assert (generated_data["loan_trigger_event"] != "").all(), "Some loan_trigger_event values are empty"

    def test_prepayment_buffer_range(self, generated_data):
        """Prepayment buffer months should be in valid range."""
        assert generated_data["prepayment_buffer_months"].min() >= 0, "Prepayment buffer cannot be negative"
        assert generated_data["prepayment_buffer_months"].max() <= 60, "Prepayment buffer exceeds 60 months cap"

    def test_negative_equity_flag_binary(self, generated_data):
        """Negative equity flag should be 0 or 1."""
        assert set(generated_data["negative_equity_flag"].unique()).issubset({0, 1})

    def test_gambling_tiered_distribution(self, generated_data):
        """Gambling spend ratio should show tiered distribution (Roy Morgan 2025)."""
        has_gambling = (generated_data["gambling_spend_ratio"].fillna(0) > 0).mean()
        # Overall gambling prevalence should be roughly 10-25% with age/state multipliers
        assert 0.05 <= has_gambling <= 0.35, f"Gambling prevalence {has_gambling:.1%} outside expected range"

    def test_home_loans_mostly_via_broker(self, generated_data):
        """Home loans should be predominantly via broker channel."""
        home_loans = generated_data[generated_data["purpose"] == "home"]
        if len(home_loans) > 50:
            broker_rate = (home_loans["application_channel"] == "broker").mean()
            assert broker_rate > 0.40, f"Home loan broker rate {broker_rate:.1%} too low (expect >40%)"

    def test_arrears_rates_match_apra(self, generated_data):
        """Arrears rates should approximate APRA Sep 2025 targets (~1.04% NPL)."""
        approved = generated_data[generated_data["approved"] == 1]
        if len(approved) > 100:
            npl = approved["actual_outcome"].isin(["arrears_90", "default"]).mean()
            # APRA Sep 2025: ~1.04% non-performing (90+ days)
            assert npl < 0.10, f"NPL rate {npl:.2%} unrealistically high"


class TestOutcomeTracking:
    """Validate outcome simulation for backtesting."""

    @pytest.fixture
    def generated_data(self):
        from apps.ml_engine.services.data_generator import DataGenerator

        gen = DataGenerator()
        return gen.generate(num_records=5000)

    def test_outcomes_exist_for_approved(self, generated_data):
        approved = generated_data[generated_data["approved"] == 1]
        assert approved["actual_outcome"].notna().mean() > 0.9, "Most approved loans should have outcomes"

    def test_outcomes_null_for_denied(self, generated_data):
        denied = generated_data[generated_data["approved"] == 0]
        if len(denied) > 0:
            nan_rate = denied["actual_outcome"].isna().mean()
            assert nan_rate > 0.9, "Denied loans should have no observable outcome"

    def test_performing_is_majority(self, generated_data):
        approved = generated_data[generated_data["approved"] == 1]
        performing = (approved["actual_outcome"] == "performing").mean()
        assert performing > 0.75, f"Performing rate {performing:.1%} too low (expect >75%)"

    def test_default_rate_realistic(self, generated_data):
        approved = generated_data[generated_data["approved"] == 1]
        default_rate = (approved["actual_outcome"] == "default").mean()
        assert default_rate < 0.05, f"Default rate {default_rate:.1%} too high (APRA target ~1.5%)"

    def test_defaults_correlated_with_credit_score(self, generated_data):
        defaults = generated_data[generated_data["actual_outcome"] == "default"]
        performing = generated_data[generated_data["actual_outcome"] == "performing"]
        if len(defaults) > 20 and len(performing) > 50:
            assert defaults["credit_score"].mean() < performing["credit_score"].mean(), (
                "Defaulters should have lower credit scores than performing loans"
            )

    def test_months_to_outcome_range(self, generated_data):
        approved = generated_data[generated_data["approved"] == 1]
        valid = approved["months_to_outcome"].dropna()
        if len(valid) > 0:
            assert valid.min() >= 1, "Months to outcome should be >= 1"
            # Log-normal default timing allows up to 36 months (RBA research)
            assert valid.max() <= 36, "Months to outcome should be <= 36"


class TestUnderwriterPolicyFeatures:
    """Validate underwriter-internal policy variables exposed as model features.

    These features (hem_benchmark, hem_gap, lmi_premium, effective_loan_amount)
    let the ML model learn the HEM-floor + LMI-capitalisation policy the
    underwriter enforces, instead of having to infer them from raw inputs.
    """

    @pytest.fixture(scope="class")
    def df(self):
        return DataGenerator().generate(num_records=3000, random_seed=7)

    def test_hem_benchmark_reasonable_range(self, df):
        # HEM lookups come from the HEM_BENCHMARKS table (couple+dependants
        # tiers). The lowest single-no-kids row is ~$1,600 and the richest
        # couple+3-kids row is under ~$6,000.
        assert df["hem_benchmark"].min() >= 1_000
        assert df["hem_benchmark"].max() <= 8_000

    def test_hem_benchmark_increases_with_dependants(self, df):
        no_deps = df[df["number_of_dependants"] == 0]["hem_benchmark"].mean()
        three_plus = df[df["number_of_dependants"] >= 3]["hem_benchmark"].mean()
        assert three_plus > no_deps, (
            f"HEM with 3+ dependants ({three_plus:.0f}) should exceed no-dependants ({no_deps:.0f})"
        )

    def test_hem_gap_equals_expenses_minus_benchmark(self, df):
        # hem_gap is computed at generation time from the RAW monthly_expenses,
        # BEFORE MNAR missingness is injected into monthly_expenses. So we
        # compare only where monthly_expenses is still observable.
        observed = df["monthly_expenses"].notna()
        diff = (df.loc[observed, "monthly_expenses"] - df.loc[observed, "hem_benchmark"]).round(2)
        assert np.allclose(df.loc[observed, "hem_gap"], diff, atol=0.02)

    def test_lmi_zero_for_non_home_loans(self, df):
        non_home = df[~df["purpose"].isin(["home", "investment"])]
        assert (non_home["lmi_premium"] == 0).all(), "Personal/car/business loans must have zero LMI"

    def test_lmi_zero_when_lvr_below_80(self, df):
        home_low_lvr = df[
            df["purpose"].isin(["home", "investment"])
            & (df["property_value"] > 0)
            & ((df["loan_amount"] / df["property_value"]) <= 0.80)
        ]
        if len(home_low_lvr) > 20:
            assert (home_low_lvr["lmi_premium"] == 0).all(), "LMI should be zero for LVR <= 80%"

    def test_lmi_positive_when_lvr_above_80(self, df):
        home_high_lvr = df[
            df["purpose"].isin(["home", "investment"])
            & (df["property_value"] > 0)
            & ((df["loan_amount"] / df["property_value"]) > 0.85)
        ]
        if len(home_high_lvr) > 20:
            positive = (home_high_lvr["lmi_premium"] > 0).mean()
            assert positive > 0.8, f"LMI should be charged for LVR>85%, got {positive:.1%} positive"

    def test_effective_loan_equals_loan_plus_lmi(self, df):
        diff = df["loan_amount"] + df["lmi_premium"]
        assert np.allclose(df["effective_loan_amount"], diff.round(2), atol=0.02)

    def test_effective_loan_never_below_loan_amount(self, df):
        assert (df["effective_loan_amount"] >= df["loan_amount"] - 0.01).all()
