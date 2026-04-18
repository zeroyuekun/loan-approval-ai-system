"""Underwriting engine — approval decisions and default-probability calibration.

Hosts the HEM expense table, serviceability-assessment thresholds, and
`compute_approval` / `calibrate_default_probability` methods. Extracted from
`DataGenerator` so the underwriting rules have a single home and can be evolved
alongside APRA APG 223 serviceability guidance without touching data generation.
"""

import numpy as np
import pandas as pd


class UnderwritingEngine:
    """Computes loan approval decisions and default probability calibration.

    Extracted from DataGenerator to isolate underwriting logic.
    Contains the HEM table, approval threshold constants, and the
    main compute_approval and calibrate_default_probability methods.
    """

    # HEM monthly benchmarks (Melbourne Institute 2025/2026, CPI-indexed)
    HEM_TABLE = {
        # Single applicants
        ("single", 0, "very_low"): 1400,
        ("single", 0, "low"): 1600,
        ("single", 0, "mid"): 2050,
        ("single", 0, "high"): 2500,
        ("single", 0, "very_high"): 3000,
        ("single", 1, "very_low"): 1900,
        ("single", 1, "low"): 2150,
        ("single", 1, "mid"): 2600,
        ("single", 1, "high"): 3050,
        ("single", 1, "very_high"): 3600,
        ("single", 2, "very_low"): 2200,
        ("single", 2, "low"): 2500,
        ("single", 2, "mid"): 3050,
        ("single", 2, "high"): 3500,
        ("single", 2, "very_high"): 4100,
        ("single", 3, "very_low"): 2500,
        ("single", 3, "low"): 2850,
        ("single", 3, "mid"): 3400,
        ("single", 3, "high"): 3900,
        ("single", 3, "very_high"): 4500,
        ("single", 4, "very_low"): 2800,
        ("single", 4, "low"): 3150,
        ("single", 4, "mid"): 3750,
        ("single", 4, "high"): 4300,
        ("single", 4, "very_high"): 4900,
        # Couple applicants
        ("couple", 0, "very_low"): 2100,
        ("couple", 0, "low"): 2400,
        ("couple", 0, "mid"): 2950,
        ("couple", 0, "high"): 3500,
        ("couple", 0, "very_high"): 4200,
        ("couple", 1, "very_low"): 2550,
        ("couple", 1, "low"): 2850,
        ("couple", 1, "mid"): 3400,
        ("couple", 1, "high"): 3950,
        ("couple", 1, "very_high"): 4700,
        ("couple", 2, "very_low"): 2900,
        ("couple", 2, "low"): 3200,
        ("couple", 2, "mid"): 3850,
        ("couple", 2, "high"): 4400,
        ("couple", 2, "very_high"): 5200,
        ("couple", 3, "very_low"): 3250,
        ("couple", 3, "low"): 3550,
        ("couple", 3, "mid"): 4200,
        ("couple", 3, "high"): 4800,
        ("couple", 3, "very_high"): 5600,
        ("couple", 4, "very_low"): 3550,
        ("couple", 4, "low"): 3900,
        ("couple", 4, "mid"): 4550,
        ("couple", 4, "high"): 5200,
        ("couple", 4, "very_high"): 6000,
    }

    # Geographic HEM multiplier (Sydney/Melbourne higher COL, regional lower)
    STATE_HEM_MULTIPLIER = {
        "NSW": 1.15,
        "VIC": 1.08,
        "QLD": 1.00,
        "WA": 1.05,
        "SA": 0.92,
        "TAS": 0.90,
        "ACT": 1.10,
        "NT": 1.02,
    }

    # Income shading by employment type (what % of income banks accept)
    INCOME_SHADING = {
        "payg_permanent": 1.00,
        "payg_casual": 0.80,  # base; <1yr: hard deny, 1-2yr: 0.80, 2yr+: 1.00
        "self_employed": 0.75,  # base; 1-2yr: 0.75, 2yr+: 0.82 (applied dynamically)
        "contract": 0.85,
    }

    # Credit card assessment: banks use 3% of limit as monthly commitment
    CREDIT_CARD_MONTHLY_RATE = 0.03

    # APRA serviceability buffer (3% above product rate)
    ASSESSMENT_BUFFER = 0.03
    FLOOR_RATE = 0.0575  # Big 4 floor rate (~5.75%)

    def __init__(self, benchmarks: dict = None):
        self._benchmarks = benchmarks

    def get_hem(self, applicant_type, dependants, annual_income, state="NSW"):
        """Look up HEM benchmark based on household composition, income, and state."""
        if annual_income < 45000:
            bracket = "very_low"
        elif annual_income < 60000:
            bracket = "low"
        elif annual_income < 120000:
            bracket = "mid"
        elif annual_income < 180000:
            bracket = "high"
        else:
            bracket = "very_high"
        dep_key = min(dependants, 4)
        base_hem = self.HEM_TABLE.get((applicant_type, dep_key, bracket), 2950)
        # Apply geographic multiplier
        state_mult = self.STATE_HEM_MULTIPLIER.get(state, 1.00)
        return int(base_hem * state_mult)

    def compute_approval(self, df, rng):
        """Apply Australian lending rules to determine approval.

        11-step assessment calibrated against APRA Sep Q 2025 data:
        - NPL rate target: ~1.04% (APRA ADI statistics)
        - 30-89 day arrears: 0.47% (APRA Sep Q 2025)
        - High-DTI (>=6) share: 6.1% of new lending (APRA Sep Q 2025)
        - High-LVR (>=80%) share: 30.8% of new lending (APRA Sep Q 2025)

        Based on APRA 2026 regulations, Big 4 bank criteria, HEM benchmarks,
        LVR/LMI thresholds, income shading, HECS/HELP deductions, and
        composite scoring.

        Realistic noise layers simulate factors the model cannot observe:
        - Hidden variables (documentation quality, savings history, employer
          reputation) that influence underwriter decisions but are not captured
          as model features.
        - Underwriter disagreement on borderline cases (~10-15%).
        - Measurement noise in self-reported income and expenses.
        - Soft policy overrides (relationship banking, branch manager discretion).

        Target: AUC 0.82-0.88 (consistent with Big 4 production scorecards).
        """
        n = len(df)
        approved = np.ones(n, dtype=int)
        hard_denied = np.zeros(n, dtype=bool)  # Track hard vs soft denials

        gross_monthly_income = df["annual_income"] / 12
        total_dti = df["debt_to_income"]
        existing_dti = df["_existing_dti"]
        credit = df["credit_score"]

        # =========================================================
        # LATENT VARIABLES (not available to the model as features)
        # These represent real-world factors banks assess from documents
        # and interviews that can't be captured in structured data.
        # =========================================================

        # Documentation quality: how clean/complete the applicant's
        # paperwork is (payslips, tax returns, bank statements).
        # Strong effect on underwriter confidence. Scale 0-1.
        doc_quality = np.clip(rng.beta(5, 2, size=n), 0, 1)
        # Self-employed have messier documentation (ATO tax returns
        # vs simple PAYG summaries)
        doc_quality[df["employment_type"] == "self_employed"] *= rng.uniform(
            0.6, 0.9, size=(df["employment_type"] == "self_employed").sum()
        )
        doc_quality[df["employment_type"] == "payg_casual"] *= rng.uniform(
            0.7, 0.95, size=(df["employment_type"] == "payg_casual").sum()
        )

        # Savings history quality: demonstrates genuine savings pattern
        # (3+ months of consistent deposits). Banks assess this from
        # statements but it's not a structured feature.
        savings_pattern = rng.beta(3, 3, size=n)

        # Employer/industry stability: banks internally rate employers
        # and industries (e.g. mining vs government vs startup).
        # Not visible in application data.
        employer_stability = rng.beta(4, 2, size=n)

        # Relationship factor: existing customers with good history
        # get benefit of the doubt on borderline cases. Simulates
        # branch manager discretion.
        relationship_bonus = rng.choice(
            [0.0, 0.03, 0.06, 0.10],
            size=n,
            p=[0.50, 0.25, 0.15, 0.10],
        )

        # =========================================================
        # STEP 1: Income shading by employment type
        # Refined per Big 4 2025 practice:
        # - Self-employed 1yr+ accepted (was 2yr pre-2025)
        #   - 1-2yr: 75%, 2yr+: 82%
        # - Casual tenure-based: <1yr deny, 1-2yr 80%, 2yr+ 100%
        # =========================================================
        income_shade = df["employment_type"].map(self.INCOME_SHADING).values
        # Self-employed with 2+ years: higher acceptance
        se_experienced = (df["employment_type"] == "self_employed") & (df["employment_length"] >= 2)
        income_shade = np.where(se_experienced, 0.82, income_shade)
        # Self-employed with 1-2 years: base rate (0.75 from INCOME_SHADING)
        # Self-employed with <1 year: lower acceptance
        se_new = (df["employment_type"] == "self_employed") & (df["employment_length"] < 1)
        income_shade = np.where(se_new, 0.65, income_shade)
        # Casual with 2+ years same employer: full income accepted
        casual_experienced = (df["employment_type"] == "payg_casual") & (df["employment_length"] >= 2)
        income_shade = np.where(casual_experienced, 1.00, income_shade)
        # Casual with <1 year: significantly lower (hard deny below)
        casual_new = (df["employment_type"] == "payg_casual") & (df["employment_length"] < 1)
        income_shade = np.where(casual_new, 0.60, income_shade)
        shaded_monthly_income = gross_monthly_income * income_shade

        # =========================================================
        # STEP 2: Hard cutoffs (auto-deny)
        # =========================================================

        # Bankruptcy: hard deny (undischarged or within 7 years)
        approved[df["has_bankruptcy"] == 1] = 0
        hard_denied[df["has_bankruptcy"] == 1] = True

        # Cash advance users with 3+ in 12 months: hard deny
        cash_adv_mask = df.get("cash_advance_count_12m", pd.Series(0, index=df.index)) >= 3
        approved[cash_adv_mask] = 0
        hard_denied[cash_adv_mask] = True

        # APRA DTI cap: hard deny at DTI >= 8.0x (no exceptions).
        # DTI 6.0-8.0x: deny UNLESS credit >= 850 AND income > $120k
        # (compensating factors -- APRA Sep Q 2025: 6.1% pass-through)
        extreme_dti_mask = total_dti >= 8.0
        approved[extreme_dti_mask] = 0
        hard_denied[extreme_dti_mask] = True

        high_dti_mask = (total_dti >= 6.0) & (total_dti < 8.0)
        high_dti_pass = high_dti_mask & (credit >= 850) & (df["annual_income"] > 120000)
        approved[high_dti_mask & ~high_dti_pass] = 0

        # Credit score floor: lowered from 650 to 580 -- non-major lenders
        # (Pepper, Liberty, Bluestone) accept 580+ for near-prime
        approved[credit < 580] = 0
        hard_denied[credit < 580] = True
        # Borderline 580-700 with high DTI: deterministic deny
        borderline_credit = (credit >= 580) & (credit < 700)
        approved[borderline_credit & (total_dti > 4.0)] = 0

        # Self-employed < 1 year ABN history (Big 4 policy change 2025:
        # CBA, Westpac, ANZ, NAB all accept 1yr+ financials)
        approved[(df["employment_type"] == "self_employed") & (df["employment_length"] < 1)] = 0

        # Casual: deny if < 6 months; 6-12 months only with credit >= 700
        casual_mask = df["employment_type"] == "payg_casual"
        approved[casual_mask & (df["employment_length"] < 0.5)] = 0
        casual_borderline = casual_mask & (df["employment_length"] >= 0.5) & (df["employment_length"] < 1)
        approved[casual_borderline & (credit < 700)] = 0

        # Contract: deny if < 6 months (was <1yr)
        approved[(df["employment_type"] == "contract") & (df["employment_length"] < 0.5)] = 0

        # PAYG permanent: deny if < 6 months; allow 6-12mo with credit >= 700
        payg_perm_mask = df["employment_type"] == "payg_permanent"
        approved[payg_perm_mask & (df["employment_length"] < 0.5)] = 0
        payg_perm_borderline = payg_perm_mask & (df["employment_length"] >= 0.5) & (df["employment_length"] < 1)
        approved[payg_perm_borderline & (credit < 700)] = 0

        # =========================================================
        # STEP 3: LVR check (home loans only)
        # =========================================================
        is_home = df["purpose"] == "home"
        property_val = df["property_value"].replace(0, np.nan)
        lvr = np.where(is_home & (property_val > 0), df["loan_amount"] / property_val, 0.0)
        # LVR > 95%: hard deny
        approved[(lvr > 0.95) & is_home] = 0
        # LVR 90-95% requires credit >= 750
        approved[(lvr > 0.90) & (lvr <= 0.95) & is_home & (credit < 750)] = 0

        # =========================================================
        # STEP 4: LMI cost for LVR > 80% (capitalized into loan)
        # =========================================================
        lmi_rate = np.where(lvr > 0.90, 0.03, np.where(lvr > 0.85, 0.02, np.where(lvr > 0.80, 0.01, 0.0)))
        lmi_premium = df["loan_amount"] * lmi_rate * is_home.astype(int)
        effective_loan_amount = df["loan_amount"] + lmi_premium

        # =========================================================
        # STEP 5: Genuine savings (home loans, LVR > 80%)
        # =========================================================
        needs_genuine_savings = is_home & (lvr > 0.80)
        min_genuine_savings = df["property_value"] * 0.05
        # Banks also assess savings pattern quality for high LVR
        weak_savings = needs_genuine_savings & (savings_pattern < 0.35)
        approved[weak_savings & (df["deposit_amount"] < min_genuine_savings * 1.2)] = 0
        approved[needs_genuine_savings & ~weak_savings & (df["deposit_amount"] < min_genuine_savings)] = 0

        # =========================================================
        # STEP 6: HEM-based expense calculation
        # =========================================================
        hem_values = np.array(
            [
                self.get_hem(at, dep, inc, st)
                for at, dep, inc, st in zip(
                    df["applicant_type"], df["number_of_dependants"], df["annual_income"], df["state"], strict=False
                )
            ]
        )
        effective_expenses = np.maximum(df["monthly_expenses"], hem_values)

        # =========================================================
        # STEP 7: Serviceability check (APRA 3% buffer)
        #
        # APRA APG 223 requires assessment at the HIGHER of:
        #   (a) customer's offered product rate + 3% buffer
        #   (b) a floor rate (typically 5.75% for Big 4)
        # Each application may have a different offered rate based
        # on their risk profile, so assessment_rate is per-application.
        # =========================================================
        # Offered product rate varies by RBA cash rate, credit quality,
        # and loan type. Big 4 pass ~80% of RBA changes through, with
        # an average spread of ~2.40% above the cash rate.
        # This makes temporal features (rba_cash_rate) actually influence
        # the label, so the model can learn genuine rate-cycle patterns.
        rate_spread = 0.024  # avg Big 4 margin above cash rate
        base_offered = np.clip(df["rba_cash_rate"].values / 100 + rate_spread, 0.055, 0.085)
        # Risk adjustments:
        #   - Excellent credit (>900): -0.3%
        #   - Fair credit (700-800): +0.5%
        #   - High LVR (>80%): +0.2%
        #   - Investment/business: +0.3%
        offered_rate = base_offered.copy()
        offered_rate = np.where(credit > 900, offered_rate - 0.003, offered_rate)
        offered_rate = np.where((credit >= 700) & (credit <= 800), offered_rate + 0.005, offered_rate)
        offered_rate = np.where(lvr > 0.80, offered_rate + 0.002, offered_rate)
        offered_rate = np.where((df["purpose"] == "business"), offered_rate + 0.003, offered_rate)

        # Per-application assessment rate: max(offered + buffer, floor)
        assessment_rate = np.maximum(offered_rate + self.ASSESSMENT_BUFFER, self.FLOOR_RATE)
        monthly_rate = assessment_rate / 12
        term_months = df["loan_term_months"]

        # New loan monthly repayment at assessment rate (P&I) using effective amount (incl LMI)
        monthly_repayment = (
            effective_loan_amount
            * monthly_rate
            * (1 + monthly_rate) ** term_months
            / ((1 + monthly_rate) ** term_months - 1)
        )

        # Australian marginal tax rates (Stage 3 tax cuts, effective 1 July 2024)
        annual_inc = df["annual_income"]
        annual_tax = np.where(
            annual_inc <= 18200,
            0,
            np.where(
                annual_inc <= 45000,
                (annual_inc - 18200) * 0.16,
                np.where(
                    annual_inc <= 135000,
                    4288 + (annual_inc - 45000) * 0.30,
                    np.where(
                        annual_inc <= 190000, 31288 + (annual_inc - 135000) * 0.37, 51638 + (annual_inc - 190000) * 0.45
                    ),
                ),
            ),
        )
        monthly_tax = annual_tax / 12

        # Existing debt servicing: existing_dti * income, serviced at ~6% over 20yr
        total_existing_debt = df["annual_income"] * existing_dti
        existing_debt_monthly = total_existing_debt * 0.0072

        # Credit card commitment: 3% of total limit
        credit_card_monthly = df["existing_credit_card_limit"] * self.CREDIT_CARD_MONTHLY_RATE

        # HECS/HELP repayment: ~3.5% of gross income (ATO compulsory).
        # Policy change 30 Sept 2025: HECS/HELP removed from DTI
        # calculations by all Big 4 banks. Still deducted from gross
        # pay (reduces net income), but NOT counted as a debt obligation
        # in serviceability assessment. Kept as informational feature only.
        np.where(
            df["has_hecs"] == 1,
            df["annual_income"] * 0.035 / 12,
            0.0,
        )

        # Monthly surplus at the assessment rate (APRA 3% buffer).
        # At the actual product rate (~6.5%), most of these loans are
        # comfortably serviceable. The APRA buffer (3% above product rate)
        # creates a theoretical stress test, not a hard boundary. Banks
        # routinely approve loans with modest shortfalls at the assessment
        # rate if the applicant has compensating strengths (strong credit,
        # stable employment, genuine savings). Only hard-deny if shortfall
        # exceeds $1,500/month at the assessment rate (serious distress).
        # NOTE: hecs_monthly excluded from surplus per Sept 2025 policy.
        monthly_surplus = (
            shaded_monthly_income
            - monthly_tax
            - effective_expenses
            - existing_debt_monthly
            - credit_card_monthly
            - monthly_repayment
        )
        # Surplus is used as a factor in composite scoring below rather
        # than a hard cutoff, except for severe shortfalls (can't service
        # even at the actual product rate, let alone the assessment rate).
        # Product rate is ~25% lower than assessment rate.
        product_rate_monthly = offered_rate / 12
        product_repayment = (
            effective_loan_amount
            * product_rate_monthly
            * (1 + product_rate_monthly) ** term_months
            / ((1 + product_rate_monthly) ** term_months - 1)
        )
        product_surplus = (
            shaded_monthly_income
            - monthly_tax
            - effective_expenses
            - existing_debt_monthly
            - credit_card_monthly
            - product_repayment
        )
        # Hard deny only if can't service at the ACTUAL product rate.
        # Even here, a modest shortfall can be offset by other income
        # sources (rental income, partner income not declared, overtime).
        approved[product_surplus < -2000] = 0

        # =========================================================
        # STEP 8: DSR check (debt service ratio)
        # Banks allow higher DSR for higher income borrowers.
        # APRA Sep Q 2025: only ~6% of new loans have DTI >= 6,
        # meaning most borrowers pass serviceability comfortably.
        # Real DSR caps are applied at the assessment rate (incl buffer),
        # but banks also consider net surplus -- if surplus is positive
        # and DSR is only modestly over the soft cap, many still approve.
        # DSR caps are assessed at the APRA buffer rate (product + 3%),
        # making them appear higher than they would at the actual rate.
        # At the actual product rate (~6.5%), the effective DSR is ~5-8%
        # lower. Banks use these generous caps because the buffer already
        # builds in conservative stress margin.
        # Caps: <$80k: 50%, $80k-$150k: 55%, >$150k: 60%
        # =========================================================
        # NOTE: hecs_monthly excluded per Sept 2025 Big 4 policy change
        total_repayments = existing_debt_monthly + credit_card_monthly + monthly_repayment
        dsr = total_repayments / gross_monthly_income
        # Real Big 4 DSR caps at assessment rate (incl APRA buffer):
        # <$80k: 50%, $80k-$150k: 55%, >$150k: 60%.
        # No Australian bank would approve 70% of gross income to debt.
        dsr_cap = np.where(df["annual_income"] > 150000, 0.60, np.where(df["annual_income"] > 80000, 0.55, 0.50))
        approved[dsr > dsr_cap] = 0

        # =========================================================
        # STEP 8b: Retirement exit strategy
        # If age + loan_term_years > 65, applicant will still be repaying
        # post-retirement. Require documented exit strategy or apply penalty.
        # APRA CPG 223 and NCCP Act responsible lending obligations.
        # =========================================================
        age = df["_age_proxy"]
        loan_term_years = df["loan_term_months"] / 12
        retirement_age_at_maturity = age + loan_term_years
        needs_exit_strategy = retirement_age_at_maturity > 65
        # Apply penalty: deny if over retirement with weak financials
        retirement_deny = (
            needs_exit_strategy
            & (credit < 800)  # no strong credit to compensate
            & (df["annual_income"] < 100000)  # not high income
        )
        approved[retirement_deny] = 0

        # =========================================================
        # STEP 9: Composite scoring with latent variables
        #
        # The composite score combines observable features (which
        # the ML model can learn) with hidden/latent variables
        # (which it cannot). This creates an irreducible error floor
        # that makes the AUC realistic (0.82-0.88 vs 0.99).
        # =========================================================
        credit_norm = np.clip((credit - 650) / 550, 0, 1)
        dti_score = np.clip(1 - (total_dti / 6.0), 0, 1)
        income_score = np.clip((df["annual_income"] - 30000) / 150000, 0, 1)
        emp_score = np.clip(df["employment_length"] / 15, 0, 1)
        surplus_score = np.clip(monthly_surplus / 3000, 0, 1)
        cosigner_bonus = df["has_cosigner"] * 0.05

        emp_type_score = np.where(
            df["employment_type"] == "payg_permanent",
            0.05,
            np.where(df["employment_type"] == "self_employed", -0.03, 0.0),
        )

        lvr_score = np.where(is_home, np.clip(1 - (lvr / 0.95), 0, 1), 0.5)

        dep_penalty = np.clip(df["number_of_dependants"] * 0.02, 0, 0.08)

        # HECS no longer penalised in composite score (Sept 2025 policy)

        # Add property count bonus for investors (they have equity as buffer)
        property_bonus = np.clip(df.get("existing_property_count", pd.Series(0, index=df.index)).values * 0.01, 0, 0.03)

        # Observable component (model can learn these patterns)
        observable_score = (
            0.12 * credit_norm
            + 0.12 * dti_score
            + 0.07 * income_score
            + 0.04 * emp_score
            + 0.10 * surplus_score
            + 0.06 * lvr_score
            + emp_type_score
            + cosigner_bonus
            - dep_penalty
            + property_bonus
        )

        # Open Banking risk signals -- reduce composite score for risky indicators
        ob_penalty = np.zeros(n)
        if "gambling_transaction_flag" in df.columns:
            ob_penalty += np.where(df["gambling_transaction_flag"] == 1, 0.12, 0.0)
        if "bnpl_active_count" in df.columns:
            ob_penalty += np.where(df["bnpl_active_count"] > 3, 0.07, 0.0)
        if "overdraft_frequency_90d" in df.columns:
            ob_penalty += np.where(df["overdraft_frequency_90d"] > 5, 0.10, 0.0)
        if "salary_credit_regularity" in df.columns:
            ob_penalty += np.where(df["salary_credit_regularity"].fillna(0.8) < 0.4, 0.08, 0.0)
        if "income_verification_score" in df.columns:
            ob_penalty += np.where(df["income_verification_score"].fillna(0.8) < 0.6, 0.12, 0.0)
        if "savings_trend_3m" in df.columns:
            ob_penalty += np.where(df["savings_trend_3m"] == "negative", 0.05, 0.0)

        # CCR / BNPL / CDR / Geographic risk penalties & bonuses
        ccr_penalty = np.zeros(n)
        if "num_late_payments_24m" in df.columns:
            ccr_penalty += np.where(df["num_late_payments_24m"] > 3, 0.15, 0.0)
        if "worst_late_payment_days" in df.columns:
            ccr_penalty += np.where(df["worst_late_payment_days"] >= 60, 0.20, 0.0)
        if "credit_utilization_pct" in df.columns:
            ccr_penalty += np.where(df["credit_utilization_pct"].fillna(0) > 0.80, 0.10, 0.0)
        if "num_hardship_flags" in df.columns:
            ccr_penalty += np.where(df["num_hardship_flags"] > 0, 0.12, 0.0)
        if "months_since_last_default" in df.columns:
            ccr_penalty += np.where(df["months_since_last_default"].fillna(999) < 12, 0.25, 0.0)
        if "stressed_dsr" in df.columns:
            ccr_penalty += np.where(df["stressed_dsr"] > 0.40, 0.15, 0.0)
        if "hem_surplus" in df.columns:
            ccr_penalty += np.where(df["hem_surplus"] < 0, 0.20, 0.0)
        if "days_negative_balance_90d" in df.columns:
            ccr_penalty += np.where(df["days_negative_balance_90d"] > 10, 0.10, 0.0)
        if "bnpl_late_payments_12m" in df.columns:
            ccr_penalty += np.where(df["bnpl_late_payments_12m"] > 2, 0.08, 0.0)
        if "stress_index" in df.columns:
            ccr_penalty += np.where(df["stress_index"] > 60, 0.12, 0.0)
        if "debt_service_coverage" in df.columns:
            ccr_penalty += np.where(df["debt_service_coverage"].fillna(10) < 1.25, 0.15, 0.0)
        if "postcode_default_rate" in df.columns:
            ccr_penalty += np.where(df["postcode_default_rate"].fillna(0) > 0.02, 0.05, 0.0)
        if "industry_risk_tier" in df.columns:
            ccr_penalty += np.where(df["industry_risk_tier"] == "very_high", 0.08, 0.0)

        # Bonuses for strong CDR signals
        ccr_bonus = np.zeros(n)
        if "rent_payment_regularity" in df.columns:
            ccr_bonus += np.where(df["rent_payment_regularity"].fillna(0) > 0.9, 0.05, 0.0)
        if "utility_payment_regularity" in df.columns:
            ccr_bonus += np.where(df["utility_payment_regularity"].fillna(0) > 0.9, 0.03, 0.0)

        # Hidden component (model CANNOT learn -- creates irreducible error)
        # These represent real factors banks assess that aren't in the
        # structured application data. Weighted heavily to create a
        # realistic AUC ceiling (real bank scorecards: 0.82-0.88).
        hidden_score = (
            0.16 * doc_quality  # documentation completeness
            + 0.14 * savings_pattern  # genuine savings behaviour
            + 0.10 * employer_stability  # employer/industry risk rating
            + relationship_bonus  # existing customer loyalty
        )

        # Phase 3A: Optimism bias penalty (assessors partially detect overconfidence)
        if "optimism_bias_flag" in df.columns:
            ob_optimism_penalty = np.where(df["optimism_bias_flag"].values == 1, 0.05, 0.0)
            observable_score -= ob_optimism_penalty

        composite = observable_score + hidden_score - ob_penalty - ccr_penalty + ccr_bonus

        # =========================================================
        # STEP 10: Underwriter variability
        #
        # Real lending decisions have human variability. Two credit
        # assessors given identical applications will disagree ~10-15%
        # of the time on borderline cases. This is well-documented in
        # banking literature (APRA thematic reviews).
        # =========================================================

        # Larger noise to simulate underwriter subjectivity and
        # unobserved case-specific factors (phone interview impression,
        # document recency, branch workload pressure)
        underwriter_noise = rng.normal(0, 0.12, size=n)

        # Final decision threshold with noise.
        # Threshold calibrated so that after all hard cutoffs + composite
        # scoring + overrides, the overall approval rate lands at ~65-75%,
        # consistent with Big 4 bank approval rates.
        final_score = composite + underwriter_noise
        # Threshold calibrated for ~58-65% approval rate (Australian market average).
        # Set to -0.08 after tightening DSR caps (50/55/60), temporal rate
        # variation, and HECS removal -- hard cutoffs now filter more
        # aggressively, so composite threshold is more lenient to keep
        # overall approval rate in the 55-62% range.
        approved[final_score < -0.08] = 0

        # =========================================================
        # STEP 11: Soft policy overrides
        #
        # In practice, some applications that pass all rules get
        # declined due to undisclosed factors (fraud signals, AML
        # flags, verbal inconsistencies during phone verification).
        # Conversely, some borderline denials get approved by senior
        # credit officers exercising discretion.
        # =========================================================

        # ~5% of approvals get overridden to denial (fraud/AML/verification
        # failures, document inconsistencies found during processing)
        approved_mask = approved == 1
        override_deny = approved_mask & (rng.random(n) < 0.05)
        approved[override_deny] = 0

        # ~8% of borderline denials get rescued by senior review
        # (relationship banking, manager discretion on good customers,
        # additional income documentation provided during processing)
        denied_mask = (approved == 0) & (final_score > 0.05) & (final_score < 0.50)
        override_approve = denied_mask & (rng.random(n) < 0.20)
        # Don't rescue bankruptcy or extreme DTI
        override_approve = override_approve & (df["has_bankruptcy"] == 0) & (total_dti < 5.5)
        approved[override_approve] = 1

        # =========================================================
        # STEP 12: Manual review + conditional approvals
        # Mirrors the orchestrator's _evaluate_conditions() logic
        # (orchestrator.py:102-173) for synthetic data realism.
        #
        # approval_type tracks HOW the loan was approved:
        #   - 'auto_approved': passed all rules automatically
        #   - 'conditional': approved with conditions attached
        #   - 'human_review': soft-denied but approved on manual review
        #   - 'denied': not approved
        #
        # conditions tracks WHAT conditions were attached, matching
        # the orchestrator's condition types:
        #   - income_verification, employment_verification,
        #     valuation_required, guarantor_needed, lmi_required
        # =========================================================

        # Initialize tracking arrays
        approval_type = np.where(approved == 1, "auto_approved", "denied")
        conditions_list = [[] for _ in range(n)]  # per-row condition lists

        # --- Conditional approvals (applied to auto-approved loans) ---
        # These mirror _evaluate_conditions() in the orchestrator

        for i in range(n):
            if approved[i] != 1:
                continue

            row_conditions = []

            # 1. Income verification gap > 15% (declared vs verified)
            #    The noise layer creates gaps -- use income_noise as proxy
            if "income_noise" in df.columns:
                gap = abs(1.0 - df.iloc[i].get("income_noise", 1.0))
            else:
                # Approximate: high-income self-employed often have gaps
                gap = (
                    0.20
                    if (df.iloc[i]["employment_type"] == "self_employed" and df.iloc[i]["annual_income"] > 80000)
                    else 0.05
                )
            if gap > 0.15:
                row_conditions.append(
                    {
                        "type": "income_verification",
                        "description": f"Income verification gap of {gap:.0%} exceeds 15% threshold.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # 2. Self-employed < 2yr tenure
            if df.iloc[i]["employment_type"] == "self_employed" and df.iloc[i]["employment_length"] < 2:
                row_conditions.append(
                    {
                        "type": "employment_verification",
                        "description": "Self-employed with less than 2 years tenure.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # 3. Home loan with high LVR (>85%) -- valuation required
            row_purpose = df.iloc[i].get("purpose", "")
            row_prop_val = df.iloc[i].get("property_value", 0)
            row_loan = df.iloc[i]["loan_amount"]
            row_lvr = row_loan / row_prop_val if row_prop_val > 0 else 0

            if row_purpose == "home" and row_lvr > 0.85:
                row_conditions.append(
                    {
                        "type": "valuation_required",
                        "description": f"High-LVR ({row_lvr:.0%}) home loan requires independent property valuation.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # 4. Large loan without strong income backing
            row_income = df.iloc[i]["annual_income"]
            if row_loan > 500000 and row_income < 100000:
                row_conditions.append(
                    {
                        "type": "guarantor_needed",
                        "description": (f"Loan ${row_loan:,.0f} exceeds $500k with income ${row_income:,.0f} < $100k."),
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # 5. LMI required (LVR 80-85%) -- condition, not denial
            if row_purpose == "home" and 0.80 < row_lvr <= 0.85:
                row_conditions.append(
                    {
                        "type": "lmi_required",
                        "description": f"LVR {row_lvr:.0%} exceeds 80% — lenders mortgage insurance required.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            if row_conditions:
                approval_type[i] = "conditional"
                conditions_list[i] = row_conditions

        # --- Manual review path -- borderline soft denials ---
        # ~20% of soft-denied applications approved by senior credit officers
        soft_denied_mask = (approved == 0) & (~hard_denied)
        manual_review_roll = rng.random(n)
        manual_approved = soft_denied_mask & (manual_review_roll < 0.20)
        approved[manual_approved] = 1
        approval_type[manual_approved] = "human_review"

        # Human-reviewed loans also get conditions based on WHY they were denied
        for i in np.where(manual_approved)[0]:
            review_conditions = []

            # Borderline credit -> require additional documentation
            if credit[i] < 700:
                review_conditions.append(
                    {
                        "type": "income_verification",
                        "description": "Manual review override — additional income verification required.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # Borderline DTI -> require expense verification
            if total_dti[i] > 4.5:
                review_conditions.append(
                    {
                        "type": "expense_verification",
                        "description": "Manual review override — detailed expense verification required.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # Short employment -> require employment letter
            if df.iloc[i]["employment_length"] < 1:
                review_conditions.append(
                    {
                        "type": "employment_verification",
                        "description": "Manual review override — employer letter required.",
                        "required": True,
                        "satisfied": False,
                        "satisfied_at": None,
                    }
                )

            # All human reviews get at least one condition
            if not review_conditions:
                review_conditions.append(
                    {
                        "type": "senior_review_noted",
                        "description": "Approved on senior credit officer discretion.",
                        "required": False,
                        "satisfied": True,
                        "satisfied_at": None,
                    }
                )

            conditions_list[i] = review_conditions

        # Flag remaining soft-denied as 'review' (sent to human queue, not approved)
        still_denied_soft = (approved == 0) & (~hard_denied)
        approval_type[still_denied_soft] = "review"

        return approved, approval_type, conditions_list

    def calibrate_default_probability(self, df, rng, resolve_default_base_rate_fn):
        """Assign realistic default probabilities calibrated to APRA/RBA data.

        Uses a MULTIPLICATIVE risk factor model (like real Basel III PD models)
        instead of additive blending, so risk factors compound realistically:
        a casual worker with high LVR AND high DTI gets a much higher PD than
        any single factor would suggest.

        Sources (2025-2026):
          - APRA ADI Statistics Sep Q 2025: NPL rate 1.04%
          - RBA Financial Stability Review 2025: 90+ day arrears 0.65%
          - S&P Lenders Mortgage Insurance: default by LVR band
          - Equifax Quarterly Credit Demand Index: default by score band
          - ABS Labour Force Survey: employment type default correlation

        Target default rates by segment (annualised PD):
          LVR <60%:     ~0.5%    | Credit 800+:     ~0.3%
          LVR 60-80%:   ~1.2%    | Credit 700-800:  ~1.0%
          LVR 80-90%:   ~2.5%    | Credit 600-700:  ~2.5%
          LVR 90%+:     ~4.5%    | Credit <600:     ~8.0%

          DTI <3:       ~0.8%    | PAYG permanent:  ~1.0%
          DTI 3-4:      ~1.5%    | Self-employed:   ~2.5%
          DTI 4-5:      ~2.8%    | Casual:          ~3.8%
          DTI 5+:       ~4.5%    | Contract:        ~2.0%
        """
        n = len(df)

        # Base PD: uses latest APRA NPL rate when benchmarks available,
        # otherwise 1.04% (APRA Sep Q 2025)
        base_pd = resolve_default_base_rate_fn()

        # --- LVR risk multiplier (continuous, exponential curve) ---
        # Calibrated so: LVR 0.5->0.5x, 0.7->1.0x, 0.85->2.2x, 0.95->4.3x
        lvr = np.where(
            df["property_value"] > 0,
            df["loan_amount"] / df["property_value"],
            0.3,
        )
        lvr_mult = np.exp(2.2 * (lvr - 0.70))  # exponential around 70% LVR pivot
        lvr_mult = np.clip(lvr_mult, 0.4, 5.0)

        # --- Credit score risk multiplier (continuous, logistic curve) ---
        # Calibrated so: 900->0.25x, 800->0.6x, 700->1.5x, 600->4.0x, 500->10x
        credit = df["credit_score"].values.astype(float)
        credit_mult = np.exp(-0.005 * (credit - 780))
        credit_mult = np.clip(credit_mult, 0.2, 10.0)

        # --- DTI risk multiplier (continuous) ---
        # Calibrated so: 1.5->0.6x, 3.0->1.0x, 4.5->2.5x, 6.0->4.5x
        dti = df["debt_to_income"].values.astype(float)
        dti_mult = np.exp(0.4 * (dti - 3.0))
        dti_mult = np.clip(dti_mult, 0.4, 6.0)

        # --- Employment type multiplier ---
        # PAYG permanent is the baseline (1.0x)
        emp_type = df["employment_type"].values
        emp_mult = np.ones(n)
        emp_mult[emp_type == "payg_permanent"] = 1.0
        emp_mult[emp_type == "contract"] = 2.0
        emp_mult[emp_type == "self_employed"] = 2.5
        emp_mult[emp_type == "payg_casual"] = 3.8

        # --- Employment tenure multiplier ---
        # Longer tenure = lower risk (protective factor)
        emp_len = df["employment_length"].values.astype(float)
        tenure_mult = np.where(
            emp_len >= 10,
            0.6,
            np.where(emp_len >= 5, 0.75, np.where(emp_len >= 2, 0.9, np.where(emp_len >= 1, 1.2, 2.0))),
        )

        # --- Dependants stress factor ---
        deps = df["number_of_dependants"].values.astype(float)
        deps_mult = 1.0 + 0.08 * deps  # each dependant adds 8% to PD

        # --- HECS drag ---
        has_hecs = df["has_hecs"].values.astype(float) if "has_hecs" in df.columns else np.zeros(n)
        hecs_mult = np.where(has_hecs == 1, 1.15, 1.0)  # 15% higher PD with HECS

        # Multiplicative model: PD = base x product(risk_factors)
        # This is how real Basel III IRB models work -- risk factors compound
        raw_pd = base_pd * lvr_mult * credit_mult * dti_mult * emp_mult * tenure_mult * deps_mult * hecs_mult

        # Bankruptcy: floor at 10% PD (very high risk, matches Equifax data)
        raw_pd[df["has_bankruptcy"] == 1] = np.maximum(raw_pd[df["has_bankruptcy"] == 1], 0.10)

        # Idiosyncratic noise (life events: divorce, illness, redundancy)
        # Log-normal preserves right skew -- most borrowers do fine, a few
        # experience severe shocks. sigma=0.5 gives realistic tail events.
        noise = rng.lognormal(mean=0.0, sigma=0.5, size=n)
        raw_pd = raw_pd * noise

        # --- Bureau risk factors (new columns from generate()) ---
        if "num_credit_enquiries_6m" in df.columns:
            enquiry_factor = np.where(
                df["num_credit_enquiries_6m"] >= 5,
                2.5,
                np.where(
                    df["num_credit_enquiries_6m"] >= 3, 1.8, np.where(df["num_credit_enquiries_6m"] >= 2, 1.3, 1.0)
                ),
            )
            raw_pd *= enquiry_factor

        if "worst_arrears_months" in df.columns:
            arrears_factor = np.where(
                df["worst_arrears_months"] >= 3,
                4.0,
                np.where(df["worst_arrears_months"] >= 2, 3.0, np.where(df["worst_arrears_months"] >= 1, 2.0, 1.0)),
            )
            raw_pd *= arrears_factor

        if "num_bnpl_accounts" in df.columns:
            bnpl_factor = np.where(df["num_bnpl_accounts"] >= 3, 1.5, np.where(df["num_bnpl_accounts"] >= 2, 1.3, 1.0))
            raw_pd *= bnpl_factor

        # Cash advance factor -- strong negative signal
        if "cash_advance_count_12m" in df.columns:
            cash_adv_factor = np.where(
                df["cash_advance_count_12m"] >= 3, 3.5, np.where(df["cash_advance_count_12m"] >= 1, 2.0, 1.0)
            )
            raw_pd *= cash_adv_factor

        # Gambling spend factor
        if "gambling_spend_ratio" in df.columns:
            gambling_factor = np.where(
                df["gambling_spend_ratio"] > 0.05, 2.5, np.where(df["gambling_spend_ratio"] > 0.02, 1.5, 1.0)
            )
            raw_pd *= gambling_factor

        # --- Behavioural risk factors (existing customers only) ---
        if "num_dishonours_12m" in df.columns:
            dishonour_factor = np.where(
                df["num_dishonours_12m"].fillna(0) >= 3,
                3.0,
                np.where(df["num_dishonours_12m"].fillna(0) >= 1, 2.0, 1.0),
            )
            raw_pd *= dishonour_factor

        if "days_in_overdraft_12m" in df.columns:
            overdraft_factor = np.where(
                df["days_in_overdraft_12m"].fillna(0) >= 30,
                2.0,
                np.where(df["days_in_overdraft_12m"].fillna(0) >= 10, 1.5, 1.0),
            )
            raw_pd *= overdraft_factor

        # --- Behavioral realism factors (Phase 3B) ---

        # Prepayment buffer (RBA RDP 2020-03)
        if "prepayment_buffer_months" in df.columns:
            buffer = df["prepayment_buffer_months"].fillna(6).values
            buffer_factor = np.where(buffer < 1, 2.32, np.where(buffer < 3, 1.5, np.where(buffer > 6, 0.33, 1.0)))
            raw_pd *= buffer_factor

        # Double-trigger interaction (RBA RDP 2020-03)
        if "negative_equity_flag" in df.columns and "prepayment_buffer_months" in df.columns:
            double_trigger = (df["negative_equity_flag"].values == 1) & (
                df["prepayment_buffer_months"].fillna(6).values < 1
            )
            raw_pd[double_trigger] *= 2.5

        # Optimism bias (Philadelphia Fed)
        if "optimism_bias_flag" in df.columns:
            raw_pd *= np.where(df["optimism_bias_flag"].values == 1, 1.7, 1.0)

        # Financial literacy (ANZ Survey)
        if "financial_literacy_score" in df.columns:
            lit = df["financial_literacy_score"].fillna(0.5).values
            lit_factor = np.where(lit < 0.4, 1.25, np.where(lit > 0.7, 0.85, 1.0))
            raw_pd *= lit_factor

        # Life event trigger risk
        if "loan_trigger_event" in df.columns:
            trigger = df["loan_trigger_event"].values
            trigger_factor = np.ones(n)
            trigger_factor[trigger == "debt_consolidation"] = 1.4
            trigger_factor[trigger == "medical"] = 1.3
            trigger_factor[trigger == "startup"] = 1.5
            trigger_factor[trigger == "refinance"] = 0.8
            trigger_factor[trigger == "vehicle_purchase"] = 0.9
            raw_pd *= trigger_factor

        # --- Macroeconomic factors ---
        if "rba_cash_rate" in df.columns:
            rate_factor = 1.0 + (df["rba_cash_rate"] - 3.5) * 0.15
            rate_factor = np.clip(rate_factor, 0.8, 1.5)
            raw_pd *= rate_factor

        if "unemployment_rate" in df.columns:
            unemp_factor = 1.0 + (df["unemployment_rate"] - 3.5) * 0.20
            unemp_factor = np.clip(unemp_factor, 0.8, 1.8)
            raw_pd *= unemp_factor

        # Clip to realistic range
        calibrated_pd = np.clip(raw_pd, 0.001, 0.60)

        return np.round(calibrated_pd, 4)
