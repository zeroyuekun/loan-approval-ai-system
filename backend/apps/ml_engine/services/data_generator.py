import os

import numpy as np
import pandas as pd
from scipy import stats


class DataGenerator:
    """Creates synthetic loan data calibrated against official Australian sources.

    Calibration sources (all publicly available):
      - ATO Taxation Statistics 2022-23: individual income percentile distributions
        (Table 16). Median taxable income $55,868; male avg $86,199; female avg $62,046.
      - ABS Employee Earnings Aug 2025: median $74,100/yr (all employees).
      - ABS Characteristics of Employment Aug 2025: permanent ~77%, casual 19%,
        self-employed 7.6%, fixed-term contract ~4% of workforce.
      - ABS Lending Indicators Dec Q 2025: avg owner-occupier loan $693,801;
        avg first home buyer $560,249; avg investor loan $685,634.
      - APRA Quarterly ADI Property Exposures Sep Q 2025: 30.8% of new loans
        LVR >= 80%; 6.1% of new loans DTI >= 6; NPL rate 1.04%.
      - Equifax 2025 Credit Scorecard: national avg 864/1200; age 18-30 avg 715;
        age 31-40 avg 839; women avg 895; men avg 882.
        State scores: ACT 915, NSW 890, VIC 894, SA 898, TAS 895, WA 893,
        QLD 874, NT 844.
      - RBA Financial Stability Review Oct 2025: <1% owner-occ 90+ day arrears;
        30-89 day arrears 0.47%; household debt-to-income declining since 2018.
      - APRA Feb 2026: DTI >= 6 macroprudential limits activated.
      - Melbourne Institute HEM benchmarks (2025/2026, CPI-indexed).
      - ABS Total Value of Dwellings Dec Q 2025: mean $1,074,700.
    """

    PURPOSES = ['home', 'auto', 'education', 'personal', 'business']
    # Purpose distribution is driven by SUB_POPULATIONS mixture model below,
    # not by fixed weights. Home loans come from FHB+upgrader+refinancer segments,
    # business from business_borrower, personal from personal_borrower.
    HOME_OWNERSHIP = ['own', 'rent', 'mortgage']
    # ABS Census 2021: ~31% own outright, ~35% mortgage, ~30% rent, ~4% other
    # Loan applicants skew toward mortgage holders (existing borrowers refinancing)
    HOME_OWNERSHIP_WEIGHTS = [0.22, 0.30, 0.48]
    EMPLOYMENT_TYPES = ['payg_permanent', 'payg_casual', 'self_employed', 'contract']
    # ABS Characteristics of Employment Aug 2025:
    # permanent ~77%, casual 19%, self-employed 7.6%, fixed-term ~4%.
    # Loan applicants self-select: casuals/self-employed apply less often,
    # permanents apply more. Adjusted for applicant pool bias.
    EMPLOYMENT_TYPE_WEIGHTS = [0.68, 0.12, 0.12, 0.08]
    APPLICANT_TYPES = ['single', 'couple']
    # ABS Census 2021: ~49% of households are couple households.
    # For mortgage applications, couples are overrepresented (~58%) due to
    # dual-income serviceability advantage.
    APPLICANT_TYPE_WEIGHTS = [0.42, 0.58]

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

    # ===================================================================
    # GEOGRAPHIC SEGMENTATION by Australian state/territory.
    #
    # Property values, incomes, and credit scores vary significantly by
    # location. A Sydney applicant borrowing $1.2M at 70% LVR looks very
    # different from a regional SA applicant borrowing $350K at 85% LVR,
    # even though both are "typical" in their markets.
    #
    # Sources:
    #   - CoreLogic/Cotality 2025: median house prices by capital city
    #   - ABS Total Value of Dwellings Dec Q 2025: national mean $1,074,700
    #   - ABS Employee Earnings Aug 2025: state-level median earnings
    #   - Equifax 2025: credit scores by state (ACT 915, NT 844, etc.)
    #   - ABS Census 2021: population distribution by state
    #
    # Each state has: population weight, median house price, income
    # multiplier (vs national median), credit score adjustment, and
    # proportion of home loans that are investor vs owner-occupier.
    # ===================================================================
    STATES = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT']
    # Population weights (ABS 2024 estimated resident population):
    # NSW 31.8%, VIC 26.5%, QLD 20.7%, WA 11.0%, SA 7.1%,
    # TAS 2.2%, ACT 1.7%, NT 1.0%
    # Adjusted for loan application volume (Sydney/Melbourne overrepresented
    # due to higher property values driving more mortgage applications)
    STATE_WEIGHTS = [0.33, 0.27, 0.19, 0.10, 0.06, 0.02, 0.02, 0.01]

    STATE_PROFILES = {
        # median_house: CoreLogic Dec 2025 median house prices
        # income_mult: ABS state median earnings relative to national median
        # credit_adj: Equifax 2025 state avg minus national avg (864)
        # investor_pct: APRA state-level investor loan share
        'NSW': {
            'median_house': 1_650_000,  # Sydney dominates
            'income_mult': 1.08,         # higher than national
            'credit_adj': +26,           # Equifax NSW avg 890
            'investor_pct': 0.40,        # highest investor share
        },
        'VIC': {
            'median_house': 978_000,
            'income_mult': 1.03,
            'credit_adj': +30,           # Equifax VIC avg 894
            'investor_pct': 0.35,
        },
        'QLD': {
            'median_house': 880_000,     # rapid growth ~86% over 5yr
            'income_mult': 0.95,
            'credit_adj': +10,           # Equifax QLD avg 874
            'investor_pct': 0.33,
        },
        'WA': {
            'median_house': 981_000,     # mining-driven recovery
            'income_mult': 1.12,         # mining incomes push median up
            'credit_adj': +29,           # Equifax WA avg 893
            'investor_pct': 0.28,
        },
        'SA': {
            'median_house': 750_000,     # strong growth ~80% over 5yr
            'income_mult': 0.92,
            'credit_adj': +34,           # Equifax SA avg 898
            'investor_pct': 0.25,
        },
        'TAS': {
            'median_house': 620_000,
            'income_mult': 0.88,
            'credit_adj': +31,           # Equifax TAS avg 895
            'investor_pct': 0.20,
        },
        'ACT': {
            'median_house': 950_000,
            'income_mult': 1.25,         # public service premium
            'credit_adj': +51,           # Equifax ACT avg 915 (highest)
            'investor_pct': 0.30,
        },
        'NT': {
            'median_house': 520_000,
            'income_mult': 1.05,         # mining/government mix
            'credit_adj': -20,           # Equifax NT avg 844 (lowest)
            'investor_pct': 0.22,
        },
    }

    # ===================================================================
    # GAUSSIAN COPULA: correlation structure for numeric features.
    #
    # In real lending data, features are correlated: higher income
    # applicants tend to have better credit scores, longer employment,
    # higher expenses, and larger credit card limits. Generating features
    # independently misses these joint patterns. A Gaussian copula
    # preserves each feature's marginal distribution while introducing
    # realistic pairwise correlations.
    #
    # Correlation matrix for: [age, income, credit_score, employment_length,
    #   monthly_expenses, credit_card_limit, number_of_dependants]
    #
    # Estimated from: ATO income-by-age tables, Equifax score-by-age data,
    # ABS employment tenure by age/income, and domain knowledge from
    # banking literature on borrower profiles.
    # ===================================================================
    COPULA_FEATURES = [
        'age', 'income', 'credit_score', 'employment_length',
        'monthly_expenses', 'credit_card_limit', 'dependants',
    ]
    COPULA_CORRELATION = np.array([
        # age   income  credit  emp_len expenses cc_lim  deps
        [1.00,  0.35,   0.40,   0.55,   0.20,   0.25,   0.15],  # age
        [0.35,  1.00,   0.30,   0.25,   0.45,   0.40,  -0.05],  # income
        [0.40,  0.30,   1.00,   0.20,   0.10,   0.15,  -0.10],  # credit_score
        [0.55,  0.25,   0.20,   1.00,   0.10,   0.15,   0.10],  # employment_length
        [0.20,  0.45,   0.10,   0.10,   1.00,   0.30,   0.25],  # monthly_expenses
        [0.25,  0.40,   0.15,   0.15,   0.30,   1.00,   0.10],  # credit_card_limit
        [0.15, -0.05,  -0.10,   0.10,   0.25,   0.10,   1.00],  # dependants
    ])

    # Validate positive semi-definiteness at import time.
    # If any future edit makes the matrix invalid, this fails immediately
    # rather than producing cryptic numpy errors during generation.
    _eigvals = np.linalg.eigvalsh(COPULA_CORRELATION)
    assert np.all(_eigvals >= -1e-10), (
        f"COPULA_CORRELATION is not positive semi-definite. "
        f"Min eigenvalue: {_eigvals.min():.6f}"
    )

    # ===================================================================
    # SUB-POPULATION MIXTURE MODEL
    #
    # Real loan applicants fall into distinct clusters with different
    # feature distributions. A Gaussian Mixture Model generates from
    # these clusters separately, producing more realistic joint
    # distributions than a single population.
    #
    # Each sub-population has: weight (proportion), income_mean,
    # income_sigma, credit_score_mean, age_mean, loan_multiplier_mean,
    # lvr_mean, typical_purpose_weights.
    # ===================================================================
    SUB_POPULATIONS = {
        'first_home_buyer': {
            'weight': 0.18,
            'age_mean': 30, 'age_std': 5,
            'income_single_mean': 72000, 'income_couple_mean': 140000,
            'credit_score_mean': 790, 'credit_score_std': 80,
            'loan_mult_mean': 4.8, 'loan_mult_std': 0.7,
            'lvr_mean': 0.85, 'lvr_std': 0.06,  # high LVR (small deposit)
            'purpose_override': 'home',
        },
        'upgrader': {
            'weight': 0.20,
            'age_mean': 42, 'age_std': 7,
            'income_single_mean': 95000, 'income_couple_mean': 170000,
            'credit_score_mean': 880, 'credit_score_std': 70,
            'loan_mult_mean': 4.0, 'loan_mult_std': 0.8,
            'lvr_mean': 0.62, 'lvr_std': 0.10,  # moderate LVR (existing equity)
            'purpose_override': 'home',
        },
        'refinancer': {
            'weight': 0.10,
            'age_mean': 48, 'age_std': 8,
            'income_single_mean': 90000, 'income_couple_mean': 165000,
            'credit_score_mean': 910, 'credit_score_std': 60,
            'loan_mult_mean': 3.0, 'loan_mult_std': 0.7,
            'lvr_mean': 0.55, 'lvr_std': 0.12,  # low LVR (long payment history)
            'purpose_override': 'home',
        },
        'personal_borrower': {
            'weight': 0.37,
            'age_mean': 36, 'age_std': 10,
            'income_single_mean': 68000, 'income_couple_mean': 130000,
            'credit_score_mean': 850, 'credit_score_std': 90,
            'loan_mult_mean': 0.35, 'loan_mult_std': 0.3,
            'lvr_mean': 0.0, 'lvr_std': 0.0,  # not applicable
            'purpose_override': None,  # uses PURPOSE_WEIGHTS for non-home
        },
        'business_borrower': {
            'weight': 0.15,
            'age_mean': 44, 'age_std': 9,
            'income_single_mean': 85000, 'income_couple_mean': 155000,
            'credit_score_mean': 860, 'credit_score_std': 85,
            'loan_mult_mean': 0.6, 'loan_mult_std': 0.5,
            'lvr_mean': 0.0, 'lvr_std': 0.0,
            'purpose_override': 'business',
        },
    }

    def _generate_copula_samples(self, n, rng):
        """Generate correlated uniform samples using a Gaussian copula.

        A Gaussian copula works by:
        1. Drawing from a multivariate normal with the target correlation matrix
        2. Transforming each dimension through its CDF to get uniform [0,1] values
        3. These uniform values preserve the correlation structure and can be
           transformed into any target marginal distribution

        This ensures that age, income, credit score, employment length, expenses,
        credit card limits, and dependants are all properly correlated, matching
        the real-world relationships observed in ATO/ABS/Equifax data.
        """
        k = len(self.COPULA_FEATURES)
        # Draw from multivariate normal with the target correlation
        mvn_samples = rng.multivariate_normal(
            mean=np.zeros(k), cov=self.COPULA_CORRELATION, size=n
        )
        # Transform to uniform [0,1] via the standard normal CDF
        uniform_samples = stats.norm.cdf(mvn_samples)
        return {
            name: uniform_samples[:, i]
            for i, name in enumerate(self.COPULA_FEATURES)
        }

    def generate(self, num_records=10000, random_seed=42):
        """Generate synthetic loan data with Australian-realistic distributions.

        Uses a Gaussian copula for correlated feature generation and a
        sub-population mixture model for realistic applicant segmentation.
        """
        rng = np.random.default_rng(random_seed)
        n = num_records
        self.reject_inference_labels = None  # populated at end of generate()

        # =============================================================
        # STEP 0: Generate correlated uniform samples via Gaussian copula
        # =============================================================
        copula = self._generate_copula_samples(n, rng)

        # =============================================================
        # STEP 1: Assign sub-populations and geographic location
        # =============================================================
        pop_names = list(self.SUB_POPULATIONS.keys())
        pop_weights = [self.SUB_POPULATIONS[p]['weight'] for p in pop_names]
        sub_pop = rng.choice(pop_names, size=n, p=pop_weights)

        # Assign state/territory based on population-weighted distribution
        state = rng.choice(self.STATES, size=n, p=self.STATE_WEIGHTS)

        # --- Demographics ---
        employment_type = rng.choice(
            self.EMPLOYMENT_TYPES, size=n, p=self.EMPLOYMENT_TYPE_WEIGHTS
        )
        applicant_type = rng.choice(
            self.APPLICANT_TYPES, size=n, p=self.APPLICANT_TYPE_WEIGHTS
        )

        # Dependants: transform copula uniform → discrete via quantile function
        # Higher copula value → more dependants
        dep_thresholds = np.cumsum([0.35, 0.25, 0.25, 0.10])  # [0.35, 0.60, 0.85, 0.95]
        number_of_dependants = np.digitize(copula['dependants'], dep_thresholds)

        # --- Age: transform copula uniform using sub-population parameters ---
        age_proxy = np.zeros(n, dtype=int)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            # Use inverse CDF (ppf) to transform copula uniform → normal with pop params
            age_proxy[mask] = np.clip(
                stats.norm.ppf(copula['age'][mask], loc=pop['age_mean'], scale=pop['age_std']).astype(int),
                20, 70,
            )

        # --- Income: copula-correlated, sub-population + state-aware ---
        # State income multipliers from ABS Employee Earnings Aug 2025:
        # e.g., WA 1.12x (mining), ACT 1.25x (public service), TAS 0.88x
        state_income_mult = np.array([
            self.STATE_PROFILES[s]['income_mult'] for s in state
        ])
        annual_income = np.zeros(n)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            is_couple = applicant_type[mask] == 'couple'
            # Transform copula uniform → lognormal income, then apply state multiplier
            inc_mean = np.where(is_couple, pop['income_couple_mean'], pop['income_single_mean'])
            inc_mean = inc_mean * state_income_mult[mask]  # state adjustment
            inc_sigma = np.where(is_couple, 0.42, 0.55)
            annual_income[mask] = np.exp(
                stats.norm.ppf(copula['income'][mask], loc=np.log(inc_mean), scale=inc_sigma)
            )
        annual_income = np.clip(annual_income.round(2), 30000, 600000)

        # --- Employment length: copula-correlated ---
        # Transform copula uniform → exponential via inverse CDF
        employment_length = np.clip(
            stats.expon.ppf(copula['employment_length'], scale=6).astype(int), 0, 40
        )
        perm_mask = employment_type == 'payg_permanent'
        employment_length[perm_mask] = np.clip(employment_length[perm_mask], 1, 40)
        low_income = annual_income < 50000
        employment_length[low_income] = np.clip(
            employment_length[low_income] - rng.integers(0, 2, size=low_income.sum()),
            0, 40,
        )

        # --- Purpose: determined by sub-population ---
        purpose = np.empty(n, dtype='<U10')
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            if pop['purpose_override']:
                purpose[mask] = pop['purpose_override']
            else:
                # Personal borrowers: distribute across non-home purposes
                non_home_purposes = ['auto', 'education', 'personal']
                non_home_weights = np.array([0.36, 0.24, 0.40])
                purpose[mask] = rng.choice(non_home_purposes, size=mask.sum(), p=non_home_weights)
        is_home = purpose == 'home'

        # --- Credit score: copula-correlated, sub-population + state-aware ---
        # Equifax 2025 state averages: ACT 915, SA 898, TAS 895, VIC 894,
        # WA 893, NSW 890, QLD 874, NT 844. National avg 864.
        state_credit_adj = np.array([
            self.STATE_PROFILES[s]['credit_adj'] for s in state
        ])
        credit_score = np.zeros(n, dtype=int)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            credit_score[mask] = np.clip(
                stats.norm.ppf(
                    copula['credit_score'][mask],
                    loc=pop['credit_score_mean'] + state_credit_adj[mask],
                    scale=pop['credit_score_std'],
                ).astype(int),
                300, 1200,
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
        existing_dti = np.where(
            is_home,
            np.clip(rng.beta(a=2.0, b=8.0, size=n) * 0.8, 0, 0.8),
            np.clip(rng.beta(a=2.0, b=6.0, size=n) * 1.2, 0, 1.2),
        ).round(2)

        # Correlation: higher existing DTI → lower credit scores
        dti_penalty = np.clip((existing_dti - 0.3) * 60, 0, 100).astype(int)
        credit_score = np.clip(credit_score - dti_penalty, 300, 1200)
        credit_score[is_home] = np.clip(credit_score[is_home], 700, 1200)
        credit_score[~is_home] = np.clip(credit_score[~is_home], 650, 1200)

        # --- Loan amounts: sub-population-driven ---
        loan_multiplier = np.zeros(n)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            if pop['purpose_override'] == 'home':
                loan_multiplier[mask] = np.clip(
                    rng.normal(pop['loan_mult_mean'], pop['loan_mult_std'], size=mask.sum()),
                    1.0, 6.5,
                )
            else:
                loan_multiplier[mask] = np.clip(
                    rng.lognormal(mean=np.log(pop['loan_mult_mean']), sigma=pop['loan_mult_std'], size=mask.sum()),
                    0.05, 2.0,
                )
        loan_amount = (annual_income * loan_multiplier).round(2)
        loan_amount = np.clip(loan_amount, 5000, 3500000)

        # Total DTI including new loan
        new_loan_dti = loan_amount / annual_income
        debt_to_income = (existing_dti + new_loan_dti).round(2)

        # Standard Australian loan terms
        loan_term_months = np.where(
            is_home,
            rng.choice([240, 300, 360], size=n, p=[0.20, 0.35, 0.45]),
            rng.choice([12, 24, 36, 60, 84], size=n, p=[0.10, 0.15, 0.30, 0.30, 0.15]),
        )

        # --- Property value: sub-population-driven LVR targets ---
        # APRA Sep Q 2025: 30.8% of new loans have LVR >= 80%.
        # Sub-populations naturally produce this: FHBs have high LVR (~88%),
        # upgraders moderate (~65%), refinancers low (~55%).
        property_value = np.zeros(n)
        lvr_targets = np.zeros(n)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            if pop['lvr_mean'] > 0:
                lvr_targets[mask] = np.clip(
                    rng.normal(pop['lvr_mean'], pop['lvr_std'], size=mask.sum()),
                    0.30, 0.97,
                )
        # Non-home loans don't have property/LVR
        lvr_targets[~is_home] = 0.0
        safe_lvr = np.where(lvr_targets > 0, lvr_targets, 1.0)
        property_value[is_home] = (loan_amount[is_home] / safe_lvr[is_home]).round(2)
        property_value = np.clip(property_value, 0, 10000000)

        # Deposit
        deposit_amount = np.zeros(n)
        deposit_amount[is_home] = np.maximum(
            property_value[is_home] - loan_amount[is_home], 0
        ).round(2)

        # Monthly declared expenses: copula-correlated with income
        # Higher copula value → higher expenses (correlated with income)
        monthly_expenses = np.clip(
            np.exp(stats.norm.ppf(copula['monthly_expenses'], loc=np.log(2500), scale=0.4)).round(2),
            800, 10000,
        )

        # Credit card limits: copula-correlated with income
        has_credit_card = copula['credit_card_limit'] < 0.70  # ~70% have a card
        existing_credit_card_limit = np.where(
            has_credit_card,
            np.clip(
                np.exp(stats.norm.ppf(
                    np.clip(copula['credit_card_limit'] / 0.70, 0.001, 0.999),
                    loc=np.log(8000), scale=0.6,
                )),
                0, 50000,
            ).round(2),
            0,
        )

        # --- HECS/HELP debt (ATO compulsory repayment at ~3.5% of gross) ---
        # ATO 2022-23: ~3 million Australians have HECS debt.
        # ~40% of borrowers under 55 carry HECS (skews younger: ~55% under 35).
        hecs_rate = np.where(age_proxy < 35, 0.55, np.where(age_proxy < 55, 0.30, 0.05))
        has_hecs = (rng.random(n) < hecs_rate).astype(int)

        # --- Bankruptcy (hard disqualifier) ---
        # AFSA 2024-25: ~12,000 personal insolvencies/yr on ~20M adults ≈ 0.06%.
        # But cumulative (discharged within 7 years still visible on bureau):
        # ~1.5-2% of population have a bankruptcy flag. Loan applicants with
        # bankruptcy mostly self-select out, so ~1% of applicants carry the flag.
        has_bankruptcy = rng.choice([0, 1], size=n, p=[0.99, 0.01])

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
            'state': state,
        }

        df = pd.DataFrame(data)
        # Store temporary columns for approval calculation (not model features)
        df['_existing_dti'] = existing_dti
        df['_age_proxy'] = age_proxy

        # Compute approval using TRUE values (banks verify documents)
        df['approved'] = self._compute_approval(df, rng)
        df.drop(columns=['_existing_dti', '_age_proxy'], inplace=True)

        # =========================================================
        # MEASUREMENT NOISE: After approval is computed, add noise
        # to features the model will see. This simulates:
        # - Income rounding/estimation on applications (~5% variance)
        # - Expense under-reporting by applicants (~8% variance)
        # - Credit score timing differences (bureau vs application date)
        # - Employment length rounding (months → years)
        #
        # The bank sees verified documents; the model sees the
        # application form. This gap creates realistic prediction error.
        # =========================================================
        income_noise = rng.normal(1.0, 0.08, size=n)
        df['annual_income'] = np.clip(
            (df['annual_income'] * income_noise).round(2), 30000, 600000
        )

        expense_noise = rng.normal(0.88, 0.10, size=n)  # applicants under-report
        df['monthly_expenses'] = np.clip(
            (df['monthly_expenses'] * expense_noise).round(2), 800, 10000
        )

        credit_score_drift = rng.integers(-40, 41, size=n)
        df['credit_score'] = np.clip(
            df['credit_score'] + credit_score_drift, 300, 1200
        )
        # Re-apply purpose floors
        df.loc[df['purpose'] == 'home', 'credit_score'] = df.loc[
            df['purpose'] == 'home', 'credit_score'
        ].clip(lower=700)
        df.loc[df['purpose'] != 'home', 'credit_score'] = df.loc[
            df['purpose'] != 'home', 'credit_score'
        ].clip(lower=650)

        # Recalculate DTI with noisy income (model sees this, not true DTI)
        df['debt_to_income'] = (
            df['loan_amount'] / df['annual_income']
            + existing_dti * (annual_income / df['annual_income'])
        ).round(2)

        # =========================================================
        # MISSING DATA: ~3-5% of optional fields are incomplete,
        # matching real application submission rates.
        # =========================================================
        # Monthly expenses: ~4% missing (applicants skip this field)
        expense_missing = rng.random(n) < 0.04
        df.loc[expense_missing, 'monthly_expenses'] = np.nan

        # Credit card limit: ~3% missing
        cc_missing = rng.random(n) < 0.03
        df.loc[cc_missing, 'existing_credit_card_limit'] = np.nan

        # Property value: ~2% of home loans missing (pre-valuation stage)
        home_mask = df['purpose'] == 'home'
        pv_missing = home_mask & (rng.random(n) < 0.02)
        df.loc[pv_missing, 'property_value'] = np.nan
        df.loc[pv_missing, 'deposit_amount'] = np.nan

        # =========================================================
        # REJECT INFERENCE (parcelling method)
        #
        # In real lending, banks only observe loan outcomes (repaid vs
        # defaulted) for APPROVED applicants. Denied applicants never
        # got the loan, so their outcome is unknown. This creates
        # selection bias: the model only learns from the approved
        # population, which is systematically different from the full
        # applicant pool.
        #
        # Reject inference estimates what would have happened to denied
        # applicants. The "parcelling" method (used by Australian banks)
        # assigns denied applicants a probability of being "good" based
        # on their observable features relative to approved applicants,
        # then probabilistically labels them.
        #
        # Without reject inference, a model trained only on approved
        # loans learns that "everyone who gets a loan repays" — which
        # is circular. With it, the model learns the full risk spectrum.
        #
        # We simulate this by adding a 'would_have_repaid' column for
        # denied applicants, estimating their hypothetical performance
        # based on their feature similarity to approved applicants.
        # =========================================================
        denied_mask = df['approved'] == 0
        n_denied = denied_mask.sum()
        if n_denied > 0:
            # Denied applicants with strong features would likely have
            # repaid. Use credit score and DTI as primary indicators.
            denied_credit = df.loc[denied_mask, 'credit_score'].values
            denied_dti = df.loc[denied_mask, 'debt_to_income'].values

            # Probability of being "good" (would have repaid) based on
            # feature strength. Higher credit + lower DTI = more likely good.
            credit_norm = np.clip((denied_credit - 650) / 400, 0, 1)
            dti_norm = np.clip(1 - denied_dti / 6.0, 0, 1)
            p_good = 0.6 * credit_norm + 0.4 * dti_norm

            # Probabilistically assign outcomes
            would_have_repaid = (rng.random(n_denied) < p_good).astype(int)

            # Store as instance attribute (NOT in the training DataFrame)
            # to prevent accidental target leakage. The column is a
            # near-perfect proxy for the target (NaN for approved, 0/1
            # for denied) — including it in the CSV would be catastrophic.
            self.reject_inference_labels = pd.Series(
                np.nan, index=df.index, name='reject_inference_label'
            )
            self.reject_inference_labels.loc[denied_mask] = would_have_repaid

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

        gross_monthly_income = df['annual_income'] / 12
        total_dti = df['debt_to_income']
        existing_dti = df['_existing_dti']
        credit = df['credit_score']

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
        doc_quality[df['employment_type'] == 'self_employed'] *= rng.uniform(0.6, 0.9, size=(df['employment_type'] == 'self_employed').sum())
        doc_quality[df['employment_type'] == 'payg_casual'] *= rng.uniform(0.7, 0.95, size=(df['employment_type'] == 'payg_casual').sum())

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
        # =========================================================
        income_shade = df['employment_type'].map(self.INCOME_SHADING).values
        shaded_monthly_income = gross_monthly_income * income_shade

        # =========================================================
        # STEP 2: Hard cutoffs (auto-deny)
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
        # Banks also assess savings pattern quality for high LVR
        weak_savings = needs_genuine_savings & (savings_pattern < 0.35)
        approved[weak_savings & (df['deposit_amount'] < min_genuine_savings * 1.2)] = 0
        approved[needs_genuine_savings & ~weak_savings & (df['deposit_amount'] < min_genuine_savings)] = 0

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

        # Monthly surplus at the assessment rate (APRA 3% buffer).
        # At the actual product rate (~6.5%), most of these loans are
        # comfortably serviceable. The APRA buffer (3% above product rate)
        # creates a theoretical stress test, not a hard boundary. Banks
        # routinely approve loans with modest shortfalls at the assessment
        # rate if the applicant has compensating strengths (strong credit,
        # stable employment, genuine savings). Only hard-deny if shortfall
        # exceeds $1,500/month at the assessment rate (serious distress).
        monthly_surplus = (
            shaded_monthly_income
            - monthly_tax
            - effective_expenses
            - existing_debt_monthly
            - credit_card_monthly
            - hecs_monthly
            - monthly_repayment
        )
        # Surplus is used as a factor in composite scoring below rather
        # than a hard cutoff, except for severe shortfalls (can't service
        # even at the actual product rate, let alone the assessment rate).
        # At 6.5% product rate, repayment is ~25% lower than at 9.5%.
        product_rate_monthly = self.BASE_RATE / 12
        product_repayment = (
            effective_loan_amount
            * product_rate_monthly
            * (1 + product_rate_monthly) ** term_months
            / ((1 + product_rate_monthly) ** term_months - 1)
        )
        product_surplus = (
            shaded_monthly_income - monthly_tax - effective_expenses
            - existing_debt_monthly - credit_card_monthly - hecs_monthly
            - product_repayment
        )
        # Hard deny only if can't service at the ACTUAL product rate.
        # Even here, a modest shortfall can be offset by other income
        # sources (rental income, partner income not declared, overtime).
        approved[product_surplus < -1000] = 0

        # =========================================================
        # STEP 8: DSR check (debt service ratio)
        # Banks allow higher DSR for higher income borrowers.
        # APRA Sep Q 2025: only ~6% of new loans have DTI >= 6,
        # meaning most borrowers pass serviceability comfortably.
        # Real DSR caps are applied at the assessment rate (incl buffer),
        # but banks also consider net surplus — if surplus is positive
        # and DSR is only modestly over the soft cap, many still approve.
        # DSR caps are assessed at the APRA buffer rate (product + 3%),
        # making them appear higher than they would at the actual rate.
        # At the actual product rate (~6.5%), the effective DSR is ~5-8%
        # lower. Banks use these generous caps because the buffer already
        # builds in conservative stress margin.
        # Caps: <$80k: 50%, $80k-$150k: 55%, >$150k: 60%
        # =========================================================
        total_repayments = existing_debt_monthly + credit_card_monthly + hecs_monthly + monthly_repayment
        dsr = total_repayments / gross_monthly_income
        # DSR at assessment rate will be ~25% higher than at product rate.
        # Use generous caps to avoid over-filtering, since the composite
        # score already penalises high DSR through the surplus_score.
        dsr_cap = np.where(
            df['annual_income'] > 150000, 0.65,
            np.where(df['annual_income'] > 80000, 0.60, 0.55)
        )
        approved[dsr > dsr_cap] = 0

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
            - hecs_penalty
        )

        # Hidden component (model CANNOT learn — creates irreducible error)
        # These represent real factors banks assess that aren't in the
        # structured application data. Weighted heavily to create a
        # realistic AUC ceiling (real bank scorecards: 0.82-0.88).
        hidden_score = (
            0.16 * doc_quality           # documentation completeness
            + 0.14 * savings_pattern     # genuine savings behaviour
            + 0.10 * employer_stability  # employer/industry risk rating
            + relationship_bonus         # existing customer loyalty
        )

        composite = observable_score + hidden_score

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
        approved[final_score < 0.18] = 0

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
        denied_mask = (approved == 0) & (final_score > 0.15) & (final_score < 0.40)
        override_approve = denied_mask & (rng.random(n) < 0.12)
        # Don't rescue bankruptcy or extreme DTI
        override_approve = override_approve & (df['has_bankruptcy'] == 0) & (total_dti < 5.5)
        approved[override_approve] = 1

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
