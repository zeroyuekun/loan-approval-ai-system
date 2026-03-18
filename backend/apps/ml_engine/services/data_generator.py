import os

import numpy as np
import pandas as pd


class DataGenerator:
    """Creates synthetic loan data using Australian lending standards.

    Based on APRA regulations (2026), Big 4 bank criteria (CBA, ANZ, Westpac, NAB),
    Equifax Australia credit scoring (0-1200 scale), Melbourne Institute HEM benchmarks
    (2025/2026 CPI-indexed), LVR thresholds with LMI, genuine savings rules,
    income shading by employment type, and HECS/HELP repayment obligations.
    """

    PURPOSES = ['home', 'auto', 'education', 'personal', 'business']
    PURPOSE_WEIGHTS = [0.35, 0.20, 0.15, 0.20, 0.10]
    HOME_OWNERSHIP = ['own', 'rent', 'mortgage']
    HOME_OWNERSHIP_WEIGHTS = [0.20, 0.35, 0.45]
    EMPLOYMENT_TYPES = ['payg_permanent', 'payg_casual', 'self_employed', 'contract']
    EMPLOYMENT_TYPE_WEIGHTS = [0.55, 0.15, 0.20, 0.10]
    APPLICANT_TYPES = ['single', 'couple']
    APPLICANT_TYPE_WEIGHTS = [0.45, 0.55]

    # APRA serviceability buffer (3% above product rate)
    ASSESSMENT_BUFFER = 0.03
    BASE_RATE = 0.065  # ~6.5% average variable rate (2025/2026)
    FLOOR_RATE = 0.0575  # Big 4 floor rate (~5.75%)

    # HEM monthly benchmarks (Melbourne Institute 2025/2026, CPI-indexed)
    HEM_TABLE = {
        ('single', 0, 'low'):    1600, ('single', 0, 'mid'):    2050, ('single', 0, 'high'):   2500,
        ('single', 1, 'low'):    2150, ('single', 1, 'mid'):    2600, ('single', 1, 'high'):   3050,
        ('single', 2, 'low'):    2500, ('single', 2, 'mid'):    3050, ('single', 2, 'high'):   3500,
        ('couple', 0, 'low'):    2400, ('couple', 0, 'mid'):    2950, ('couple', 0, 'high'):   3500,
        ('couple', 1, 'low'):    2850, ('couple', 1, 'mid'):    3400, ('couple', 1, 'high'):   3950,
        ('couple', 2, 'low'):    3200, ('couple', 2, 'mid'):    3850, ('couple', 2, 'high'):   4400,
    }

    # Income shading by employment type (what % of income banks accept)
    INCOME_SHADING = {
        'payg_permanent': 1.00,
        'payg_casual': 0.80,
        'self_employed': 0.75,
        'contract': 0.85,
    }

    # Credit card assessment: banks use 3% of limit as monthly commitment
    CREDIT_CARD_MONTHLY_RATE = 0.03

    # LMI premium rates by LVR band (approximate, capitalised into loan)
    LMI_RATES = {
        (0.80, 0.85): 0.01,
        (0.85, 0.90): 0.02,
        (0.90, 0.95): 0.03,
    }

    def generate(self, num_records=10000, random_seed=42):
        """Generate synthetic loan data with Australian-realistic distributions."""
        rng = np.random.default_rng(random_seed)
        n = num_records

        # --- Demographics ---
        employment_type = rng.choice(
            self.EMPLOYMENT_TYPES, size=n, p=self.EMPLOYMENT_TYPE_WEIGHTS
        )
        applicant_type = rng.choice(
            self.APPLICANT_TYPES, size=n, p=self.APPLICANT_TYPE_WEIGHTS
        )
        number_of_dependants = rng.choice(
            [0, 1, 2, 3, 4], size=n, p=[0.35, 0.25, 0.25, 0.10, 0.05]
        )

        # --- Income (ABS median ~$65k single, ~$130k couple household) ---
        base_income = np.where(
            applicant_type == 'couple',
            rng.lognormal(mean=np.log(130000), sigma=0.40, size=n),
            rng.lognormal(mean=np.log(70000), sigma=0.50, size=n),
        ).round(2)
        annual_income = np.clip(base_income, 25000, 500000)

        employment_length = np.clip(
            rng.exponential(scale=6, size=n).astype(int), 0, 40
        )
        # Low-income applicants tend to have shorter employment
        low_income = annual_income < 50000
        employment_length[low_income] = np.clip(
            employment_length[low_income] - rng.integers(0, 3, size=low_income.sum()),
            0, 40,
        )

        purpose = rng.choice(self.PURPOSES, size=n, p=self.PURPOSE_WEIGHTS)
        is_home = purpose == 'home'

        # --- Credit score (Equifax AU 0-1200, national average ~846) ---
        # Tighter sigma (120) for Big 4 self-selecting applicants
        credit_score = np.clip(
            rng.normal(loc=846, scale=120, size=n).astype(int), 300, 1200
        )
        # Home loan applicants self-select: floor at 700
        credit_score[is_home] = np.clip(credit_score[is_home], 700, 1200)
        # All others: Big 4 pre-screening floor at 650
        credit_score[~is_home] = np.clip(credit_score[~is_home], 650, 1200)

        home_ownership = rng.choice(
            self.HOME_OWNERSHIP, size=n, p=self.HOME_OWNERSHIP_WEIGHTS
        )
        has_cosigner = rng.choice([0, 1], size=n, p=[0.92, 0.08])

        # --- Existing debt (separate from new loan) ---
        # Beta(2,6) * 1.5 gives mean ~0.375, realistic for applicants with some debt
        existing_dti = np.clip(
            rng.beta(a=2.0, b=6.0, size=n) * 1.5, 0, 1.5
        ).round(2)

        # Correlation: higher existing DTI → lower credit scores
        dti_penalty = np.clip((existing_dti - 0.3) * 80, 0, 150).astype(int)
        credit_score = np.clip(credit_score - dti_penalty, 300, 1200)
        # Re-apply purpose floors after penalty
        credit_score[is_home] = np.clip(credit_score[is_home], 700, 1200)
        credit_score[~is_home] = np.clip(credit_score[~is_home], 650, 1200)

        # --- Loan amounts: correlated with income and purpose ---
        # Home loans: capped at 4.5x income (APRA realistic)
        # Other loans: 0.05-2x income
        loan_multiplier = np.where(
            is_home,
            np.clip(rng.normal(3.2, 0.8, size=n), 1.5, 4.5),
            np.clip(rng.lognormal(mean=np.log(0.3), sigma=0.8, size=n), 0.05, 2.0),
        )
        loan_amount = (annual_income * loan_multiplier).round(2)
        loan_amount = np.clip(loan_amount, 5000, 3000000)

        # Total DTI including new loan
        new_loan_dti = loan_amount / annual_income
        debt_to_income = (existing_dti + new_loan_dti).round(2)

        # Standard Australian loan terms
        loan_term_months = np.where(
            is_home,
            rng.choice([240, 300, 360], size=n, p=[0.20, 0.35, 0.45]),
            rng.choice([12, 24, 36, 60, 84], size=n, p=[0.10, 0.15, 0.30, 0.30, 0.15]),
        )

        # --- Property value (home loans only) ---
        property_value = np.zeros(n)
        lvr_targets = np.clip(rng.normal(0.80, 0.10, size=n), 0.50, 0.98)
        property_value[is_home] = (loan_amount[is_home] / lvr_targets[is_home]).round(2)
        property_value = np.clip(property_value, 0, 5000000)

        # Deposit
        deposit_amount = np.zeros(n)
        deposit_amount[is_home] = np.maximum(
            property_value[is_home] - loan_amount[is_home], 0
        ).round(2)

        # Monthly declared expenses
        monthly_expenses = np.clip(
            rng.lognormal(mean=np.log(2500), sigma=0.4, size=n).round(2),
            800, 10000
        )

        # Credit card limits
        existing_credit_card_limit = np.where(
            rng.random(n) < 0.70,
            np.clip(
                rng.lognormal(mean=np.log(8000), sigma=0.6, size=n), 0, 50000
            ).round(2),
            0
        )

        # --- HECS/HELP debt (ATO compulsory repayment at ~3.5% of gross) ---
        # ~40% of borrowers under 55 carry HECS
        age_proxy = np.clip(18 + employment_length + rng.integers(0, 5, size=n), 18, 70)
        has_hecs = ((age_proxy < 55) & (rng.random(n) < 0.40)).astype(int)

        # --- Bankruptcy (hard disqualifier, ~3% of population) ---
        has_bankruptcy = rng.choice([0, 1], size=n, p=[0.97, 0.03])

        data = {
            'annual_income': annual_income,
            'credit_score': credit_score,
            'loan_amount': loan_amount,
            'loan_term_months': loan_term_months,
            'debt_to_income': debt_to_income,
            'employment_length': employment_length,
            'purpose': purpose,
            'home_ownership': home_ownership,
            'has_cosigner': has_cosigner,
            'property_value': property_value,
            'deposit_amount': deposit_amount,
            'monthly_expenses': monthly_expenses,
            'existing_credit_card_limit': existing_credit_card_limit,
            'number_of_dependants': number_of_dependants,
            'employment_type': employment_type,
            'applicant_type': applicant_type,
            'has_hecs': has_hecs,
            'has_bankruptcy': has_bankruptcy,
        }

        df = pd.DataFrame(data)
        # Store temporary columns for approval calculation (not model features)
        df['_existing_dti'] = existing_dti
        df['_age_proxy'] = age_proxy
        df['approved'] = self._compute_approval(df, rng)
        df.drop(columns=['_existing_dti', '_age_proxy'], inplace=True)

        return df

    def _get_hem(self, applicant_type, dependants, annual_income):
        """Look up HEM benchmark based on household composition and income."""
        if annual_income < 60000:
            bracket = 'low'
        elif annual_income < 120000:
            bracket = 'mid'
        else:
            bracket = 'high'
        dep_key = min(dependants, 2)
        return self.HEM_TABLE.get((applicant_type, dep_key, bracket), 2950)

    def _compute_approval(self, df, rng):
        """Apply Australian lending rules to determine approval.

        Full 9-step deterministic assessment based on APRA 2026 regulations,
        Big 4 bank criteria, HEM benchmarks, LVR/LMI thresholds, income shading,
        HECS/HELP deductions, and composite scoring without random noise.
        """
        n = len(df)
        approved = np.ones(n, dtype=int)

        gross_monthly_income = df['annual_income'] / 12
        total_dti = df['debt_to_income']
        existing_dti = df['_existing_dti']
        credit = df['credit_score']

        # =========================================================
        # STEP 1: Income shading by employment type
        # =========================================================
        income_shade = df['employment_type'].map(self.INCOME_SHADING).values
        shaded_monthly_income = gross_monthly_income * income_shade

        # =========================================================
        # STEP 2: Hard cutoffs (auto-deny, fully deterministic)
        # =========================================================

        # Bankruptcy: hard deny (undischarged or within 7 years)
        approved[df['has_bankruptcy'] == 1] = 0

        # APRA DTI cap: total DTI >= 6x is a hard boundary
        approved[total_dti >= 6.0] = 0

        # Credit score floor: Big 4 banks require 650+
        approved[credit < 650] = 0
        # Borderline 650-700 with high DTI: deterministic deny
        borderline_credit = (credit >= 650) & (credit < 700)
        approved[borderline_credit & (total_dti > 4.0)] = 0

        # Self-employed < 2 years ABN history
        approved[(df['employment_type'] == 'self_employed') & (df['employment_length'] < 2)] = 0

        # Casual < 1 year continuous
        approved[(df['employment_type'] == 'payg_casual') & (df['employment_length'] < 1)] = 0

        # Contract < 1 year
        approved[(df['employment_type'] == 'contract') & (df['employment_length'] < 1)] = 0

        # PAYG permanent < 6 months (modeled as < 1 year in integer years)
        approved[(df['employment_type'] == 'payg_permanent') & (df['employment_length'] < 1)] = 0

        # =========================================================
        # STEP 3: LVR check (home loans only)
        # =========================================================
        is_home = df['purpose'] == 'home'
        property_val = df['property_value'].replace(0, np.nan)
        lvr = np.where(
            is_home & (property_val > 0),
            df['loan_amount'] / property_val,
            0.0
        )
        # LVR > 95%: hard deny
        approved[(lvr > 0.95) & is_home] = 0
        # LVR 90-95% requires credit >= 750
        approved[(lvr > 0.90) & (lvr <= 0.95) & is_home & (credit < 750)] = 0

        # =========================================================
        # STEP 4: LMI cost for LVR > 80% (capitalized into loan)
        # =========================================================
        lmi_rate = np.where(
            lvr > 0.90, 0.03,
            np.where(lvr > 0.85, 0.02,
                     np.where(lvr > 0.80, 0.01, 0.0))
        )
        lmi_premium = df['loan_amount'] * lmi_rate * is_home.astype(int)
        effective_loan_amount = df['loan_amount'] + lmi_premium

        # =========================================================
        # STEP 5: Genuine savings (home loans, LVR > 80%)
        # =========================================================
        needs_genuine_savings = is_home & (lvr > 0.80)
        min_genuine_savings = df['property_value'] * 0.05
        approved[needs_genuine_savings & (df['deposit_amount'] < min_genuine_savings)] = 0

        # =========================================================
        # STEP 6: HEM-based expense calculation
        # =========================================================
        hem_values = np.array([
            self._get_hem(at, dep, inc)
            for at, dep, inc in zip(
                df['applicant_type'], df['number_of_dependants'], df['annual_income']
            )
        ])
        effective_expenses = np.maximum(df['monthly_expenses'], hem_values)

        # =========================================================
        # STEP 7: Serviceability check (APRA 3% buffer)
        # =========================================================
        assessment_rate = max(self.BASE_RATE + self.ASSESSMENT_BUFFER, self.FLOOR_RATE)
        monthly_rate = assessment_rate / 12
        term_months = df['loan_term_months']

        # New loan monthly repayment at assessment rate (P&I) using effective amount (incl LMI)
        monthly_repayment = (
            effective_loan_amount
            * monthly_rate
            * (1 + monthly_rate) ** term_months
            / ((1 + monthly_rate) ** term_months - 1)
        )

        # Australian marginal tax rates (Stage 3 tax cuts, effective 1 July 2024)
        annual_inc = df['annual_income']
        annual_tax = np.where(
            annual_inc <= 18200, 0,
            np.where(
                annual_inc <= 45000, (annual_inc - 18200) * 0.16,
                np.where(
                    annual_inc <= 135000,
                    4288 + (annual_inc - 45000) * 0.30,
                    np.where(
                        annual_inc <= 190000,
                        31288 + (annual_inc - 135000) * 0.37,
                        51638 + (annual_inc - 190000) * 0.45
                    )
                )
            )
        )
        monthly_tax = annual_tax / 12

        # Existing debt servicing: existing_dti * income, serviced at ~6% over 20yr
        total_existing_debt = df['annual_income'] * existing_dti
        existing_debt_monthly = total_existing_debt * 0.0072

        # Credit card commitment: 3% of total limit
        credit_card_monthly = df['existing_credit_card_limit'] * self.CREDIT_CARD_MONTHLY_RATE

        # HECS/HELP repayment: ~3.5% of gross income (ATO compulsory)
        hecs_monthly = np.where(
            df['has_hecs'] == 1,
            df['annual_income'] * 0.035 / 12,
            0.0,
        )

        # Monthly surplus
        monthly_surplus = (
            shaded_monthly_income
            - monthly_tax
            - effective_expenses
            - existing_debt_monthly
            - credit_card_monthly
            - hecs_monthly
            - monthly_repayment
        )
        approved[monthly_surplus < 0] = 0

        # =========================================================
        # STEP 8: DSR check (debt service ratio)
        # Banks allow higher DSR for higher income borrowers:
        # <$80k: 35%, $80k-$150k: 40%, >$150k: 45%
        # =========================================================
        total_repayments = existing_debt_monthly + credit_card_monthly + hecs_monthly + monthly_repayment
        dsr = total_repayments / gross_monthly_income
        dsr_cap = np.where(
            df['annual_income'] > 150000, 0.45,
            np.where(df['annual_income'] > 80000, 0.40, 0.35)
        )
        approved[dsr > dsr_cap] = 0

        # =========================================================
        # STEP 9: Composite scoring for borderline cases
        # Fully deterministic (no random noise)
        # =========================================================
        credit_norm = np.clip((credit - 650) / 550, 0, 1)
        dti_score = np.clip(1 - (total_dti / 6.0), 0, 1)
        income_score = np.clip((df['annual_income'] - 30000) / 150000, 0, 1)
        emp_score = np.clip(df['employment_length'] / 15, 0, 1)
        surplus_score = np.clip(monthly_surplus / 3000, 0, 1)
        cosigner_bonus = df['has_cosigner'] * 0.05

        emp_type_score = np.where(
            df['employment_type'] == 'payg_permanent', 0.05,
            np.where(df['employment_type'] == 'self_employed', -0.03, 0.0)
        )

        lvr_score = np.where(
            is_home, np.clip(1 - (lvr / 0.95), 0, 1), 0.5
        )

        dep_penalty = np.clip(df['number_of_dependants'] * 0.02, 0, 0.08)

        hecs_penalty = df['has_hecs'] * 0.02

        composite = (
            0.20 * credit_norm
            + 0.20 * dti_score
            + 0.12 * income_score
            + 0.08 * emp_score
            + 0.18 * surplus_score
            + 0.10 * lvr_score
            + emp_type_score
            + cosigner_bonus
            - dep_penalty
            - hecs_penalty
        )

        # Add small noise around the boundary to simulate real-world variation
        # (e.g., different loan officers, slightly different documentation quality)
        noise = rng.normal(0, 0.03, size=n)
        approved[(composite + noise) < 0.35] = 0

        return approved

    @staticmethod
    def _sanitize_csv_value(val):
        """Prefix formula-injection characters to prevent Excel macro execution."""
        if isinstance(val, str) and val and val[0] in ('=', '+', '-', '@'):
            return "'" + val
        return val

    def save_to_csv(self, df, path):
        """Save DataFrame to CSV, creating directories as needed."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        safe_df = df.apply(
            lambda col: col.map(self._sanitize_csv_value) if col.dtype == object else col
        )
        safe_df.to_csv(path, index=False)
        return path
