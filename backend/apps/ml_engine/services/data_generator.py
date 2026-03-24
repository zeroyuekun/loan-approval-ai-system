import os
from datetime import date, timedelta

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

    # Reject inference weights (parcelling method).
    # Parcelling method: heuristic without theoretical guarantees (PMC 2022).
    # Weights are configurable.
    REJECT_INFERENCE_CREDIT_WEIGHT = 0.6
    REJECT_INFERENCE_DTI_WEIGHT = 0.4

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
    # Expanded to 5 income brackets and 0-4+ dependants (real HEM has 6+ brackets)
    HEM_TABLE = {
        # Single applicants
        ('single', 0, 'very_low'): 1400, ('single', 0, 'low'): 1600, ('single', 0, 'mid'): 2050, ('single', 0, 'high'): 2500, ('single', 0, 'very_high'): 3000,
        ('single', 1, 'very_low'): 1900, ('single', 1, 'low'): 2150, ('single', 1, 'mid'): 2600, ('single', 1, 'high'): 3050, ('single', 1, 'very_high'): 3600,
        ('single', 2, 'very_low'): 2200, ('single', 2, 'low'): 2500, ('single', 2, 'mid'): 3050, ('single', 2, 'high'): 3500, ('single', 2, 'very_high'): 4100,
        ('single', 3, 'very_low'): 2500, ('single', 3, 'low'): 2850, ('single', 3, 'mid'): 3400, ('single', 3, 'high'): 3900, ('single', 3, 'very_high'): 4500,
        ('single', 4, 'very_low'): 2800, ('single', 4, 'low'): 3150, ('single', 4, 'mid'): 3750, ('single', 4, 'high'): 4300, ('single', 4, 'very_high'): 4900,
        # Couple applicants
        ('couple', 0, 'very_low'): 2100, ('couple', 0, 'low'): 2400, ('couple', 0, 'mid'): 2950, ('couple', 0, 'high'): 3500, ('couple', 0, 'very_high'): 4200,
        ('couple', 1, 'very_low'): 2550, ('couple', 1, 'low'): 2850, ('couple', 1, 'mid'): 3400, ('couple', 1, 'high'): 3950, ('couple', 1, 'very_high'): 4700,
        ('couple', 2, 'very_low'): 2900, ('couple', 2, 'low'): 3200, ('couple', 2, 'mid'): 3850, ('couple', 2, 'high'): 4400, ('couple', 2, 'very_high'): 5200,
        ('couple', 3, 'very_low'): 3250, ('couple', 3, 'low'): 3550, ('couple', 3, 'mid'): 4200, ('couple', 3, 'high'): 4800, ('couple', 3, 'very_high'): 5600,
        ('couple', 4, 'very_low'): 3550, ('couple', 4, 'low'): 3900, ('couple', 4, 'mid'): 4550, ('couple', 4, 'high'): 5200, ('couple', 4, 'very_high'): 6000,
    }

    # Geographic HEM multiplier (Sydney/Melbourne higher COL, regional lower)
    STATE_HEM_MULTIPLIER = {
        'NSW': 1.15, 'VIC': 1.08, 'QLD': 1.00, 'WA': 1.05,
        'SA': 0.92, 'TAS': 0.90, 'ACT': 1.10, 'NT': 1.02,
    }

    # Income shading by employment type (what % of income banks accept)
    # Refined per Big 4 2025 practice: self-employed 1yr+ accepted (was 2yr),
    # casual tenure-based tiers, contract at 85%.
    INCOME_SHADING = {
        'payg_permanent': 1.00,
        'payg_casual': 0.80,        # base; <1yr: hard deny, 1-2yr: 0.80, 2yr+: 1.00
        'self_employed': 0.75,      # base; 1-2yr: 0.75, 2yr+: 0.82 (applied dynamically)
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
            'weight': 0.15,
            'age_mean': 33, 'age_std': 5,  # ABS Dec 2025: avg FHB age 33
            # ABS Dec 2025: avg FHB loan $607,624; FHB median household
            # income ~$105k (couple), ~$65k (single). Updated couple to
            # $95k to produce realistic loan sizes at 6.2x multiplier.
            'income_single_mean': 58000, 'income_couple_mean': 95000,
            'credit_score_mean': 800, 'credit_score_std': 80,
            'loan_mult_mean': 5.2, 'loan_mult_std': 0.8,
            'lvr_mean': 0.87, 'lvr_std': 0.05,  # high LVR — APRA: 30.4% of new loans LVR>=80%
            'purpose_override': 'home',
        },
        'upgrader': {
            'weight': 0.20,
            'age_mean': 42, 'age_std': 7,
            # ABS 2025: upgrader household ~$130k (couple), ~$82k (single)
            'income_single_mean': 74000, 'income_couple_mean': 105000,
            'credit_score_mean': 875, 'credit_score_std': 70,
            'loan_mult_mean': 4.0, 'loan_mult_std': 0.8,
            'lvr_mean': 0.65, 'lvr_std': 0.12,  # moderate LVR (existing equity)
            'purpose_override': 'home',
        },
        'refinancer': {
            'weight': 0.10,
            'age_mean': 48, 'age_std': 8,
            # ABS 2025: refinancers ~$125k (couple), ~$78k (single)
            'income_single_mean': 70000, 'income_couple_mean': 100000,
            'credit_score_mean': 905, 'credit_score_std': 60,
            'loan_mult_mean': 3.0, 'loan_mult_std': 0.7,
            'lvr_mean': 0.55, 'lvr_std': 0.12,  # low LVR (long payment history)
            'purpose_override': 'home',
        },
        'personal_borrower': {
            'weight': 0.35,
            'age_mean': 36, 'age_std': 10,
            # ATO 2022-23: median taxable income ~$56k; personal loan applicants
            # skew slightly above median. Couples ~$100k household.
            'income_single_mean': 50000, 'income_couple_mean': 72000,
            'credit_score_mean': 845, 'credit_score_std': 90,
            'loan_mult_mean': 0.35, 'loan_mult_std': 0.3,
            'lvr_mean': 0.0, 'lvr_std': 0.0,  # not applicable
            'purpose_override': None,  # uses PURPOSE_WEIGHTS for non-home
        },
        'business_borrower': {
            'weight': 0.12,
            'age_mean': 44, 'age_std': 9,
            # ATO 2022-23: self-employed median ~$62k; business borrowers
            # skew higher. Couples ~$120k household.
            'income_single_mean': 60000, 'income_couple_mean': 92000,
            'credit_score_mean': 855, 'credit_score_std': 85,
            'loan_mult_mean': 0.6, 'loan_mult_std': 0.5,
            'lvr_mean': 0.0, 'lvr_std': 0.0,
            'purpose_override': 'business',
        },
        # ~30-40% of Australian lending is investor loans (APRA Sep Q 2025).
        # Investor segment has tighter DTI assessment, lower max LVR,
        # and APRA macroprudential rules (interest-only caps, etc.)
        'investor': {
            'weight': 0.08,
            'age_mean': 45, 'age_std': 8,
            # ATO 2022-23: investors skew higher income — top 20% earners
            'income_single_mean': 85000, 'income_couple_mean': 125000,
            'credit_score_mean': 885, 'credit_score_std': 65,
            'loan_mult_mean': 4.5, 'loan_mult_std': 1.0,
            'lvr_mean': 0.70, 'lvr_std': 0.08,  # lower LVR than owner-occ
            'purpose_override': 'home',
        },
    }

    # ===================================================================
    # TEMPORAL DIMENSION — 36-month application window
    # Real lending data spans years with economic cycles.
    # ===================================================================

    # Quarterly RBA cash rate (actual historical + projected)
    RBA_RATE_HISTORY = {
        '2023Q3': 4.10, '2023Q4': 4.35,
        '2024Q1': 4.35, '2024Q2': 4.35, '2024Q3': 4.35, '2024Q4': 4.35,
        '2025Q1': 4.10, '2025Q2': 4.10, '2025Q3': 3.85, '2025Q4': 3.85,
        '2026Q1': 3.60, '2026Q2': 3.60,
    }

    # Property growth 12-month % by state and quarter (CoreLogic-calibrated)
    PROPERTY_GROWTH = {
        '2023Q3': {'NSW': 8.1, 'VIC': 3.2, 'QLD': 12.4, 'WA': 15.8, 'SA': 9.7, 'TAS': -0.5, 'ACT': 1.2, 'NT': 0.8},
        '2023Q4': {'NSW': 10.2, 'VIC': 4.1, 'QLD': 13.1, 'WA': 17.2, 'SA': 11.3, 'TAS': 0.2, 'ACT': 2.0, 'NT': 1.5},
        '2024Q1': {'NSW': 7.5, 'VIC': 2.8, 'QLD': 14.8, 'WA': 20.1, 'SA': 13.5, 'TAS': 1.0, 'ACT': 2.5, 'NT': 2.0},
        '2024Q2': {'NSW': 5.8, 'VIC': 1.5, 'QLD': 13.2, 'WA': 22.3, 'SA': 14.1, 'TAS': 0.8, 'ACT': 1.8, 'NT': 1.2},
        '2024Q3': {'NSW': 4.2, 'VIC': 0.8, 'QLD': 10.5, 'WA': 18.7, 'SA': 12.8, 'TAS': 0.5, 'ACT': 1.5, 'NT': 0.9},
        '2024Q4': {'NSW': 3.5, 'VIC': -0.2, 'QLD': 8.8, 'WA': 15.4, 'SA': 11.2, 'TAS': -0.3, 'ACT': 0.8, 'NT': 0.5},
        '2025Q1': {'NSW': 2.8, 'VIC': -1.0, 'QLD': 6.5, 'WA': 10.2, 'SA': 8.5, 'TAS': -0.8, 'ACT': 0.5, 'NT': 0.2},
        '2025Q2': {'NSW': 3.2, 'VIC': 0.5, 'QLD': 5.8, 'WA': 8.1, 'SA': 7.2, 'TAS': 0.0, 'ACT': 1.0, 'NT': 0.5},
        '2025Q3': {'NSW': 4.0, 'VIC': 1.2, 'QLD': 5.5, 'WA': 7.5, 'SA': 6.8, 'TAS': 0.5, 'ACT': 1.5, 'NT': 0.8},
        '2025Q4': {'NSW': 4.5, 'VIC': 2.0, 'QLD': 5.2, 'WA': 6.8, 'SA': 6.5, 'TAS': 1.0, 'ACT': 2.0, 'NT': 1.0},
        '2026Q1': {'NSW': 5.0, 'VIC': 2.8, 'QLD': 5.0, 'WA': 6.2, 'SA': 6.0, 'TAS': 1.5, 'ACT': 2.5, 'NT': 1.2},
        '2026Q2': {'NSW': 5.2, 'VIC': 3.0, 'QLD': 4.8, 'WA': 5.8, 'SA': 5.5, 'TAS': 1.8, 'ACT': 2.8, 'NT': 1.5},
    }

    # State unemployment rates by quarter (ABS Labour Force)
    UNEMPLOYMENT_RATES = {
        '2023Q3': {'NSW': 3.1, 'VIC': 3.5, 'QLD': 3.8, 'WA': 3.2, 'SA': 4.0, 'TAS': 4.2, 'ACT': 2.8, 'NT': 3.5},
        '2023Q4': {'NSW': 3.3, 'VIC': 3.7, 'QLD': 3.9, 'WA': 3.4, 'SA': 4.1, 'TAS': 4.3, 'ACT': 2.9, 'NT': 3.6},
        '2024Q1': {'NSW': 3.5, 'VIC': 3.9, 'QLD': 4.0, 'WA': 3.5, 'SA': 4.2, 'TAS': 4.4, 'ACT': 3.0, 'NT': 3.7},
        '2024Q2': {'NSW': 3.8, 'VIC': 4.2, 'QLD': 4.2, 'WA': 3.7, 'SA': 4.5, 'TAS': 4.6, 'ACT': 3.2, 'NT': 3.9},
        '2024Q3': {'NSW': 4.0, 'VIC': 4.5, 'QLD': 4.3, 'WA': 3.8, 'SA': 4.7, 'TAS': 4.8, 'ACT': 3.3, 'NT': 4.0},
        '2024Q4': {'NSW': 4.1, 'VIC': 4.6, 'QLD': 4.2, 'WA': 3.7, 'SA': 4.6, 'TAS': 4.7, 'ACT': 3.2, 'NT': 3.9},
        '2025Q1': {'NSW': 4.0, 'VIC': 4.4, 'QLD': 4.0, 'WA': 3.5, 'SA': 4.4, 'TAS': 4.5, 'ACT': 3.0, 'NT': 3.7},
        '2025Q2': {'NSW': 3.8, 'VIC': 4.2, 'QLD': 3.8, 'WA': 3.3, 'SA': 4.2, 'TAS': 4.3, 'ACT': 2.9, 'NT': 3.5},
        '2025Q3': {'NSW': 3.6, 'VIC': 4.0, 'QLD': 3.7, 'WA': 3.2, 'SA': 4.0, 'TAS': 4.1, 'ACT': 2.8, 'NT': 3.4},
        '2025Q4': {'NSW': 3.5, 'VIC': 3.8, 'QLD': 3.5, 'WA': 3.0, 'SA': 3.8, 'TAS': 3.9, 'ACT': 2.7, 'NT': 3.3},
        '2026Q1': {'NSW': 3.4, 'VIC': 3.7, 'QLD': 3.4, 'WA': 2.9, 'SA': 3.7, 'TAS': 3.8, 'ACT': 2.6, 'NT': 3.2},
        '2026Q2': {'NSW': 3.3, 'VIC': 3.6, 'QLD': 3.3, 'WA': 2.8, 'SA': 3.6, 'TAS': 3.7, 'ACT': 2.5, 'NT': 3.1},
    }

    # Westpac-Melbourne Institute Consumer Confidence Index (100 = neutral)
    CONSUMER_CONFIDENCE = {
        '2023Q3': 79.7, '2023Q4': 82.0,
        '2024Q1': 84.5, '2024Q2': 82.2, '2024Q3': 84.6, '2024Q4': 86.8,
        '2025Q1': 92.2, '2025Q2': 95.5, '2025Q3': 96.0, '2025Q4': 97.5,
        '2026Q1': 98.0, '2026Q2': 99.0,
    }

    # Quarter start dates for generating application_date within each quarter
    _QUARTER_START_DATES = {
        '2023Q3': date(2023, 7, 1), '2023Q4': date(2023, 10, 1),
        '2024Q1': date(2024, 1, 1), '2024Q2': date(2024, 4, 1),
        '2024Q3': date(2024, 7, 1), '2024Q4': date(2024, 10, 1),
        '2025Q1': date(2025, 1, 1), '2025Q2': date(2025, 4, 1),
        '2025Q3': date(2025, 7, 1), '2025Q4': date(2025, 10, 1),
        '2026Q1': date(2026, 1, 1), '2026Q2': date(2026, 4, 1),
    }

    # Seasonal application volume weights.
    _QUARTER_SEASON_WEIGHTS = {
        'Q1': 1.15, 'Q2': 0.80, 'Q3': 0.95, 'Q4': 1.10,
    }
    # Monthly seasonal weights (ABS Lending Indicators).
    # Peaks Oct-Feb (spring/summer auction season), troughs Jun-Jul (winter).
    _MONTH_SEASON_WEIGHTS = {
        1: 1.10, 2: 1.15, 3: 1.05, 4: 0.90, 5: 0.85, 6: 0.75,
        7: 0.78, 8: 0.88, 9: 0.95, 10: 1.10, 11: 1.20, 12: 1.05,
    }
    _RATE_CUT_BOOST_QUARTERS = {'2025Q1', '2025Q3', '2026Q1'}

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

    # =================================================================
    # Behavioral realism methods (Phase 1 & 2)
    # =================================================================

    def _apply_round_number_bias(self, loan_amount, rng):
        """Apply round-number bias to loan amounts (MIT/Wharton research).

        65% round to nearest $5K, 22% to nearest $1K, 13% keep as-is.
        """
        n = len(loan_amount)
        tier_roll = rng.random(n)
        rounded = np.where(
            tier_roll < 0.65,
            np.round(loan_amount / 5000) * 5000,
            np.where(
                tier_roll < 0.87,
                np.round(loan_amount / 1000) * 1000,
                np.round(loan_amount / 100) * 100,
            ),
        )
        return rounded

    def _assign_application_channel(self, age, purpose, sub_pop, rng):
        """Assign application channel (digital/mobile/branch/broker).

        77% of AU mortgages via brokers; personal loans mostly digital.
        Age adjustments: <30 digital+, >50 branch+.
        Vectorized implementation using numpy broadcasting.
        """
        n = len(age)
        is_home = purpose == 'home'

        # Base weights: [digital, mobile, branch, broker]
        # Start with non-home defaults, override for home loans
        w_digital = np.where(is_home, 0.15, 0.55)
        w_mobile = np.where(is_home, 0.05, 0.20)
        w_branch = np.where(is_home, 0.05, 0.18)
        w_broker = np.where(is_home, 0.75, 0.07)

        # Age adjustments
        young = age < 30
        old = age > 50
        w_digital = np.where(young, w_digital + 0.10, np.where(old, w_digital - 0.10, w_digital))
        w_mobile = np.where(young, w_mobile + 0.05, np.where(old, w_mobile - 0.05, w_mobile))
        w_branch = np.where(young, w_branch - 0.10, np.where(old, w_branch + 0.10, w_branch))
        w_broker = np.where(young, w_broker - 0.05, np.where(old, w_broker + 0.05, w_broker))

        # Clip and normalize
        w_digital = np.clip(w_digital, 0.01, None)
        w_mobile = np.clip(w_mobile, 0.01, None)
        w_branch = np.clip(w_branch, 0.01, None)
        w_broker = np.clip(w_broker, 0.01, None)
        w_total = w_digital + w_mobile + w_branch + w_broker
        w_digital /= w_total
        w_mobile /= w_total
        w_branch /= w_total
        w_broker /= w_total

        # Vectorized sampling using cumulative thresholds
        roll = rng.random(n)
        cum1 = w_digital
        cum2 = cum1 + w_mobile
        cum3 = cum2 + w_branch

        channel = np.where(
            roll < cum1, 'digital',
            np.where(roll < cum2, 'mobile',
                np.where(roll < cum3, 'branch', 'broker'))
        )
        return channel

    def _apply_income_inflation(self, annual_income, employment_type, is_fraud_signal, rng):
        """Apply strategic income inflation (ASIC v Westpac research).

        7% base inflation rate; self-employed 3x (21%), casual 1.5x (10.5%).
        Magnitude: 70% mild (1.05-1.15x), 25% moderate (1.15-1.25x), 5% severe (1.25-1.40x).
        """
        n = len(annual_income)
        inflation_prob = np.full(n, 0.07)
        inflation_prob[employment_type == 'self_employed'] = 0.21
        inflation_prob[employment_type == 'payg_casual'] = 0.105
        inflation_prob[is_fraud_signal == 1] = 0.80

        is_inflator = rng.random(n) < inflation_prob

        # Magnitude tiers
        magnitude_roll = rng.random(n)
        multiplier = np.where(
            magnitude_roll < 0.70, rng.uniform(1.05, 1.15, size=n),
            np.where(magnitude_roll < 0.95, rng.uniform(1.15, 1.25, size=n),
                rng.uniform(1.25, 1.40, size=n))
        )

        true_income = annual_income.copy()
        inflated_income = annual_income.copy()
        inflated_income[is_inflator] = (annual_income[is_inflator] * multiplier[is_inflator]).round(2)

        # income_verification_gap = stated / verified
        verification_gap = np.where(is_inflator, inflated_income / true_income, 1.0).round(2)

        return inflated_income, true_income, verification_gap

    def _apply_optimism_bias(self, loan_amount, age, sub_pop, rng):
        """Apply optimism bias — borrowers request more than capacity (Philadelphia Fed).

        27% base rate; age <30: 40%, FHB: 1.3x, refinancer: 0.6x.
        Optimists request 10-25% more than capacity.
        """
        n = len(loan_amount)
        base_prob = np.full(n, 0.27)
        base_prob[age < 30] = 0.40
        base_prob[(age >= 30) & (age < 40)] = 0.32
        base_prob[age >= 50] = 0.19

        # Sub-population adjustments
        base_prob[sub_pop == 'first_home_buyer'] *= 1.3
        base_prob[sub_pop == 'refinancer'] *= 0.6
        base_prob = np.clip(base_prob, 0, 0.60)

        is_optimist = rng.random(n) < base_prob

        # Optimists request 10-25% more
        boost = rng.uniform(1.10, 1.25, size=n)
        adjusted_amount = loan_amount.copy()
        adjusted_amount[is_optimist] = (loan_amount[is_optimist] * boost[is_optimist]).round(2)

        return adjusted_amount, is_optimist.astype(int)

    def _assign_financial_literacy(self, age, credit_score, sub_pop, rng):
        """Assign financial literacy score (ANZ Survey).

        Beta(4,4) base; age <25: -0.15, credit >900: +0.10, business: +0.10.
        """
        n = len(age)
        base = rng.beta(4, 4, size=n)

        # Age adjustments (ANZ Survey)
        base[age < 25] -= 0.15
        base[(age >= 25) & (age < 35)] -= 0.05
        base[(age >= 35) & (age < 50)] += 0.05
        base[age >= 50] += 0.10

        # Credit score correlation
        base[credit_score > 900] += 0.10
        base[credit_score < 700] -= 0.10

        # Business borrowers tend to be more literate
        base[sub_pop == 'business_borrower'] += 0.10

        return np.clip(base, 0.05, 0.95).round(2)

    def _compute_prepayment_buffer(self, df, rng):
        """Compute prepayment buffer and negative equity flag (RBA RDP 2020-03).

        Buffer distribution: <1mo: 8%, 1-3: 12%, 3-6: 10%, 6-12: 25%, 12+: 45%.
        """
        n = len(df)
        buffer_tier = rng.choice(
            ['very_low', 'low', 'medium', 'high', 'very_high'],
            size=n, p=[0.08, 0.12, 0.10, 0.25, 0.45],
        )
        buffer_months = np.where(
            buffer_tier == 'very_low', rng.uniform(0, 1, size=n),
            np.where(buffer_tier == 'low', rng.uniform(1, 3, size=n),
                np.where(buffer_tier == 'medium', rng.uniform(3, 6, size=n),
                    np.where(buffer_tier == 'high', rng.uniform(6, 12, size=n),
                        rng.uniform(12, 36, size=n))))).round(1)

        # Correlate with credit score
        credit_norm = np.clip((df['credit_score'].values - 650) / 400, 0, 1)
        buffer_months = buffer_months * (0.5 + credit_norm)
        buffer_months = np.clip(buffer_months, 0, 60).round(1)

        # Negative equity flag (home loans only)
        is_home = df['purpose'] == 'home'
        property_growth = df.get('property_growth_12m', pd.Series(np.zeros(n))).values
        lvr = np.where(
            df['property_value'] > 0,
            df['loan_amount'] / df['property_value'],
            0.0,
        )
        # After 12 months of property growth, what's the effective LVR?
        effective_lvr = lvr / (1 + property_growth / 100)
        negative_equity = (is_home & (effective_lvr > 1.0)).astype(int)

        return buffer_months, negative_equity

    def _assign_life_event_trigger(self, purpose, sub_pop, rng):
        """Assign life event trigger for the loan application.

        Personal: debt_consolidation 35%, etc.  Home: by sub-population.
        Business: expansion/equipment/working_capital/startup.
        """
        n = len(purpose)
        triggers = np.full(n, 'other', dtype='<U25')

        personal_mask = np.isin(purpose, ['personal', 'auto', 'education'])
        home_mask = purpose == 'home'
        business_mask = purpose == 'business'

        # Personal loans
        personal_events = ['debt_consolidation', 'home_improvement', 'major_purchase',
                           'medical', 'wedding', 'travel', 'moving_costs', 'other']
        personal_weights = [0.35, 0.15, 0.12, 0.10, 0.08, 0.07, 0.05, 0.08]
        if personal_mask.sum() > 0:
            triggers[personal_mask] = rng.choice(personal_events, size=personal_mask.sum(), p=personal_weights)

        # Override for auto/education
        triggers[purpose == 'auto'] = 'vehicle_purchase'
        triggers[purpose == 'education'] = 'education'

        # Home loans by sub-population
        fhb_mask = home_mask & (sub_pop == 'first_home_buyer')
        upgrader_mask = home_mask & (sub_pop == 'upgrader')
        refinancer_mask = home_mask & (sub_pop == 'refinancer')
        investor_mask = home_mask & (sub_pop == 'investor')
        triggers[fhb_mask] = 'purchase'
        if upgrader_mask.sum() > 0:
            triggers[upgrader_mask] = rng.choice(
                ['purchase', 'renovation'], size=upgrader_mask.sum(), p=[0.80, 0.20]
            )
        triggers[refinancer_mask] = 'refinance'
        triggers[investor_mask] = 'investment_purchase'

        # Business loans
        business_events = ['expansion', 'equipment', 'working_capital', 'startup']
        business_weights = [0.30, 0.25, 0.30, 0.15]
        if business_mask.sum() > 0:
            triggers[business_mask] = rng.choice(business_events, size=business_mask.sum(), p=business_weights)

        return triggers

    def generate(self, num_records=50000, random_seed=42, label_noise_rate=0.05):
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

        # =============================================================
        # STEP 0b: Temporal dimension — 36-month application window
        # Uses monthly seasonal weights (ABS Lending Indicators) for
        # more granular seasonality than the legacy quarterly weights.
        # =============================================================
        quarters = list(self.RBA_RATE_HISTORY.keys())

        # Build month-level weight list from the quarter range
        # Each quarter has 3 months; combine monthly season weight
        # with rate-cut boost from the parent quarter.
        _month_entries = []  # list of (year, month, quarter_key, weight)
        for q_key in quarters:
            year = int(q_key[:4])
            q_num = int(q_key[-1])
            rate_boost = 1.20 if q_key in self._RATE_CUT_BOOST_QUARTERS else 1.0
            for m_offset in range(3):
                month = (q_num - 1) * 3 + 1 + m_offset
                w = self._MONTH_SEASON_WEIGHTS[month] * rate_boost
                _month_entries.append((year, month, q_key, w))

        month_weights = np.array([e[3] for e in _month_entries])
        month_weights /= month_weights.sum()

        month_idx = rng.choice(len(_month_entries), size=n, p=month_weights)
        # Derive application_date: random day within each selected month
        application_date = []
        for idx in month_idx:
            year, month, _, _ = _month_entries[idx]
            # Days in this month (28-31)
            if month == 12:
                days_in_month = (date(year + 1, 1, 1) - date(year, month, 1)).days
            else:
                days_in_month = (date(year, month + 1, 1) - date(year, month, 1)).days
            day_offset = int(rng.integers(0, days_in_month))
            application_date.append(date(year, month, 1) + timedelta(days=day_offset))
        application_date = np.array(application_date, dtype='datetime64[D]')

        # Derive application_quarter from the month entries (backward compat)
        application_quarter = np.array([_month_entries[i][2] for i in month_idx])

        # Macro lookups from quarter
        rba_cash_rate = np.array([self.RBA_RATE_HISTORY[q] for q in application_quarter])
        unemployment_rate = np.array([
            self.UNEMPLOYMENT_RATES[q][s] for q, s in zip(application_quarter, state)
        ])
        property_growth_12m = np.array([
            self.PROPERTY_GROWTH[q][s] for q, s in zip(application_quarter, state)
        ])
        consumer_confidence = np.array([self.CONSUMER_CONFIDENCE[q] for q in application_quarter])

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
            # Lognormal sigma: higher = more spread. Couples have wider spread
            # because partner incomes vary (full-time + part-time, parental leave,
            # single-income households applying as couple for guarantee purposes).
            inc_sigma = np.where(is_couple, 0.50, 0.55)
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
        # Beta distribution scaled to produce ~6% of applicants with total DTI>=6
        # (APRA Sep Q 2025: 6.1% of new lending). Home buyers carry less existing
        # debt (buying their main asset) while personal/business borrowers more.
        existing_dti = np.where(
            is_home,
            np.clip(rng.beta(a=2.0, b=4.5, size=n) * 1.4, 0, 1.4),
            np.clip(rng.beta(a=2.0, b=4.0, size=n) * 2.0, 0, 2.0),
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
        # Phase 1A: Round number bias (MIT/Wharton research)
        loan_amount = self._apply_round_number_bias(loan_amount, rng)
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

        # Monthly rent paid (for renters) — demonstrates repayment capacity
        # ABS 2025: national median weekly rent ~$580 ($2,515/month)
        # Sydney ~$750/wk ($3,250/mo), regional ~$400/wk ($1,735/mo)
        state_rent_mult = np.array([
            {'NSW': 1.30, 'VIC': 1.10, 'QLD': 1.00, 'WA': 1.05,
             'SA': 0.85, 'TAS': 0.80, 'ACT': 1.15, 'NT': 0.90}[s] for s in state
        ])
        monthly_rent = np.where(
            home_ownership == 'rent',
            np.clip(rng.lognormal(mean=np.log(2200), sigma=0.3, size=n) * state_rent_mult, 800, 6000).round(0),
            0.0,
        )

        # --- HECS/HELP debt (ATO compulsory repayment at ~3.5% of gross) ---
        # ATO 2022-23: ~3 million Australians have HECS debt.
        # ~40% of borrowers under 55 carry HECS (skews younger: ~55% under 35).
        hecs_rate = np.where(age_proxy < 35, 0.55, np.where(age_proxy < 55, 0.30, 0.05))
        has_hecs = (rng.random(n) < hecs_rate).astype(int)

        # HECS-HELP debt balance (ATO 2025: avg outstanding ~$22,000 post-indexation cut)
        # Only for applicants with has_hecs == 1
        hecs_debt_balance = np.where(
            has_hecs == 1,
            np.clip(rng.lognormal(mean=np.log(22000), sigma=0.6, size=n), 5000, 120000).round(0),
            0.0,
        )

        # --- Bankruptcy (hard disqualifier) ---
        # AFSA 2024-25: ~12,000 personal insolvencies/yr on ~20M adults ≈ 0.06%.
        # But cumulative (discharged within 7 years still visible on bureau):
        # ~1.5-2% of population have a bankruptcy flag. Loan applicants with
        # bankruptcy mostly self-select out, so ~1% of applicants carry the flag.
        has_bankruptcy = rng.choice([0, 1], size=n, p=[0.99, 0.01])

        # Existing property count — 65% own 0, 25% own 1, 8% own 2, 2% own 3+
        # Investors always own at least 1
        property_count_base = np.digitize(rng.random(n), [0.65, 0.90, 0.98])
        # Investors must own >= 1
        investor_mask = sub_pop == 'investor'
        property_count_base[investor_mask] = np.clip(property_count_base[investor_mask], 1, 5)
        # Upgraders likely own 1
        upgrader_mask = sub_pop == 'upgrader'
        property_count_base[upgrader_mask] = np.where(
            rng.random(upgrader_mask.sum()) < 0.85, 1, property_count_base[upgrader_mask]
        )
        existing_property_count = property_count_base

        # =============================================================
        # BUREAU FEATURES: correlated with credit score
        # =============================================================
        credit_norm = (credit_score - 300) / 900  # 0-1 scale

        # Number of credit enquiries in last 6 months
        # Equifax: avg 1.2 enquiries/6m for good borrowers, 3.5+ for subprime
        enquiry_lambda = np.where(credit_norm > 0.7, 0.8, np.where(credit_norm > 0.4, 1.5, 3.5))
        num_credit_enquiries_6m = rng.poisson(enquiry_lambda)

        # Worst arrears in last 24 months (0, 1, 2, 3+ months)
        arrears_u = rng.random(n)
        worst_arrears_months = np.where(
            credit_norm > 0.7,
            np.where(arrears_u < 0.97, 0, np.where(arrears_u < 0.99, 1, np.where(arrears_u < 0.998, 2, 3))),
            np.where(credit_norm > 0.4,
                np.where(arrears_u < 0.88, 0, np.where(arrears_u < 0.96, 1, np.where(arrears_u < 0.99, 2, 3))),
                np.where(arrears_u < 0.70, 0, np.where(arrears_u < 0.85, 1, np.where(arrears_u < 0.95, 2, 3))))
        )

        # Number of defaults in last 5 years
        default_u = rng.random(n)
        num_defaults_5yr = np.where(
            credit_norm > 0.6, 0,
            np.where(default_u < 0.90, 0, np.where(default_u < 0.97, 1, np.where(default_u < 0.99, 2, 3)))
        )
        num_defaults_5yr[has_bankruptcy == 1] = np.clip(num_defaults_5yr[has_bankruptcy == 1] + 1, 1, 5)

        # Credit history length in months (correlated with age)
        credit_history_months = np.clip(
            ((age_proxy - 18) * 12 * rng.uniform(0.3, 0.9, size=n)).astype(int),
            0, 480
        )

        # Total open accounts (correlated with income and age)
        total_open_accounts = np.clip(
            rng.poisson(np.where(annual_income > 100000, 5.0, np.where(annual_income > 60000, 3.5, 2.0))),
            0, 15
        )

        # BNPL accounts (skews younger, ASIC 2025 focus area)
        bnpl_base_prob = np.where(age_proxy < 30, 0.55, np.where(age_proxy < 40, 0.35, np.where(age_proxy < 50, 0.15, 0.05)))
        has_bnpl = rng.random(n) < bnpl_base_prob
        num_bnpl_accounts = np.where(has_bnpl, rng.choice([1, 2, 3, 4], size=n, p=[0.45, 0.30, 0.15, 0.10]), 0)

        # Cash advance / payday loan count (12m) — strong negative signal
        # Most borrowers: 0; subprime: 1-3+
        cash_advance_count_12m = np.where(
            credit_norm > 0.6, 0,
            np.where(rng.random(n) < 0.15,
                rng.choice([1, 2, 3, 4, 5], size=n, p=[0.50, 0.25, 0.15, 0.07, 0.03]),
                0)
        )

        # =============================================================
        # BEHAVIOURAL SCORE: existing customers (~40%) have internal data
        # =============================================================
        is_existing_customer = (rng.random(n) < 0.40).astype(int)

        savings_balance = np.where(
            is_existing_customer == 1,
            np.clip(rng.lognormal(mean=np.log(15000), sigma=1.2, size=n) * (credit_norm * 0.7 + 0.3), 100, 500000),
            np.nan
        )
        salary_credit_regularity = np.where(
            is_existing_customer == 1,
            np.clip(rng.beta(8, 2, size=n), 0, 1),
            np.nan
        )
        num_dishonours_12m = np.where(
            is_existing_customer == 1,
            np.where(credit_norm > 0.6, rng.choice([0, 0, 0, 0, 1], size=n), rng.choice([0, 0, 1, 1, 2, 3], size=n)),
            np.nan
        ).astype(float)
        avg_monthly_savings_rate = np.where(
            is_existing_customer == 1,
            np.clip(rng.normal(0.12, 0.08, size=n) + credit_norm * 0.05, -0.10, 0.50),
            np.nan
        )
        days_in_overdraft_12m = np.where(
            is_existing_customer == 1,
            np.where(credit_norm > 0.6, rng.choice([0, 0, 0, 0, 0, 1, 2, 3], size=n), rng.choice([0, 0, 5, 10, 15, 20, 30, 45], size=n)),
            np.nan
        ).astype(float)

        # =============================================================
        # FRAUD SIGNALS: ~2% of applications (APRA/ASIC focus area)
        # =============================================================
        is_fraud_signal = (rng.random(n) < 0.02).astype(int)

        income_verification_gap = np.where(
            is_fraud_signal == 1,
            rng.uniform(1.20, 2.00, size=n),
            np.clip(rng.normal(1.0, 0.03, size=n), 0.90, 1.10)
        ).round(3)

        address_tenure_months = np.where(
            is_fraud_signal == 1,
            rng.choice([1, 2, 3, 4, 5, 6], size=n),
            np.clip((rng.exponential(36, size=n)).astype(int), 1, 360)
        )

        document_consistency_score = np.where(
            is_fraud_signal == 1,
            np.clip(rng.normal(0.35, 0.15, size=n), 0.0, 0.60),
            np.clip(rng.beta(8, 2, size=n), 0.5, 1.0)
        ).round(3)

        # === Open Banking Features (Plaid/Basiq-inspired simulation) ===

        # Savings trend: correlated with income surplus and age
        surplus = annual_income / 12 - monthly_expenses
        savings_prob = np.clip(surplus / 3000, 0.1, 0.9)
        savings_roll = rng.random(n)
        ob_savings_trend_3m = np.where(
            savings_roll < savings_prob * 0.6, 'positive',
            np.where(savings_roll < savings_prob * 0.6 + 0.3, 'flat', 'negative')
        )

        # Discretionary spend ratio: younger people spend more on discretionary
        age_factor = np.clip((age_proxy - 20) / 40, 0, 1)
        ob_discretionary_spend_ratio = np.clip(
            rng.beta(3, 5, size=n) + (1 - age_factor) * 0.15, 0.05, 0.85
        ).round(2)

        # Gambling spend-to-income ratio (CDR) — Roy Morgan 2025 tiered data
        # 2.9% problem, 5.8% moderate, 7.5% low risk
        # Age multipliers: 25-34 → 1.7x, 18-24 → 1.4x, 35-49 → 1.0x, 50+ → 0.6x
        age_gambling_mult = np.where(age_proxy < 25, 1.4,
            np.where(age_proxy < 35, 1.7,
                np.where(age_proxy < 50, 1.0, 0.6)))
        # State multipliers
        state_gambling_mult = np.ones(n)
        for s, m in {'NSW': 1.15, 'NT': 1.20, 'VIC': 1.05, 'QLD': 1.00,
                      'WA': 0.95, 'SA': 0.90, 'TAS': 0.85, 'ACT': 0.90}.items():
            state_gambling_mult[state == s] = m

        gambling_roll = rng.random(n)
        problem_thresh = 0.029 * age_gambling_mult * state_gambling_mult
        moderate_thresh = problem_thresh + 0.058 * age_gambling_mult * state_gambling_mult
        low_thresh = moderate_thresh + 0.075 * age_gambling_mult * state_gambling_mult

        gambling_spend_ratio = np.where(
            gambling_roll < problem_thresh,
            np.clip(rng.uniform(0.05, 0.15, size=n), 0.05, 0.15),
            np.where(gambling_roll < moderate_thresh,
                np.clip(rng.uniform(0.02, 0.05, size=n), 0.02, 0.05),
                np.where(gambling_roll < low_thresh,
                    np.clip(rng.uniform(0.005, 0.02, size=n), 0.005, 0.02),
                    0.0))
        ).round(4)
        has_gambling = gambling_spend_ratio > 0
        ob_gambling_transaction_flag = has_gambling

        # BNPL active count: correlated with age and credit utilization
        bnpl_lambda = np.where(age_proxy < 35, 1.5, 0.5) * np.where(credit_score < 700, 1.3, 0.8)
        ob_bnpl_active_count = np.clip(rng.poisson(bnpl_lambda), 0, 8)

        # Overdraft frequency: correlated with low savings and high expenses
        financial_stress = np.clip((monthly_expenses * 12 / annual_income - 0.5) * 5, 0, 3)
        ob_overdraft_frequency_90d = np.clip(rng.poisson(financial_stress), 0, 15)

        # Income verification score: how closely declared income matches observed
        income_noise_ob = np.abs(rng.normal(0, 0.08, size=n))
        se_noise = np.where(employment_type == 'self_employed', 0.12, 0)
        ob_income_verification_score = np.clip(1.0 - income_noise_ob - se_noise, 0.3, 1.0).round(2)

        # =============================================================
        # CCR (Comprehensive Credit Reporting) features
        # Mandatory since 2018 — all credit providers report positive+negative data
        # =============================================================
        # credit_norm already defined above — reuse it

        # Late payments: inversely correlated with credit score
        late_pay_lambda = np.where(credit_norm > 0.7, 0.2, np.where(credit_norm > 0.4, 1.5, 4.0))
        ccr_num_late_payments_24m = np.clip(rng.poisson(late_pay_lambda), 0, 20)

        # Worst late payment days: correlated with num late payments
        worst_late_buckets = [0, 14, 30, 60, 90]
        worst_late_probs_good = [0.85, 0.08, 0.04, 0.02, 0.01]
        worst_late_probs_bad = [0.20, 0.15, 0.25, 0.20, 0.20]
        worst_late_probs = np.where(
            credit_norm[:, None] > 0.6,
            np.tile(worst_late_probs_good, (n, 1)),
            np.tile(worst_late_probs_bad, (n, 1)),
        )
        ccr_worst_late_payment_days = np.array([
            rng.choice(worst_late_buckets, p=p) for p in worst_late_probs
        ])

        # Total credit limit: correlated with income
        ccr_total_credit_limit = np.clip(
            rng.lognormal(mean=np.log(annual_income * 0.3), sigma=0.5, size=n),
            1000, 500000
        ).round(2)

        # Credit utilization: inversely correlated with credit score
        ccr_credit_utilization_pct = np.clip(
            rng.beta(2, 5, size=n) + (1 - credit_norm) * 0.3, 0.0, 1.0
        ).round(3)

        # Hardship flags (CCR since Jul 2022): rare but impactful
        hardship_prob = np.where(credit_norm > 0.6, 0.02, np.where(credit_norm > 0.3, 0.08, 0.18))
        ccr_num_hardship_flags = np.where(rng.random(n) < hardship_prob, rng.choice([1, 2, 3], size=n, p=[0.7, 0.2, 0.1]), 0)

        # Months since last default: NaN if no defaults
        has_default = num_defaults_5yr > 0
        ccr_months_since_last_default = np.where(
            has_default,
            np.clip(rng.exponential(24, size=n).astype(int), 1, 60),
            np.nan
        ).astype(float)

        # Number of credit providers
        ccr_num_credit_providers = np.clip(
            rng.poisson(np.where(credit_norm > 0.5, 3, 2), size=n), 1, 15
        )

        # =============================================================
        # BNPL-specific features (NCCP Act regulation since June 2025)
        # =============================================================
        has_bnpl_mask = num_bnpl_accounts > 0
        ccr_bnpl_total_limit = np.where(
            has_bnpl_mask,
            np.clip(num_bnpl_accounts * rng.uniform(500, 2000, size=n), 0, 15000),
            0
        ).round(2)

        ccr_bnpl_utilization_pct = np.where(
            has_bnpl_mask,
            np.clip(rng.beta(3, 4, size=n), 0, 1),
            0
        ).round(3)

        ccr_bnpl_late_payments_12m = np.where(
            has_bnpl_mask,
            np.where(credit_norm > 0.6, rng.choice([0, 0, 0, 1], size=n), rng.choice([0, 1, 2, 3], size=n)),
            0
        )

        ccr_bnpl_monthly_commitment = np.where(
            has_bnpl_mask,
            np.clip(ccr_bnpl_total_limit * rng.uniform(0.05, 0.15, size=n), 0, 2000),
            0
        ).round(2)

        # =============================================================
        # CDR/Open Banking transaction features (Consumer Data Right)
        # =============================================================
        # Income source count: self-employed tend to have more sources
        cdr_income_source_count = np.where(
            employment_type == 'self_employed',
            rng.choice([1, 2, 3, 4], size=n, p=[0.15, 0.35, 0.30, 0.20]),
            rng.choice([1, 2, 3], size=n, p=[0.65, 0.25, 0.10])
        )

        # Rent payment regularity: higher for good credit, NaN for owners
        is_renter = np.array([h == 'rent' for h in home_ownership])
        cdr_rent_payment_regularity = np.where(
            is_renter,
            np.clip(rng.beta(8, 2, size=n) * (credit_norm * 0.3 + 0.7), 0.3, 1.0),
            np.nan
        ).astype(float)

        # Utility payment regularity
        cdr_utility_payment_regularity = np.clip(
            rng.beta(9, 2, size=n) * (credit_norm * 0.2 + 0.8), 0.4, 1.0
        ).round(2)

        # Essential to total spend ratio
        cdr_essential_to_total_spend = np.clip(
            rng.beta(5, 4, size=n) + number_of_dependants * 0.03, 0.20, 0.90
        ).round(3)

        # Subscription burden: recurring subscriptions / monthly income
        cdr_subscription_burden = np.clip(
            rng.lognormal(mean=np.log(0.04), sigma=0.6, size=n),
            0.005, 0.30
        ).round(4)

        # Balance before payday: 3-day pre-salary balance
        cdr_balance_before_payday = np.clip(
            rng.lognormal(mean=np.log(2000), sigma=1.2, size=n) * (credit_norm * 0.6 + 0.4),
            -500, 50000
        ).round(2)

        # Minimum balance in last 30 days
        cdr_min_balance_30d = np.clip(
            cdr_balance_before_payday * rng.uniform(0.1, 0.8, size=n),
            -2000, 40000
        ).round(2)

        # Days with negative balance in 90 days
        neg_bal_lambda = np.where(credit_norm > 0.7, 0.3, np.where(credit_norm > 0.4, 2.0, 6.0))
        cdr_days_negative_balance_90d = np.clip(rng.poisson(neg_bal_lambda), 0, 90)

        # =============================================================
        # Geographic risk features
        # =============================================================
        # Postcode default rate: state-based baseline with noise
        state_default_rates = {
            'NSW': 0.012, 'VIC': 0.013, 'QLD': 0.016, 'WA': 0.015,
            'SA': 0.014, 'TAS': 0.011, 'ACT': 0.008, 'NT': 0.020,
        }
        geo_postcode_default_rate = np.array([
            state_default_rates.get(s, 0.015) for s in state
        ]) + rng.normal(0, 0.003, size=n)
        geo_postcode_default_rate = np.clip(geo_postcode_default_rate, 0.002, 0.05).round(4)

        # Industry risk tier
        geo_industry_risk_tier = rng.choice(
            ['low', 'medium', 'high', 'very_high'],
            size=n, p=[0.40, 0.35, 0.18, 0.07]
        )

        # =============================================================
        # Phase 2: Behavioral realism features
        # Spawn child RNGs to avoid changing existing random sequences.
        # =============================================================
        behavioral_rngs = rng.spawn(6)

        # 2A. Application channel
        application_channel = self._assign_application_channel(
            age_proxy, purpose, sub_pop, behavioral_rngs[0]
        )

        # 2B. Strategic income inflation (before measurement noise)
        inflated_income, _true_income, strategic_gap = self._apply_income_inflation(
            annual_income, employment_type, is_fraud_signal, behavioral_rngs[1]
        )
        # Replace annual_income with inflated version; update verification gap
        # for inflators (keep fraud signal gaps from the original generation)
        is_strategic_inflator = strategic_gap > 1.0
        annual_income = inflated_income
        income_verification_gap = np.where(
            is_strategic_inflator & (is_fraud_signal == 0),
            strategic_gap,
            income_verification_gap,
        )

        # 2C. Optimism bias (after round number bias, before DTI)
        loan_amount, optimism_bias_flag = self._apply_optimism_bias(
            loan_amount, age_proxy, sub_pop, behavioral_rngs[2]
        )
        loan_amount = np.clip(loan_amount, 5000, 3500000)
        # Recalculate DTI after optimism bias
        new_loan_dti = loan_amount / annual_income
        debt_to_income = (existing_dti + new_loan_dti).round(2)

        # 2D. Financial literacy
        financial_literacy_score = self._assign_financial_literacy(
            age_proxy, credit_score, sub_pop, behavioral_rngs[3]
        )

        # 2F. Life event triggers
        loan_trigger_event = self._assign_life_event_trigger(
            purpose, sub_pop, behavioral_rngs[5]
        )

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
            'monthly_rent': monthly_rent,
            'number_of_dependants': number_of_dependants,
            'employment_type': employment_type,
            'applicant_type': applicant_type,
            'has_hecs': has_hecs,
            'hecs_debt_balance': hecs_debt_balance,
            'has_bankruptcy': has_bankruptcy,
            'existing_property_count': existing_property_count,
            'state': state,
            # Temporal dimension
            'application_quarter': application_quarter,
            'rba_cash_rate': rba_cash_rate,
            'unemployment_rate': unemployment_rate,
            'property_growth_12m': property_growth_12m,
            'consumer_confidence': consumer_confidence,
            # Bureau features
            'num_credit_enquiries_6m': num_credit_enquiries_6m,
            'worst_arrears_months': worst_arrears_months,
            'num_defaults_5yr': num_defaults_5yr,
            'credit_history_months': credit_history_months,
            'total_open_accounts': total_open_accounts,
            'num_bnpl_accounts': num_bnpl_accounts,
            'cash_advance_count_12m': cash_advance_count_12m,
            # Behavioural scores (NaN for non-existing customers)
            'is_existing_customer': is_existing_customer,
            'savings_balance': savings_balance,
            'salary_credit_regularity': salary_credit_regularity,
            'num_dishonours_12m': num_dishonours_12m,
            'avg_monthly_savings_rate': avg_monthly_savings_rate,
            'days_in_overdraft_12m': days_in_overdraft_12m,
            # Fraud signals
            'is_fraud_signal': is_fraud_signal,
            'income_verification_gap': income_verification_gap,
            'address_tenure_months': address_tenure_months,
            'document_consistency_score': document_consistency_score,
            # Open Banking features (Plaid/Basiq-inspired)
            'savings_trend_3m': ob_savings_trend_3m,
            'discretionary_spend_ratio': ob_discretionary_spend_ratio,
            'gambling_transaction_flag': ob_gambling_transaction_flag.astype(int),
            'gambling_spend_ratio': gambling_spend_ratio,
            'bnpl_active_count': ob_bnpl_active_count,
            'overdraft_frequency_90d': ob_overdraft_frequency_90d,
            'income_verification_score': ob_income_verification_score,
            # CCR features
            'num_late_payments_24m': ccr_num_late_payments_24m,
            'worst_late_payment_days': ccr_worst_late_payment_days,
            'total_credit_limit': ccr_total_credit_limit,
            'credit_utilization_pct': ccr_credit_utilization_pct,
            'num_hardship_flags': ccr_num_hardship_flags,
            'months_since_last_default': ccr_months_since_last_default,
            'num_credit_providers': ccr_num_credit_providers,
            # BNPL-specific
            'bnpl_total_limit': ccr_bnpl_total_limit,
            'bnpl_utilization_pct': ccr_bnpl_utilization_pct,
            'bnpl_late_payments_12m': ccr_bnpl_late_payments_12m,
            'bnpl_monthly_commitment': ccr_bnpl_monthly_commitment,
            # CDR/Open Banking transaction features
            'income_source_count': cdr_income_source_count,
            'rent_payment_regularity': cdr_rent_payment_regularity,
            'utility_payment_regularity': cdr_utility_payment_regularity,
            'essential_to_total_spend': cdr_essential_to_total_spend,
            'subscription_burden': cdr_subscription_burden,
            'balance_before_payday': cdr_balance_before_payday,
            'min_balance_30d': cdr_min_balance_30d,
            'days_negative_balance_90d': cdr_days_negative_balance_90d,
            # Geographic risk
            'postcode_default_rate': geo_postcode_default_rate,
            'industry_risk_tier': geo_industry_risk_tier,
            # Behavioral realism features
            'application_channel': application_channel,
            'optimism_bias_flag': optimism_bias_flag,
            'financial_literacy_score': financial_literacy_score,
            'loan_trigger_event': loan_trigger_event,
        }

        df = pd.DataFrame(data)
        # Store temporary columns for approval calculation (not model features)
        df['_existing_dti'] = existing_dti
        df['_age_proxy'] = age_proxy

        # --- Derived ratios (APRA stress test + Australian regulatory) ---
        _monthly_income = df['annual_income'] / 12.0
        _stressed_rate = (self.BASE_RATE + self.ASSESSMENT_BUFFER) / 12
        _term = df['loan_term_months'].clip(lower=1)
        df['stressed_repayment'] = np.where(
            _term > 0,
            df['loan_amount'] * _stressed_rate * (1 + _stressed_rate) ** _term
            / ((1 + _stressed_rate) ** _term - 1),
            0.0,
        )
        df['stressed_dsr'] = np.where(
            _monthly_income > 0,
            df['stressed_repayment'] / _monthly_income,
            0.0,
        )
        df['hem_surplus'] = _monthly_income - df['monthly_expenses'] - df['stressed_repayment']
        _cc_commit = df['existing_credit_card_limit'] * 0.03
        _bnpl_commit = df['bnpl_monthly_commitment']
        df['uncommitted_monthly_income'] = (
            _monthly_income - df['monthly_expenses'] - _cc_commit - _bnpl_commit - df['stressed_repayment']
        )
        df['savings_to_loan_ratio'] = np.where(
            df['loan_amount'] > 0,
            df['savings_balance'].fillna(0) / df['loan_amount'],
            0.0,
        )
        _total_debt_service = df['stressed_repayment'] + _cc_commit + _bnpl_commit
        df['debt_service_coverage'] = np.where(
            _total_debt_service > 0,
            _monthly_income / _total_debt_service,
            10.0,
        )
        df['bnpl_to_income_ratio'] = np.where(
            _monthly_income > 0,
            _bnpl_commit / _monthly_income,
            0.0,
        )
        df['enquiry_to_account_ratio'] = np.where(
            df['total_open_accounts'] > 0,
            df['num_credit_enquiries_6m'] / np.maximum(df['total_open_accounts'], 1),
            0.0,
        )
        df['stress_index'] = np.clip(
            df['credit_utilization_pct'].fillna(0.3) * 30
            + df['days_negative_balance_90d'] * 1.5
            + df['overdraft_frequency_90d'] * 3
            + df['stressed_dsr'] * 40,
            0, 100,
        )
        df['log_annual_income'] = np.log1p(df['annual_income'])
        df['log_loan_amount'] = np.log1p(df['loan_amount'])

        # Compute approval using TRUE values (banks verify documents)
        df['approved'] = self._compute_approval(df, rng)

        # 2E. Prepayment buffer + negative equity (computed after approval)
        buffer_months, neg_equity = self._compute_prepayment_buffer(df, behavioral_rngs[4])
        df['prepayment_buffer_months'] = buffer_months
        df['negative_equity_flag'] = neg_equity

        df.drop(columns=['_existing_dti', '_age_proxy'], inplace=True)

        # Default probability calibrated to real APRA/RBA/S&P statistics
        df['default_probability'] = self._calibrate_default_probability(df, rng)

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

        expense_noise = rng.normal(0.70, 0.15, size=n)  # ASIC: 30-50% under-reporting
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

        # HECS debt balance noise (~10% variance from self-reporting)
        if 'hecs_debt_balance' in df.columns:
            hecs_noise = rng.normal(1.0, 0.10, size=n)
            df['hecs_debt_balance'] = np.where(
                df['hecs_debt_balance'] > 0,
                np.clip((df['hecs_debt_balance'] * hecs_noise).round(0), 5000, 120000),
                0.0,
            )

        # Monthly rent noise (~5% variance)
        if 'monthly_rent' in df.columns:
            rent_noise = rng.normal(1.0, 0.05, size=n)
            df['monthly_rent'] = np.where(
                df['monthly_rent'] > 0,
                np.clip((df['monthly_rent'] * rent_noise).round(0), 800, 6000),
                0.0,
            )

        # Recalculate DTI with noisy income (model sees this, not true DTI)
        df['debt_to_income'] = (
            df['loan_amount'] / df['annual_income']
            + existing_dti * (annual_income / df['annual_income'])
        ).round(2)

        # =========================================================
        # MISSING DATA: Real applications have 10-15% missing on
        # optional fields. Higher-risk applicants skip fields more.
        # =========================================================
        # Monthly expenses: ~11% missing
        expense_missing = rng.random(n) < 0.11
        df.loc[expense_missing, 'monthly_expenses'] = np.nan

        # Credit card limit: ~8% missing
        cc_missing = rng.random(n) < 0.08
        df.loc[cc_missing, 'existing_credit_card_limit'] = np.nan

        # Property value: ~5% of home loans missing (pre-valuation)
        home_mask = df['purpose'] == 'home'
        pv_missing = home_mask & (rng.random(n) < 0.05)
        df.loc[pv_missing, 'property_value'] = np.nan
        df.loc[pv_missing, 'deposit_amount'] = np.nan

        # Bureau features: 8-12% missing for non-existing customers
        non_existing = df['is_existing_customer'] == 0
        bureau_cols = [
            'num_credit_enquiries_6m', 'worst_arrears_months',
            'num_defaults_5yr', 'credit_history_months',
            'total_open_accounts', 'num_bnpl_accounts',
        ]
        for col in bureau_cols:
            miss_rate = rng.uniform(0.08, 0.12)
            bureau_missing = non_existing & (rng.random(n) < miss_rate)
            df.loc[bureau_missing, col] = np.nan

        # Thin-file segment: short credit history → higher missing
        thin_file = df['credit_history_months'].notna() & (df['credit_history_months'] < 36)
        for col in bureau_cols:
            thin_miss = thin_file & (rng.random(n) < 0.25)
            df.loc[thin_miss, col] = np.nan

        # HECS debt balance: ~6% missing
        if 'hecs_debt_balance' in df.columns:
            hecs_missing = (df['hecs_debt_balance'] > 0) & (rng.random(n) < 0.06)
            df.loc[hecs_missing, 'hecs_debt_balance'] = np.nan

        # Monthly rent: ~7% missing for renters
        if 'monthly_rent' in df.columns:
            rent_missing = (df['monthly_rent'] > 0) & (rng.random(n) < 0.07)
            df.loc[rent_missing, 'monthly_rent'] = np.nan

        # Cash advance count: ~10% missing (sensitive disclosure)
        if 'cash_advance_count_12m' in df.columns:
            cash_adv_missing = rng.random(n) < 0.10
            df.loc[cash_adv_missing, 'cash_advance_count_12m'] = np.nan

        # Gambling spend ratio: ~12% missing (sensitive disclosure)
        if 'gambling_spend_ratio' in df.columns:
            gambling_missing = rng.random(n) < 0.12
            df.loc[gambling_missing, 'gambling_spend_ratio'] = np.nan

        # MNAR: low credit score → more likely to skip optional fields
        credit_norm_mnar = np.clip((df['credit_score'] - 300) / 900, 0, 1)
        mnar_prob = 0.08 * (1 - credit_norm_mnar)
        mnar_expense = (~expense_missing) & (rng.random(n) < mnar_prob)
        df.loc[mnar_expense, 'monthly_expenses'] = np.nan
        mnar_cc = (~cc_missing) & (rng.random(n) < mnar_prob)
        df.loc[mnar_cc, 'existing_credit_card_limit'] = np.nan

        # =========================================================
        # LABEL NOISE: ~5% of approved loans are false approvals.
        # Simulates borrowers who default within 6 months due to
        # factors invisible at application time. Concentrated on
        # borderline cases (higher default_probability).
        # =========================================================
        approved_mask = df['approved'] == 1
        n_approved = approved_mask.sum()
        if n_approved > 0:
            approved_dp = df.loc[approved_mask, 'default_probability'].values
            flip_weights = approved_dp / max(approved_dp.mean(), 1e-6) * label_noise_rate
            flip_weights = np.clip(flip_weights, 0.0, 0.25)
            flip_mask = rng.random(n_approved) < flip_weights
            flip_indices = df.index[approved_mask][flip_mask]
            df.loc[flip_indices, 'approved'] = 0

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
            # Parcelling method: heuristic without theoretical guarantees (PMC 2022).
            # Weights are configurable via class-level constants.
            credit_norm = np.clip((denied_credit - 650) / 400, 0, 1)
            dti_norm = np.clip(1 - denied_dti / 6.0, 0, 1)
            p_good = (
                self.REJECT_INFERENCE_CREDIT_WEIGHT * credit_norm
                + self.REJECT_INFERENCE_DTI_WEIGHT * dti_norm
            )

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

        # === Outcome Simulation (12-month post-approval backtesting) ===
        approved_mask = df['approved'] == 1

        # Base default probability: 1.5% (APRA NPL rate Sep Q 2025)
        base_pd = np.full(len(df), 0.015)

        # Risk multipliers (Equifax 2024, RBA FSR Oct 2025)
        base_pd = np.where(df['credit_score'] < 650, base_pd * 3.0, base_pd)
        base_pd = np.where(df['credit_score'] > 850, base_pd * 0.4, base_pd)
        base_pd = np.where(df['num_defaults_5yr'] > 0, base_pd * 2.5, base_pd)
        if 'stress_index' in df.columns:
            base_pd = np.where(df['stress_index'] > 60, base_pd * 2.5, base_pd)
        if 'overdraft_frequency_90d' in df.columns:
            base_pd = np.where(df['overdraft_frequency_90d'] > 5, base_pd * 2.0, base_pd)
        if 'gambling_transaction_flag' in df.columns:
            base_pd = np.where(df['gambling_transaction_flag'] == True, base_pd * 1.8, base_pd)
        if 'worst_late_payment_days' in df.columns:
            base_pd = np.where(df['worst_late_payment_days'] >= 60, base_pd * 2.0, base_pd)
        if 'bnpl_late_payments_12m' in df.columns:
            base_pd = np.where(df['bnpl_late_payments_12m'] > 2, base_pd * 1.5, base_pd)
        if 'savings_to_loan_ratio' in df.columns:
            base_pd = np.where(df['savings_to_loan_ratio'] > 0.3, base_pd * 0.6, base_pd)
        if 'debt_service_coverage' in df.columns:
            base_pd = np.where(df['debt_service_coverage'] > 2.0, base_pd * 0.5, base_pd)

        # Seasonal multiplier
        if 'quarter' in df.columns:
            base_pd = np.where(df['quarter'] == 1, base_pd * 1.3, base_pd)
            base_pd = np.where(df['quarter'] == 3, base_pd * 1.15, base_pd)
            base_pd = np.where(df['quarter'] == 4, base_pd * 0.95, base_pd)

        base_pd = np.clip(base_pd, 0.001, 0.50)

        # Roll outcomes for approved loans only
        outcome_roll = rng.random(len(df))
        prepaid_threshold = 0.035

        outcomes = np.where(
            ~approved_mask, None,
            np.where(outcome_roll < base_pd * 0.3, 'arrears_90',
            np.where(outcome_roll < base_pd * 0.6, 'arrears_60',
            np.where(outcome_roll < base_pd, 'arrears_30',
            np.where(outcome_roll < base_pd + prepaid_threshold, 'prepaid',
            'performing'))))
        )
        # Upgrade worst arrears to default
        default_roll = rng.random(len(df))
        outcomes = np.where(
            (outcomes == 'arrears_90') & (default_roll < 0.5), 'default', outcomes
        )

        # actual_outcome records the WORST state reached during the observation
        # window (ever-delinquent measure), not the end state. This is the
        # standard for credit risk modelling — a loan that was 60 days past due
        # and then cured still carries that signal. The "scarring effect" of
        # prior delinquency is one of the strongest default predictors.
        # See: RBA RDP 2020-03, APRA APS 220, Urban Institute vintage analysis.

        df['actual_outcome'] = outcomes

        # Phase 1C: Default timing — shifted log-normal for more realistic timing
        df['months_to_outcome'] = np.where(
            approved_mask & df['actual_outcome'].isin(['default', 'arrears_90']),
            np.clip(rng.lognormal(mean=np.log(18), sigma=0.5, size=len(df)).astype(int), 3, 36),
            np.where(approved_mask & df['actual_outcome'].isin(['arrears_30', 'arrears_60']),
                np.clip(rng.lognormal(mean=np.log(12), sigma=0.6, size=len(df)).astype(int), 1, 36),
                np.where(approved_mask & (df['actual_outcome'] == 'prepaid'),
                    np.clip(rng.poisson(4, len(df)), 1, 12),
                    np.where(approved_mask, 12, np.nan)))
        )

        return df

    def _get_hem(self, applicant_type, dependants, annual_income, state='NSW'):
        """Look up HEM benchmark based on household composition, income, and state."""
        if annual_income < 45000:
            bracket = 'very_low'
        elif annual_income < 60000:
            bracket = 'low'
        elif annual_income < 120000:
            bracket = 'mid'
        elif annual_income < 180000:
            bracket = 'high'
        else:
            bracket = 'very_high'
        dep_key = min(dependants, 4)
        base_hem = self.HEM_TABLE.get((applicant_type, dep_key, bracket), 2950)
        # Apply geographic multiplier
        state_mult = self.STATE_HEM_MULTIPLIER.get(state, 1.00)
        return int(base_hem * state_mult)

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
        # Refined per Big 4 2025 practice:
        # - Self-employed 1yr+ accepted (was 2yr pre-2025)
        #   - 1-2yr: 75%, 2yr+: 82%
        # - Casual tenure-based: <1yr deny, 1-2yr 80%, 2yr+ 100%
        # =========================================================
        income_shade = df['employment_type'].map(self.INCOME_SHADING).values
        # Self-employed with 2+ years: higher acceptance
        se_experienced = (df['employment_type'] == 'self_employed') & (df['employment_length'] >= 2)
        income_shade = np.where(se_experienced, 0.82, income_shade)
        # Self-employed with 1-2 years: base rate (0.75 from INCOME_SHADING)
        # Self-employed with <1 year: lower acceptance
        se_new = (df['employment_type'] == 'self_employed') & (df['employment_length'] < 1)
        income_shade = np.where(se_new, 0.65, income_shade)
        # Casual with 2+ years same employer: full income accepted
        casual_experienced = (df['employment_type'] == 'payg_casual') & (df['employment_length'] >= 2)
        income_shade = np.where(casual_experienced, 1.00, income_shade)
        # Casual with <1 year: significantly lower (hard deny below)
        casual_new = (df['employment_type'] == 'payg_casual') & (df['employment_length'] < 1)
        income_shade = np.where(casual_new, 0.60, income_shade)
        shaded_monthly_income = gross_monthly_income * income_shade

        # =========================================================
        # STEP 2: Hard cutoffs (auto-deny)
        # =========================================================

        # Bankruptcy: hard deny (undischarged or within 7 years)
        approved[df['has_bankruptcy'] == 1] = 0

        # Cash advance users with 3+ in 12 months: hard deny
        approved[(df.get('cash_advance_count_12m', pd.Series(0, index=df.index)) >= 3)] = 0

        # APRA DTI cap: total DTI >= 6x is a macro-prudential boundary.
        # APRA Sep Q 2025: 6.1% of new lending has DTI >= 6, meaning some
        # pass through with compensating factors (excellent credit, high income,
        # strong documentation). ~15% pass-through rate for qualified applicants.
        high_dti_mask = total_dti >= 6.0
        high_dti_pass = high_dti_mask & (credit >= 850) & (df['annual_income'] > 150000)
        approved[high_dti_mask & ~high_dti_pass] = 0

        # Credit score floor: Big 4 banks require 650+
        approved[credit < 650] = 0
        # Borderline 650-700 with high DTI: deterministic deny
        borderline_credit = (credit >= 650) & (credit < 700)
        approved[borderline_credit & (total_dti > 4.0)] = 0

        # Self-employed < 1 year ABN history (Big 4 policy change 2025:
        # CBA, Westpac, ANZ, NAB all accept 1yr+ financials)
        approved[(df['employment_type'] == 'self_employed') & (df['employment_length'] < 1)] = 0

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
            self._get_hem(at, dep, inc, st)
            for at, dep, inc, st in zip(
                df['applicant_type'], df['number_of_dependants'],
                df['annual_income'], df['state']
            )
        ])
        effective_expenses = np.maximum(df['monthly_expenses'], hem_values)

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
        base_offered = np.clip(
            df['rba_cash_rate'].values / 100 + rate_spread, 0.055, 0.085
        )
        # Risk adjustments:
        #   - Excellent credit (>900): -0.3%
        #   - Fair credit (700-800): +0.5%
        #   - High LVR (>80%): +0.2%
        #   - Investment/business: +0.3%
        offered_rate = base_offered.copy()
        offered_rate = np.where(credit > 900, offered_rate - 0.003, offered_rate)
        offered_rate = np.where((credit >= 700) & (credit <= 800), offered_rate + 0.005, offered_rate)
        offered_rate = np.where(lvr > 0.80, offered_rate + 0.002, offered_rate)
        offered_rate = np.where(
            (df['purpose'] == 'business'), offered_rate + 0.003, offered_rate
        )

        # Per-application assessment rate: max(offered + buffer, floor)
        assessment_rate = np.maximum(offered_rate + self.ASSESSMENT_BUFFER, self.FLOOR_RATE)
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

        # HECS/HELP repayment: ~3.5% of gross income (ATO compulsory).
        # Policy change 30 Sept 2025: HECS/HELP removed from DTI
        # calculations by all Big 4 banks. Still deducted from gross
        # pay (reduces net income), but NOT counted as a debt obligation
        # in serviceability assessment. Kept as informational feature only.
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
            shaded_monthly_income - monthly_tax - effective_expenses
            - existing_debt_monthly - credit_card_monthly
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
        # but banks also consider net surplus — if surplus is positive
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
        dsr_cap = np.where(
            df['annual_income'] > 150000, 0.60,
            np.where(df['annual_income'] > 80000, 0.55, 0.50)
        )
        approved[dsr > dsr_cap] = 0

        # =========================================================
        # STEP 8b: Retirement exit strategy
        # If age + loan_term_years > 65, applicant will still be repaying
        # post-retirement. Require documented exit strategy or apply penalty.
        # APRA CPG 223 and NCCP Act responsible lending obligations.
        # =========================================================
        age = df['_age_proxy']
        loan_term_years = df['loan_term_months'] / 12
        retirement_age_at_maturity = age + loan_term_years
        needs_exit_strategy = retirement_age_at_maturity > 65
        # Apply penalty: deny if over retirement with weak financials
        retirement_deny = (
            needs_exit_strategy
            & (credit < 800)  # no strong credit to compensate
            & (df['annual_income'] < 100000)  # not high income
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

        # HECS no longer penalised in composite score (Sept 2025 policy)

        # Add property count bonus for investors (they have equity as buffer)
        property_bonus = np.clip(df.get('existing_property_count', pd.Series(0, index=df.index)).values * 0.01, 0, 0.03)

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

        # Open Banking risk signals — reduce composite score for risky indicators
        ob_penalty = np.zeros(n)
        if 'gambling_transaction_flag' in df.columns:
            ob_penalty += np.where(df['gambling_transaction_flag'] == 1, 0.12, 0.0)
        if 'bnpl_active_count' in df.columns:
            ob_penalty += np.where(df['bnpl_active_count'] > 3, 0.07, 0.0)
        if 'overdraft_frequency_90d' in df.columns:
            ob_penalty += np.where(df['overdraft_frequency_90d'] > 5, 0.10, 0.0)
        if 'salary_credit_regularity' in df.columns:
            ob_penalty += np.where(
                df['salary_credit_regularity'].fillna(0.8) < 0.4, 0.08, 0.0
            )
        if 'income_verification_score' in df.columns:
            ob_penalty += np.where(
                df['income_verification_score'].fillna(0.8) < 0.6, 0.12, 0.0
            )
        if 'savings_trend_3m' in df.columns:
            ob_penalty += np.where(df['savings_trend_3m'] == 'negative', 0.05, 0.0)

        # CCR / BNPL / CDR / Geographic risk penalties & bonuses
        ccr_penalty = np.zeros(n)
        if 'num_late_payments_24m' in df.columns:
            ccr_penalty += np.where(df['num_late_payments_24m'] > 3, 0.15, 0.0)
        if 'worst_late_payment_days' in df.columns:
            ccr_penalty += np.where(df['worst_late_payment_days'] >= 60, 0.20, 0.0)
        if 'credit_utilization_pct' in df.columns:
            ccr_penalty += np.where(df['credit_utilization_pct'].fillna(0) > 0.80, 0.10, 0.0)
        if 'num_hardship_flags' in df.columns:
            ccr_penalty += np.where(df['num_hardship_flags'] > 0, 0.12, 0.0)
        if 'months_since_last_default' in df.columns:
            ccr_penalty += np.where(df['months_since_last_default'].fillna(999) < 12, 0.25, 0.0)
        if 'stressed_dsr' in df.columns:
            ccr_penalty += np.where(df['stressed_dsr'] > 0.40, 0.15, 0.0)
        if 'hem_surplus' in df.columns:
            ccr_penalty += np.where(df['hem_surplus'] < 0, 0.20, 0.0)
        if 'days_negative_balance_90d' in df.columns:
            ccr_penalty += np.where(df['days_negative_balance_90d'] > 10, 0.10, 0.0)
        if 'bnpl_late_payments_12m' in df.columns:
            ccr_penalty += np.where(df['bnpl_late_payments_12m'] > 2, 0.08, 0.0)
        if 'stress_index' in df.columns:
            ccr_penalty += np.where(df['stress_index'] > 60, 0.12, 0.0)
        if 'debt_service_coverage' in df.columns:
            ccr_penalty += np.where(df['debt_service_coverage'].fillna(10) < 1.25, 0.15, 0.0)
        if 'postcode_default_rate' in df.columns:
            ccr_penalty += np.where(df['postcode_default_rate'].fillna(0) > 0.02, 0.05, 0.0)
        if 'industry_risk_tier' in df.columns:
            ccr_penalty += np.where(df['industry_risk_tier'] == 'very_high', 0.08, 0.0)

        # Bonuses for strong CDR signals
        ccr_bonus = np.zeros(n)
        if 'rent_payment_regularity' in df.columns:
            ccr_bonus += np.where(df['rent_payment_regularity'].fillna(0) > 0.9, 0.05, 0.0)
        if 'utility_payment_regularity' in df.columns:
            ccr_bonus += np.where(df['utility_payment_regularity'].fillna(0) > 0.9, 0.03, 0.0)

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

        # Phase 3A: Optimism bias penalty (assessors partially detect overconfidence)
        if 'optimism_bias_flag' in df.columns:
            ob_optimism_penalty = np.where(df['optimism_bias_flag'].values == 1, 0.05, 0.0)
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
        # variation, and HECS removal — hard cutoffs now filter more
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
        override_approve = override_approve & (df['has_bankruptcy'] == 0) & (total_dti < 5.5)
        approved[override_approve] = 1

        return approved

    def _calibrate_default_probability(self, df, rng):
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

        # Base PD: 1.04% (APRA aggregate NPL rate Sep Q 2025)
        base_pd = 0.0104

        # --- LVR risk multiplier (continuous, exponential curve) ---
        # Calibrated so: LVR 0.5→0.5x, 0.7→1.0x, 0.85→2.2x, 0.95→4.3x
        lvr = np.where(
            df['property_value'] > 0,
            df['loan_amount'] / df['property_value'],
            0.3,
        )
        lvr_mult = np.exp(2.2 * (lvr - 0.70))  # exponential around 70% LVR pivot
        lvr_mult = np.clip(lvr_mult, 0.4, 5.0)

        # --- Credit score risk multiplier (continuous, logistic curve) ---
        # Calibrated so: 900→0.25x, 800→0.6x, 700→1.5x, 600→4.0x, 500→10x
        credit = df['credit_score'].values.astype(float)
        credit_mult = np.exp(-0.005 * (credit - 780))
        credit_mult = np.clip(credit_mult, 0.2, 10.0)

        # --- DTI risk multiplier (continuous) ---
        # Calibrated so: 1.5→0.6x, 3.0→1.0x, 4.5→2.5x, 6.0→4.5x
        dti = df['debt_to_income'].values.astype(float)
        dti_mult = np.exp(0.4 * (dti - 3.0))
        dti_mult = np.clip(dti_mult, 0.4, 6.0)

        # --- Employment type multiplier ---
        # PAYG permanent is the baseline (1.0x)
        emp_type = df['employment_type'].values
        emp_mult = np.ones(n)
        emp_mult[emp_type == 'payg_permanent'] = 1.0
        emp_mult[emp_type == 'contract'] = 2.0
        emp_mult[emp_type == 'self_employed'] = 2.5
        emp_mult[emp_type == 'payg_casual'] = 3.8

        # --- Employment tenure multiplier ---
        # Longer tenure = lower risk (protective factor)
        emp_len = df['employment_length'].values.astype(float)
        tenure_mult = np.where(emp_len >= 10, 0.6,
                     np.where(emp_len >= 5, 0.75,
                     np.where(emp_len >= 2, 0.9,
                     np.where(emp_len >= 1, 1.2, 2.0))))

        # --- Dependants stress factor ---
        deps = df['number_of_dependants'].values.astype(float)
        deps_mult = 1.0 + 0.08 * deps  # each dependant adds 8% to PD

        # --- HECS drag ---
        has_hecs = df['has_hecs'].values.astype(float) if 'has_hecs' in df.columns else np.zeros(n)
        hecs_mult = np.where(has_hecs == 1, 1.15, 1.0)  # 15% higher PD with HECS

        # Multiplicative model: PD = base × product(risk_factors)
        # This is how real Basel III IRB models work — risk factors compound
        raw_pd = (
            base_pd
            * lvr_mult
            * credit_mult
            * dti_mult
            * emp_mult
            * tenure_mult
            * deps_mult
            * hecs_mult
        )

        # Bankruptcy: floor at 10% PD (very high risk, matches Equifax data)
        raw_pd[df['has_bankruptcy'] == 1] = np.maximum(
            raw_pd[df['has_bankruptcy'] == 1], 0.10
        )

        # Idiosyncratic noise (life events: divorce, illness, redundancy)
        # Log-normal preserves right skew — most borrowers do fine, a few
        # experience severe shocks. sigma=0.5 gives realistic tail events.
        noise = rng.lognormal(mean=0.0, sigma=0.5, size=n)
        raw_pd = raw_pd * noise

        # --- Bureau risk factors (new columns from generate()) ---
        if 'num_credit_enquiries_6m' in df.columns:
            enquiry_factor = np.where(
                df['num_credit_enquiries_6m'] >= 5, 2.5,
                np.where(df['num_credit_enquiries_6m'] >= 3, 1.8,
                    np.where(df['num_credit_enquiries_6m'] >= 2, 1.3, 1.0))
            )
            raw_pd *= enquiry_factor

        if 'worst_arrears_months' in df.columns:
            arrears_factor = np.where(
                df['worst_arrears_months'] >= 3, 4.0,
                np.where(df['worst_arrears_months'] >= 2, 3.0,
                    np.where(df['worst_arrears_months'] >= 1, 2.0, 1.0))
            )
            raw_pd *= arrears_factor

        if 'num_bnpl_accounts' in df.columns:
            bnpl_factor = np.where(df['num_bnpl_accounts'] >= 3, 1.5,
                np.where(df['num_bnpl_accounts'] >= 2, 1.3, 1.0))
            raw_pd *= bnpl_factor

        # Cash advance factor — strong negative signal
        if 'cash_advance_count_12m' in df.columns:
            cash_adv_factor = np.where(
                df['cash_advance_count_12m'] >= 3, 3.5,
                np.where(df['cash_advance_count_12m'] >= 1, 2.0, 1.0))
            raw_pd *= cash_adv_factor

        # Gambling spend factor
        if 'gambling_spend_ratio' in df.columns:
            gambling_factor = np.where(
                df['gambling_spend_ratio'] > 0.05, 2.5,
                np.where(df['gambling_spend_ratio'] > 0.02, 1.5, 1.0))
            raw_pd *= gambling_factor

        # --- Behavioural risk factors (existing customers only) ---
        if 'num_dishonours_12m' in df.columns:
            dishonour_factor = np.where(
                df['num_dishonours_12m'].fillna(0) >= 3, 3.0,
                np.where(df['num_dishonours_12m'].fillna(0) >= 1, 2.0, 1.0))
            raw_pd *= dishonour_factor

        if 'days_in_overdraft_12m' in df.columns:
            overdraft_factor = np.where(
                df['days_in_overdraft_12m'].fillna(0) >= 30, 2.0,
                np.where(df['days_in_overdraft_12m'].fillna(0) >= 10, 1.5, 1.0))
            raw_pd *= overdraft_factor

        # --- Behavioral realism factors (Phase 3B) ---

        # Prepayment buffer (RBA RDP 2020-03)
        if 'prepayment_buffer_months' in df.columns:
            buffer = df['prepayment_buffer_months'].fillna(6).values
            buffer_factor = np.where(buffer < 1, 2.32,
                np.where(buffer < 3, 1.5,
                    np.where(buffer > 6, 0.33, 1.0)))
            raw_pd *= buffer_factor

        # Double-trigger interaction (RBA RDP 2020-03)
        if 'negative_equity_flag' in df.columns and 'prepayment_buffer_months' in df.columns:
            double_trigger = (
                (df['negative_equity_flag'].values == 1)
                & (df['prepayment_buffer_months'].fillna(6).values < 1)
            )
            raw_pd[double_trigger] *= 2.5

        # Optimism bias (Philadelphia Fed)
        if 'optimism_bias_flag' in df.columns:
            raw_pd *= np.where(df['optimism_bias_flag'].values == 1, 1.7, 1.0)

        # Financial literacy (ANZ Survey)
        if 'financial_literacy_score' in df.columns:
            lit = df['financial_literacy_score'].fillna(0.5).values
            lit_factor = np.where(lit < 0.4, 1.25, np.where(lit > 0.7, 0.85, 1.0))
            raw_pd *= lit_factor

        # Life event trigger risk
        if 'loan_trigger_event' in df.columns:
            trigger = df['loan_trigger_event'].values
            trigger_factor = np.ones(n)
            trigger_factor[trigger == 'debt_consolidation'] = 1.4
            trigger_factor[trigger == 'medical'] = 1.3
            trigger_factor[trigger == 'startup'] = 1.5
            trigger_factor[trigger == 'refinance'] = 0.8
            trigger_factor[trigger == 'vehicle_purchase'] = 0.9
            raw_pd *= trigger_factor

        # --- Macroeconomic factors ---
        if 'rba_cash_rate' in df.columns:
            rate_factor = 1.0 + (df['rba_cash_rate'] - 3.5) * 0.15
            rate_factor = np.clip(rate_factor, 0.8, 1.5)
            raw_pd *= rate_factor

        if 'unemployment_rate' in df.columns:
            unemp_factor = 1.0 + (df['unemployment_rate'] - 3.5) * 0.20
            unemp_factor = np.clip(unemp_factor, 0.8, 1.8)
            raw_pd *= unemp_factor

        # Clip to realistic range
        calibrated_pd = np.clip(raw_pd, 0.001, 0.60)

        return np.round(calibrated_pd, 4)

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
