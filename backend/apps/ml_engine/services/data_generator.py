import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats

from .benchmark_resolver import BenchmarkResolver
from .feature_generator import BehavioralFeatureGenerator
from .loan_performance_simulator import LoanPerformanceSimulator
from .property_data_service import PropertyDataService
from .underwriting_engine import UnderwritingEngine


# Columns that describe post-approval outcomes, or that directly encode the
# approval decision. They MUST be excluded from any feature matrix built for
# model training or ablation — including them gives all models trivially
# perfect separation (AUC ~= 1.0). Kept here next to the generator that emits
# them so any future schema change can update this tuple in one place.
# Consumers: apps.ml_engine.management.commands.run_benchmark,
#            apps.ml_engine.management.commands.run_ablation
LABEL_LEAKING_COLUMNS: tuple[str, ...] = (
    "approval_type",
    "conditions",
    "requires_human_review",
    "n_conditions",
    "prepayment_buffer_months",
    "negative_equity_flag",
    "default_probability",
    "actual_outcome",
    "months_to_outcome",
    "months_on_book",
    "ever_30dpd",
    "ever_90dpd",
    "default_flag",
    "prepaid_flag",
    "current_status",
    "stressed_repayment",
    "stressed_dsr",
)


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

    PURPOSES = ["home", "auto", "education", "personal", "business"]
    HOME_OWNERSHIP = ["own", "rent", "mortgage"]
    HOME_OWNERSHIP_WEIGHTS = [0.22, 0.30, 0.48]
    EMPLOYMENT_TYPES = ["payg_permanent", "payg_casual", "self_employed", "contract"]
    EMPLOYMENT_TYPE_WEIGHTS = [0.68, 0.12, 0.12, 0.08]
    APPLICANT_TYPES = ["single", "couple"]
    APPLICANT_TYPE_WEIGHTS = [0.42, 0.58]

    # APRA serviceability buffer (3% above product rate)
    ASSESSMENT_BUFFER = 0.03
    BASE_RATE = 0.065  # ~6.5% average variable rate (2025/2026)
    FLOOR_RATE = 0.0575  # Big 4 floor rate (~5.75%)

    # Temporal rate modelling — product rate = cash rate + spread
    RATE_SPREAD_OVER_CASH = 2.15  # Big 4 avg spread over RBA cash rate (%)
    STRESS_TEST_BUFFER = 3.0  # APRA buffer above product rate (%)

    # HEM monthly benchmarks (Melbourne Institute 2025/2026, CPI-indexed)
    HEM_TABLE = UnderwritingEngine.HEM_TABLE

    # Geographic HEM multiplier (Sydney/Melbourne higher COL, regional lower)
    STATE_HEM_MULTIPLIER = UnderwritingEngine.STATE_HEM_MULTIPLIER

    # Income shading by employment type (what % of income banks accept)
    INCOME_SHADING = UnderwritingEngine.INCOME_SHADING

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
    # ===================================================================
    STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]
    STATE_WEIGHTS = [0.33, 0.27, 0.19, 0.10, 0.06, 0.02, 0.02, 0.01]

    STATE_PROFILES = {
        "NSW": {
            "median_house": 1_650_000,
            "income_mult": 1.08,
            "credit_adj": +26,
            "investor_pct": 0.40,
        },
        "VIC": {
            "median_house": 978_000,
            "income_mult": 1.03,
            "credit_adj": +30,
            "investor_pct": 0.35,
        },
        "QLD": {
            "median_house": 880_000,
            "income_mult": 0.95,
            "credit_adj": +10,
            "investor_pct": 0.33,
        },
        "WA": {
            "median_house": 981_000,
            "income_mult": 1.12,
            "credit_adj": +29,
            "investor_pct": 0.28,
        },
        "SA": {
            "median_house": 750_000,
            "income_mult": 0.92,
            "credit_adj": +34,
            "investor_pct": 0.25,
        },
        "TAS": {
            "median_house": 620_000,
            "income_mult": 0.88,
            "credit_adj": +31,
            "investor_pct": 0.20,
        },
        "ACT": {
            "median_house": 950_000,
            "income_mult": 1.25,
            "credit_adj": +51,
            "investor_pct": 0.30,
        },
        "NT": {
            "median_house": 520_000,
            "income_mult": 1.05,
            "credit_adj": -20,
            "investor_pct": 0.22,
        },
    }

    # ===================================================================
    # ANZSIC INDUSTRY DISTRIBUTION BY STATE
    # ===================================================================
    ANZSIC_DIVISIONS = BenchmarkResolver.ANZSIC_DIVISIONS

    # Baseline national industry weights (ABS Labour Force Aug 2025)
    _NATIONAL_INDUSTRY_WEIGHTS = BenchmarkResolver._NATIONAL_INDUSTRY_WEIGHTS

    # State-specific adjustments (multipliers applied to national weights)
    _STATE_INDUSTRY_ADJUSTMENTS = BenchmarkResolver._STATE_INDUSTRY_ADJUSTMENTS

    # Fallback income multipliers by ANZSIC division (ABS AWE Aug 2025)
    _FALLBACK_INDUSTRY_INCOME_MULT = {
        "A": 0.78,
        "B": 1.85,
        "C": 0.95,
        "E": 1.10,
        "G": 0.68,
        "H": 0.58,
        "I": 1.05,
        "J": 1.40,
        "K": 1.45,
        "M": 1.35,
        "N": 0.75,
        "O": 1.20,
        "P": 0.92,
        "Q": 0.88,
        "S": 0.80,
    }

    # FHB grants by state (2025-26 rates, no scraping needed)
    FHB_GRANTS = {
        "NSW": {"amount": 10_000, "new_home_cap": 600_000, "house_land_cap": 750_000},
        "VIC": {"amount": 10_000, "new_home_cap": 750_000, "house_land_cap": 750_000},
        "QLD": {"amount": 30_000, "new_home_cap": 750_000, "house_land_cap": 750_000},
        "WA": {"amount": 10_000, "new_home_cap": 750_000, "house_land_cap": 750_000},
        "SA": {"amount": 15_000, "new_home_cap": 650_000, "house_land_cap": 650_000},
        "TAS": {"amount": 30_000, "new_home_cap": 400_000, "house_land_cap": 400_000},
        "ACT": {"amount": 0, "new_home_cap": 0, "house_land_cap": 0},
        "NT": {"amount": 10_000, "new_home_cap": 750_000, "house_land_cap": 750_000},
    }

    # HELP repayment thresholds 2025-26 (ATO)
    HELP_REPAYMENT_THRESHOLDS = BenchmarkResolver.HELP_REPAYMENT_THRESHOLDS

    # ===================================================================
    # GAUSSIAN COPULA: correlation structure for numeric features.
    # ===================================================================
    COPULA_FEATURES = [
        "age",
        "income",
        "credit_score",
        "employment_length",
        "monthly_expenses",
        "credit_card_limit",
        "dependants",
    ]
    COPULA_CORRELATION = np.array(
        [
            # age   income  credit  emp_len expenses cc_lim  deps
            [1.00, 0.35, 0.40, 0.55, 0.20, 0.25, 0.15],  # age
            [0.35, 1.00, 0.30, 0.25, 0.45, 0.40, -0.05],  # income
            [0.40, 0.30, 1.00, 0.20, 0.10, 0.15, -0.10],  # credit_score
            [0.55, 0.25, 0.20, 1.00, 0.10, 0.15, 0.10],  # employment_length
            [0.20, 0.45, 0.10, 0.10, 1.00, 0.30, 0.25],  # monthly_expenses
            [0.25, 0.40, 0.15, 0.15, 0.30, 1.00, 0.10],  # credit_card_limit
            [0.15, -0.05, -0.10, 0.10, 0.25, 0.10, 1.00],  # dependants
        ]
    )

    # Validate positive semi-definiteness at import time.
    _eigvals = np.linalg.eigvalsh(COPULA_CORRELATION)
    assert np.all(_eigvals >= -1e-10), (
        f"COPULA_CORRELATION is not positive semi-definite. Min eigenvalue: {_eigvals.min():.6f}"
    )

    # ===================================================================
    # SUB-POPULATION MIXTURE MODEL
    # ===================================================================
    SUB_POPULATIONS = {
        "first_home_buyer": {
            "weight": 0.15,
            "age_mean": 33,
            "age_std": 5,
            "income_single_mean": 58000,
            "income_couple_mean": 95000,
            "credit_score_mean": 800,
            "credit_score_std": 80,
            "loan_mult_mean": 5.2,
            "loan_mult_std": 0.8,
            "lvr_mean": 0.87,
            "lvr_std": 0.05,
            "purpose_override": "home",
        },
        "upgrader": {
            "weight": 0.20,
            "age_mean": 42,
            "age_std": 7,
            "income_single_mean": 74000,
            "income_couple_mean": 105000,
            "credit_score_mean": 875,
            "credit_score_std": 70,
            "loan_mult_mean": 4.0,
            "loan_mult_std": 0.8,
            "lvr_mean": 0.65,
            "lvr_std": 0.12,
            "purpose_override": "home",
        },
        "refinancer": {
            "weight": 0.10,
            "age_mean": 48,
            "age_std": 8,
            "income_single_mean": 70000,
            "income_couple_mean": 100000,
            "credit_score_mean": 905,
            "credit_score_std": 60,
            "loan_mult_mean": 3.0,
            "loan_mult_std": 0.7,
            "lvr_mean": 0.55,
            "lvr_std": 0.12,
            "purpose_override": "home",
        },
        "personal_borrower": {
            "weight": 0.35,
            "age_mean": 36,
            "age_std": 10,
            "income_single_mean": 50000,
            "income_couple_mean": 72000,
            "credit_score_mean": 845,
            "credit_score_std": 90,
            "loan_mult_mean": 0.35,
            "loan_mult_std": 0.3,
            "lvr_mean": 0.0,
            "lvr_std": 0.0,
            "purpose_override": None,
        },
        "business_borrower": {
            "weight": 0.12,
            "age_mean": 44,
            "age_std": 9,
            "income_single_mean": 60000,
            "income_couple_mean": 92000,
            "credit_score_mean": 855,
            "credit_score_std": 85,
            "loan_mult_mean": 0.6,
            "loan_mult_std": 0.5,
            "lvr_mean": 0.0,
            "lvr_std": 0.0,
            "purpose_override": "business",
        },
        "investor": {
            "weight": 0.08,
            "age_mean": 45,
            "age_std": 8,
            "income_single_mean": 85000,
            "income_couple_mean": 125000,
            "credit_score_mean": 885,
            "credit_score_std": 65,
            "loan_mult_mean": 4.5,
            "loan_mult_std": 1.0,
            "lvr_mean": 0.70,
            "lvr_std": 0.08,
            "purpose_override": "home",
        },
    }

    # ===================================================================
    # TEMPORAL DIMENSION — 36-month application window
    # ===================================================================

    # Quarterly RBA cash rate (actual historical + projected)
    RBA_RATE_HISTORY = BenchmarkResolver.RBA_RATE_HISTORY

    # Property growth 12-month % by state and quarter (CoreLogic-calibrated)
    PROPERTY_GROWTH = BenchmarkResolver.PROPERTY_GROWTH

    # State unemployment rates by quarter (ABS Labour Force)
    UNEMPLOYMENT_RATES = BenchmarkResolver.UNEMPLOYMENT_RATES

    # Westpac-Melbourne Institute Consumer Confidence Index (100 = neutral)
    CONSUMER_CONFIDENCE = BenchmarkResolver.CONSUMER_CONFIDENCE

    # Quarter start dates for generating application_date within each quarter
    _QUARTER_START_DATES = {
        "2023Q3": date(2023, 7, 1),
        "2023Q4": date(2023, 10, 1),
        "2024Q1": date(2024, 1, 1),
        "2024Q2": date(2024, 4, 1),
        "2024Q3": date(2024, 7, 1),
        "2024Q4": date(2024, 10, 1),
        "2025Q1": date(2025, 1, 1),
        "2025Q2": date(2025, 4, 1),
        "2025Q3": date(2025, 7, 1),
        "2025Q4": date(2025, 10, 1),
        "2026Q1": date(2026, 1, 1),
        "2026Q2": date(2026, 4, 1),
    }

    # Seasonal application volume weights.
    _QUARTER_SEASON_WEIGHTS = {
        "Q1": 1.15,
        "Q2": 0.80,
        "Q3": 0.95,
        "Q4": 1.10,
    }
    # Monthly seasonal weights (ABS Lending Indicators).
    _MONTH_SEASON_WEIGHTS = {
        1: 1.10,
        2: 1.15,
        3: 1.05,
        4: 0.90,
        5: 0.85,
        6: 0.75,
        7: 0.78,
        8: 0.88,
        9: 0.95,
        10: 1.10,
        11: 1.20,
        12: 1.05,
    }
    _RATE_CUT_BOOST_QUARTERS = {"2025Q1", "2025Q3", "2026Q1"}

    def __init__(self, benchmarks: dict = None, use_live_macro: bool = False):
        """Initialise DataGenerator with optional real-world calibration.

        Args:
            benchmarks: Optional calibration snapshot from
                RealWorldBenchmarks.get_calibration_snapshot(). When None
                (the default), all class-level constants are used as-is,
                producing identical output to the original implementation.
            use_live_macro: If True, fetch current-quarter macro indicators
                from MacroDataService instead of using RBA_RATE_HISTORY etc.
                Only affects the LATEST quarter in the temporal window;
                historical quarters always use hardcoded tables.
        """
        self._benchmarks_raw = benchmarks
        self._use_live_macro = use_live_macro
        self._macro_cache: dict = {}
        self.reject_inference_labels = None
        self._property_service = PropertyDataService()

        # Delegate objects
        self._benchmark = BenchmarkResolver(benchmarks, use_live_macro)
        self._features = BehavioralFeatureGenerator()
        self._underwriting = UnderwritingEngine(benchmarks)
        self._performance = LoanPerformanceSimulator()

    # ------------------------------------------------------------------
    # Backward-compatible delegate methods (keep _ prefix on DataGenerator)
    # ------------------------------------------------------------------

    def _get_state_industry_weights(self, state_code: str) -> np.ndarray:
        return self._benchmark.get_state_industry_weights(state_code)

    def _get_help_repayment_rate(self, income: float) -> float:
        return self._benchmark.get_help_repayment_rate(income)

    def _compute_product_rates(self, rba_cash_rate, purpose, sub_pop, n):
        return self._benchmark.compute_product_rates(rba_cash_rate, purpose, sub_pop, n)

    def _resolve_income_params(self, pop_name, is_couple, state_mult):
        return self._benchmark.resolve_income_params(pop_name, is_couple, state_mult, self.SUB_POPULATIONS)

    def _resolve_loan_multiplier(self, pop_name):
        return self._benchmark.resolve_loan_multiplier(pop_name, self.SUB_POPULATIONS)

    def _resolve_credit_score_params(self, pop_name, state_credit_adj):
        return self._benchmark.resolve_credit_score_params(pop_name, state_credit_adj, self.SUB_POPULATIONS)

    def _resolve_default_base_rate(self):
        return self._benchmark.resolve_default_base_rate()

    def _resolve_macro_for_quarter(self, quarter, state):
        return self._benchmark.resolve_macro_for_quarter(quarter, state)

    def _apply_round_number_bias(self, loan_amount, rng):
        return self._features.apply_round_number_bias(loan_amount, rng)

    def _assign_application_channel(self, age, purpose, sub_pop, rng):
        return self._features.assign_application_channel(age, purpose, sub_pop, rng)

    def _apply_income_inflation(self, annual_income, employment_type, is_fraud_signal, rng):
        return self._features.apply_income_inflation(annual_income, employment_type, is_fraud_signal, rng)

    def _apply_optimism_bias(self, loan_amount, age, sub_pop, rng):
        return self._features.apply_optimism_bias(loan_amount, age, sub_pop, rng)

    def _assign_financial_literacy(self, age, credit_score, sub_pop, rng):
        return self._features.assign_financial_literacy(age, credit_score, sub_pop, rng)

    def _compute_prepayment_buffer(self, df, rng):
        return self._features.compute_prepayment_buffer(df, rng)

    def _assign_life_event_trigger(self, purpose, sub_pop, rng):
        return self._features.assign_life_event_trigger(purpose, sub_pop, rng)

    def _get_hem(self, applicant_type, dependants, annual_income, state="NSW"):
        return self._underwriting.get_hem(applicant_type, dependants, annual_income, state)

    def _compute_approval(self, df, rng):
        return self._underwriting.compute_approval(df, rng)

    def _calibrate_default_probability(self, df, rng):
        return self._underwriting.calibrate_default_probability(df, rng, self._benchmark.resolve_default_base_rate)

    def _simulate_loan_performance(self, df):
        return self._performance.simulate_loan_performance(df)

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
        mvn_samples = rng.multivariate_normal(mean=np.zeros(k), cov=self.COPULA_CORRELATION, size=n)
        # Transform to uniform [0,1] via the standard normal CDF
        uniform_samples = stats.norm.cdf(mvn_samples)
        return {name: uniform_samples[:, i] for i, name in enumerate(self.COPULA_FEATURES)}

    def generate(self, num_records=50000, random_seed=42, label_noise_rate=0.05):
        """Generate synthetic loan data with Australian-realistic distributions.

        Uses a Gaussian copula for correlated feature generation and a
        sub-population mixture model for realistic applicant segmentation.
        """
        rng = np.random.default_rng(random_seed)
        np.random.seed(random_seed)  # also seed legacy RNG for _simulate_loan_performance
        n = num_records
        self.reject_inference_labels = None  # populated at end of generate()
        self._macro_cache = {}  # reset per-generate to ensure reproducibility
        self._benchmark._macro_cache = {}  # reset delegate cache too

        # =============================================================
        # STEP 0: Generate correlated uniform samples via Gaussian copula
        # =============================================================
        copula = self._generate_copula_samples(n, rng)

        # =============================================================
        # STEP 1: Assign sub-populations and geographic location
        # =============================================================
        pop_names = list(self.SUB_POPULATIONS.keys())
        pop_weights = [self.SUB_POPULATIONS[p]["weight"] for p in pop_names]
        sub_pop = rng.choice(pop_names, size=n, p=pop_weights)

        # Assign state/territory based on population-weighted distribution
        state = rng.choice(self.STATES, size=n, p=self.STATE_WEIGHTS)

        # --- SA3 sub-state geography assignment ---
        sa3_codes = np.empty(n, dtype="<U5")
        sa3_names = np.empty(n, dtype="<U50")
        sa3_property_mult = np.ones(n)
        sa3_rental_mult = np.ones(n)
        for st in self.STATES:
            st_mask = state == st
            count = st_mask.sum()
            if count == 0:
                continue
            regions = self._property_service._sa3_by_state.get(st, [])
            if not regions:
                sa3_codes[st_mask] = "00000"
                sa3_names[st_mask] = f"Unknown ({st})"
                continue
            weights = np.array([r["population_weight"] for r in regions])
            weights /= weights.sum()
            idxs = rng.choice(len(regions), size=count, p=weights)
            sa3_codes[st_mask] = [regions[i]["code"] for i in idxs]
            sa3_names[st_mask] = [regions[i]["name"] for i in idxs]
            sa3_property_mult[st_mask] = [regions[i]["property_mult"] for i in idxs]
            sa3_rental_mult[st_mask] = [regions[i]["rental_mult"] for i in idxs]

        # --- ANZSIC industry assignment (correlated with state) ---
        industry_anzsic = np.empty(n, dtype="<U1")
        for st in self.STATES:
            st_mask = state == st
            if st_mask.sum() > 0:
                weights = self._get_state_industry_weights(st)
                industry_anzsic[st_mask] = rng.choice(
                    self.ANZSIC_DIVISIONS,
                    size=st_mask.sum(),
                    p=weights,
                )

        # Industry income multiplier
        industry_income_mult_map = self._FALLBACK_INDUSTRY_INCOME_MULT.copy()
        if self._benchmarks_raw and "industry_income_multipliers" in self._benchmarks_raw:
            live = self._benchmarks_raw["industry_income_multipliers"]
            for div in self.ANZSIC_DIVISIONS:
                if div in live:
                    industry_income_mult_map[div] = live[div]
        industry_income_mult = np.array([industry_income_mult_map.get(d, 1.0) for d in industry_anzsic])

        # =============================================================
        # STEP 0b: Temporal dimension — 36-month application window
        # =============================================================
        quarters = list(self.RBA_RATE_HISTORY.keys())

        _month_entries = []
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
        application_date = []
        for idx in month_idx:
            year, month, _, _ = _month_entries[idx]
            if month == 12:
                days_in_month = (date(year + 1, 1, 1) - date(year, month, 1)).days
            else:
                days_in_month = (date(year, month + 1, 1) - date(year, month, 1)).days
            day_offset = int(rng.integers(0, days_in_month))
            application_date.append(date(year, month, 1) + timedelta(days=day_offset))
        application_date = np.array(application_date, dtype="datetime64[D]")

        application_quarter = np.array([_month_entries[i][2] for i in month_idx])

        _macro = [self._resolve_macro_for_quarter(q, s) for q, s in zip(application_quarter, state, strict=False)]
        rba_cash_rate = np.array([m["rba_cash_rate"] for m in _macro])
        unemployment_rate = np.array([m["unemployment_rate"] for m in _macro])
        property_growth_12m = np.array([m["property_growth_12m"] for m in _macro])
        consumer_confidence = np.array([m["consumer_confidence"] for m in _macro])

        # --- Demographics ---
        employment_type = rng.choice(self.EMPLOYMENT_TYPES, size=n, p=self.EMPLOYMENT_TYPE_WEIGHTS)
        applicant_type = rng.choice(self.APPLICANT_TYPES, size=n, p=self.APPLICANT_TYPE_WEIGHTS)

        dep_thresholds = np.cumsum([0.35, 0.25, 0.25, 0.10])
        number_of_dependants = np.digitize(copula["dependants"], dep_thresholds)

        # --- Age: transform copula uniform using sub-population parameters ---
        age_proxy = np.zeros(n, dtype=int)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            age_proxy[mask] = np.clip(
                stats.norm.ppf(copula["age"][mask], loc=pop["age_mean"], scale=pop["age_std"]).astype(int),
                20,
                70,
            )

        # --- Income: copula-correlated, sub-population + state-aware ---
        state_income_mult = np.array([self.STATE_PROFILES[s]["income_mult"] for s in state])
        combined_income_mult = state_income_mult * industry_income_mult
        annual_income = np.zeros(n)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            is_couple = applicant_type[mask] == "couple"
            inc_mean, inc_sigma = self._resolve_income_params(
                pop_name,
                is_couple,
                combined_income_mult[mask],
            )
            annual_income[mask] = np.exp(stats.norm.ppf(copula["income"][mask], loc=np.log(inc_mean), scale=inc_sigma))
        annual_income = np.clip(annual_income.round(2), 30000, 600000)

        # --- Employment length: copula-correlated ---
        employment_length = np.clip(stats.expon.ppf(copula["employment_length"], scale=6).astype(int), 0, 40)
        perm_mask = employment_type == "payg_permanent"
        employment_length[perm_mask] = np.clip(employment_length[perm_mask], 1, 40)
        low_income = annual_income < 50000
        employment_length[low_income] = np.clip(
            employment_length[low_income] - rng.integers(0, 2, size=low_income.sum()),
            0,
            40,
        )

        # --- Purpose: determined by sub-population ---
        purpose = np.empty(n, dtype="<U10")
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            if pop["purpose_override"]:
                purpose[mask] = pop["purpose_override"]
            else:
                non_home_purposes = ["auto", "education", "personal"]
                non_home_weights = np.array([0.36, 0.24, 0.40])
                purpose[mask] = rng.choice(non_home_purposes, size=mask.sum(), p=non_home_weights)
        is_home = purpose == "home"

        # --- Credit score: copula-correlated, sub-population + state-aware ---
        state_credit_adj = np.array([self.STATE_PROFILES[s]["credit_adj"] for s in state])
        credit_score = np.zeros(n, dtype=int)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            cs_mean, cs_std, _ = self._resolve_credit_score_params(
                pop_name,
                state_credit_adj[mask],
            )
            credit_score[mask] = np.clip(
                stats.norm.ppf(
                    copula["credit_score"][mask],
                    loc=cs_mean + state_credit_adj[mask],
                    scale=cs_std,
                ).astype(int),
                300,
                1200,
            )
        credit_score[is_home] = np.clip(credit_score[is_home], 700, 1200)
        credit_score[~is_home] = np.clip(credit_score[~is_home], 650, 1200)

        home_ownership = rng.choice(self.HOME_OWNERSHIP, size=n, p=self.HOME_OWNERSHIP_WEIGHTS)
        has_cosigner = rng.choice([0, 1], size=n, p=[0.92, 0.08])

        # --- Existing debt ---
        existing_dti = np.where(
            is_home,
            np.clip(rng.beta(a=2.0, b=4.5, size=n) * 1.4, 0, 1.4),
            np.clip(rng.beta(a=2.0, b=4.0, size=n) * 2.0, 0, 2.0),
        ).round(2)

        dti_penalty = np.clip((existing_dti - 0.3) * 60, 0, 100).astype(int)
        credit_score = np.clip(credit_score - dti_penalty, 300, 1200)
        credit_score[is_home] = np.clip(credit_score[is_home], 700, 1200)
        credit_score[~is_home] = np.clip(credit_score[~is_home], 650, 1200)

        # --- Loan amounts: sub-population-driven ---
        loan_multiplier = np.zeros(n)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            mult_mean, mult_std = self._resolve_loan_multiplier(pop_name)
            if pop["purpose_override"] == "home":
                loan_multiplier[mask] = np.clip(
                    rng.normal(mult_mean, mult_std, size=mask.sum()),
                    1.0,
                    6.5,
                )
            else:
                loan_multiplier[mask] = np.clip(
                    rng.lognormal(mean=np.log(mult_mean), sigma=mult_std, size=mask.sum()),
                    0.05,
                    2.0,
                )
        loan_amount = (annual_income * loan_multiplier).round(2)
        loan_amount = self._apply_round_number_bias(loan_amount, rng)
        loan_amount = np.clip(loan_amount, 5000, 3500000)

        new_loan_dti = loan_amount / annual_income
        debt_to_income = (existing_dti + new_loan_dti).round(2)

        loan_term_months = np.where(
            is_home,
            rng.choice([240, 300, 360], size=n, p=[0.20, 0.35, 0.45]),
            rng.choice([12, 24, 36, 60, 84], size=n, p=[0.10, 0.15, 0.30, 0.30, 0.15]),
        )

        # --- Property value ---
        property_value = np.zeros(n)
        lvr_targets = np.zeros(n)
        for pop_name in pop_names:
            mask = sub_pop == pop_name
            pop = self.SUB_POPULATIONS[pop_name]
            if pop["lvr_mean"] > 0:
                lvr_targets[mask] = np.clip(
                    rng.normal(pop["lvr_mean"], pop["lvr_std"], size=mask.sum()),
                    0.30,
                    0.97,
                )
        lvr_targets[~is_home] = 0.0
        safe_lvr = np.where(lvr_targets > 0, lvr_targets, 1.0)
        property_value[is_home] = (loan_amount[is_home] / safe_lvr[is_home]).round(2)
        property_value[is_home] = (property_value[is_home] * sa3_property_mult[is_home]).round(2)
        property_value = np.clip(property_value, 0, 10000000)
        deposit_amount = np.zeros(n)
        deposit_amount[is_home] = np.maximum(property_value[is_home] - loan_amount[is_home], 0).round(2)

        # Apply First Home Buyer grants (state-specific)
        fhb_mask = (sub_pop == "first_home_buyer") & is_home
        for st in self.STATES:
            grant_info = self.FHB_GRANTS.get(st, {})
            grant_amount = grant_info.get("amount", 0)
            cap = grant_info.get("new_home_cap", 0)
            if grant_amount > 0:
                eligible = fhb_mask & (state == st) & (property_value <= cap)
                deposit_amount[eligible] += grant_amount

        monthly_expenses = np.clip(
            np.exp(stats.norm.ppf(copula["monthly_expenses"], loc=np.log(2500), scale=0.4)).round(2),
            800,
            10000,
        )

        has_credit_card = copula["credit_card_limit"] < 0.70
        existing_credit_card_limit = np.where(
            has_credit_card,
            np.clip(
                np.exp(
                    stats.norm.ppf(
                        np.clip(copula["credit_card_limit"] / 0.70, 0.001, 0.999),
                        loc=np.log(8000),
                        scale=0.6,
                    )
                ),
                0,
                50000,
            ).round(2),
            0,
        )

        _state_rent_base = {
            "NSW": 1.30,
            "VIC": 1.10,
            "QLD": 1.00,
            "WA": 1.05,
            "SA": 0.85,
            "TAS": 0.80,
            "ACT": 1.15,
            "NT": 0.90,
        }
        state_rent_mult = np.array([_state_rent_base[s] for s in state])
        state_rent_mult = state_rent_mult * sa3_rental_mult
        monthly_rent = np.where(
            home_ownership == "rent",
            np.clip(rng.lognormal(mean=np.log(2200), sigma=0.3, size=n) * state_rent_mult, 800, 6000).round(0),
            0.0,
        )

        # --- HECS/HELP debt ---
        hecs_rate = np.where(age_proxy < 35, 0.55, np.where(age_proxy < 55, 0.30, 0.05))
        has_hecs = (rng.random(n) < hecs_rate).astype(int)

        hecs_debt_balance = np.where(
            has_hecs == 1,
            np.clip(rng.lognormal(mean=np.log(22000), sigma=0.6, size=n), 5000, 120000).round(0),
            0.0,
        )

        help_repayment_annual = np.array(
            [
                self._get_help_repayment_rate(inc) * inc if hecs else 0.0
                for inc, hecs in zip(annual_income, has_hecs, strict=False)
            ]
        )
        help_repayment_monthly = (help_repayment_annual / 12).round(2)

        # --- Bankruptcy ---
        has_bankruptcy = rng.choice([0, 1], size=n, p=[0.99, 0.01])

        property_count_base = np.digitize(rng.random(n), [0.65, 0.90, 0.98])
        investor_mask = sub_pop == "investor"
        property_count_base[investor_mask] = np.clip(property_count_base[investor_mask], 1, 5)
        upgrader_mask = sub_pop == "upgrader"
        property_count_base[upgrader_mask] = np.where(
            rng.random(upgrader_mask.sum()) < 0.85, 1, property_count_base[upgrader_mask]
        )
        existing_property_count = property_count_base

        # =============================================================
        # BUREAU FEATURES
        # =============================================================
        credit_norm = (credit_score - 300) / 900

        enquiry_lambda = np.where(credit_norm > 0.7, 0.8, np.where(credit_norm > 0.4, 1.5, 3.5))
        num_credit_enquiries_6m = rng.poisson(enquiry_lambda)

        arrears_u = rng.random(n)
        worst_arrears_months = np.where(
            credit_norm > 0.7,
            np.where(arrears_u < 0.97, 0, np.where(arrears_u < 0.99, 1, np.where(arrears_u < 0.998, 2, 3))),
            np.where(
                credit_norm > 0.4,
                np.where(arrears_u < 0.88, 0, np.where(arrears_u < 0.96, 1, np.where(arrears_u < 0.99, 2, 3))),
                np.where(arrears_u < 0.70, 0, np.where(arrears_u < 0.85, 1, np.where(arrears_u < 0.95, 2, 3))),
            ),
        )

        default_u = rng.random(n)
        num_defaults_5yr = np.where(
            credit_norm > 0.6,
            0,
            np.where(default_u < 0.90, 0, np.where(default_u < 0.97, 1, np.where(default_u < 0.99, 2, 3))),
        )
        num_defaults_5yr[has_bankruptcy == 1] = np.clip(num_defaults_5yr[has_bankruptcy == 1] + 1, 1, 5)

        credit_history_months = np.clip(((age_proxy - 18) * 12 * rng.uniform(0.3, 0.9, size=n)).astype(int), 0, 480)

        total_open_accounts = np.clip(
            rng.poisson(np.where(annual_income > 100000, 5.0, np.where(annual_income > 60000, 3.5, 2.0))), 0, 15
        )

        bnpl_base_prob = np.where(
            age_proxy < 30, 0.55, np.where(age_proxy < 40, 0.35, np.where(age_proxy < 50, 0.15, 0.05))
        )
        has_bnpl = rng.random(n) < bnpl_base_prob
        num_bnpl_accounts = np.where(has_bnpl, rng.choice([1, 2, 3, 4], size=n, p=[0.45, 0.30, 0.15, 0.10]), 0)

        cash_advance_count_12m = np.where(
            credit_norm > 0.6,
            0,
            np.where(rng.random(n) < 0.15, rng.choice([1, 2, 3, 4, 5], size=n, p=[0.50, 0.25, 0.15, 0.07, 0.03]), 0),
        )

        # =============================================================
        # BEHAVIOURAL SCORE
        # =============================================================
        is_existing_customer = (rng.random(n) < 0.40).astype(int)

        savings_balance = np.where(
            is_existing_customer == 1,
            np.clip(rng.lognormal(mean=np.log(15000), sigma=1.2, size=n) * (credit_norm * 0.7 + 0.3), 100, 500000),
            np.nan,
        )
        salary_credit_regularity = np.where(is_existing_customer == 1, np.clip(rng.beta(8, 2, size=n), 0, 1), np.nan)
        num_dishonours_12m = np.where(
            is_existing_customer == 1,
            np.where(credit_norm > 0.6, rng.choice([0, 0, 0, 0, 1], size=n), rng.choice([0, 0, 1, 1, 2, 3], size=n)),
            np.nan,
        ).astype(float)
        avg_monthly_savings_rate = np.where(
            is_existing_customer == 1, np.clip(rng.normal(0.12, 0.08, size=n) + credit_norm * 0.05, -0.10, 0.50), np.nan
        )
        days_in_overdraft_12m = np.where(
            is_existing_customer == 1,
            np.where(
                credit_norm > 0.6,
                rng.choice([0, 0, 0, 0, 0, 1, 2, 3], size=n),
                rng.choice([0, 0, 5, 10, 15, 20, 30, 45], size=n),
            ),
            np.nan,
        ).astype(float)

        # =============================================================
        # FRAUD SIGNALS
        # =============================================================
        is_fraud_signal = (rng.random(n) < 0.02).astype(int)

        income_verification_gap = np.where(
            is_fraud_signal == 1, rng.uniform(1.20, 2.00, size=n), np.clip(rng.normal(1.0, 0.03, size=n), 0.90, 1.10)
        ).round(3)

        address_tenure_months = np.where(
            is_fraud_signal == 1,
            rng.choice([1, 2, 3, 4, 5, 6], size=n),
            np.clip((rng.exponential(36, size=n)).astype(int), 1, 360),
        )

        document_consistency_score = np.where(
            is_fraud_signal == 1,
            np.clip(rng.normal(0.35, 0.15, size=n), 0.0, 0.60),
            np.clip(rng.beta(8, 2, size=n), 0.5, 1.0),
        ).round(3)

        # === Open Banking Features ===
        surplus = annual_income / 12 - monthly_expenses
        savings_prob = np.clip(surplus / 3000, 0.1, 0.9)
        savings_roll = rng.random(n)
        ob_savings_trend_3m = np.where(
            savings_roll < savings_prob * 0.6,
            "positive",
            np.where(savings_roll < savings_prob * 0.6 + 0.3, "flat", "negative"),
        )

        age_factor = np.clip((age_proxy - 20) / 40, 0, 1)
        ob_discretionary_spend_ratio = np.clip(rng.beta(3, 5, size=n) + (1 - age_factor) * 0.15, 0.05, 0.85).round(2)

        age_gambling_mult = np.where(
            age_proxy < 25, 1.4, np.where(age_proxy < 35, 1.7, np.where(age_proxy < 50, 1.0, 0.6))
        )
        state_gambling_mult = np.ones(n)
        for s, m in {
            "NSW": 1.15,
            "NT": 1.20,
            "VIC": 1.05,
            "QLD": 1.00,
            "WA": 0.95,
            "SA": 0.90,
            "TAS": 0.85,
            "ACT": 0.90,
        }.items():
            state_gambling_mult[state == s] = m

        gambling_roll = rng.random(n)
        problem_thresh = 0.029 * age_gambling_mult * state_gambling_mult
        moderate_thresh = problem_thresh + 0.058 * age_gambling_mult * state_gambling_mult
        low_thresh = moderate_thresh + 0.075 * age_gambling_mult * state_gambling_mult

        gambling_spend_ratio = np.where(
            gambling_roll < problem_thresh,
            np.clip(rng.uniform(0.05, 0.15, size=n), 0.05, 0.15),
            np.where(
                gambling_roll < moderate_thresh,
                np.clip(rng.uniform(0.02, 0.05, size=n), 0.02, 0.05),
                np.where(gambling_roll < low_thresh, np.clip(rng.uniform(0.005, 0.02, size=n), 0.005, 0.02), 0.0),
            ),
        ).round(4)
        has_gambling = gambling_spend_ratio > 0
        ob_gambling_transaction_flag = has_gambling

        bnpl_lambda = np.where(age_proxy < 35, 1.5, 0.5) * np.where(credit_score < 700, 1.3, 0.8)
        ob_bnpl_active_count = np.clip(rng.poisson(bnpl_lambda), 0, 8)

        financial_stress = np.clip((monthly_expenses * 12 / annual_income - 0.5) * 5, 0, 3)
        ob_overdraft_frequency_90d = np.clip(rng.poisson(financial_stress), 0, 15)

        income_noise_ob = np.abs(rng.normal(0, 0.08, size=n))
        se_noise = np.where(employment_type == "self_employed", 0.12, 0)
        ob_income_verification_score = np.clip(1.0 - income_noise_ob - se_noise, 0.3, 1.0).round(2)

        # =============================================================
        # CCR features
        # =============================================================
        late_pay_lambda = np.where(credit_norm > 0.7, 0.2, np.where(credit_norm > 0.4, 1.5, 4.0))
        ccr_num_late_payments_24m = np.clip(rng.poisson(late_pay_lambda), 0, 20)

        worst_late_buckets = [0, 14, 30, 60, 90]
        worst_late_probs_good = [0.85, 0.08, 0.04, 0.02, 0.01]
        worst_late_probs_bad = [0.20, 0.15, 0.25, 0.20, 0.20]
        worst_late_probs = np.where(
            credit_norm[:, None] > 0.6,
            np.tile(worst_late_probs_good, (n, 1)),
            np.tile(worst_late_probs_bad, (n, 1)),
        )
        ccr_worst_late_payment_days = np.array([rng.choice(worst_late_buckets, p=p) for p in worst_late_probs])

        ccr_total_credit_limit = np.clip(
            rng.lognormal(mean=np.log(annual_income * 0.3), sigma=0.5, size=n), 1000, 500000
        ).round(2)

        ccr_credit_utilization_pct = np.clip(rng.beta(2, 5, size=n) + (1 - credit_norm) * 0.3, 0.0, 1.0).round(3)

        hardship_prob = np.where(credit_norm > 0.6, 0.02, np.where(credit_norm > 0.3, 0.08, 0.18))
        ccr_num_hardship_flags = np.where(
            rng.random(n) < hardship_prob, rng.choice([1, 2, 3], size=n, p=[0.7, 0.2, 0.1]), 0
        )

        has_default = num_defaults_5yr > 0
        ccr_months_since_last_default = np.where(
            has_default, np.clip(rng.exponential(24, size=n).astype(int), 1, 60), np.nan
        ).astype(float)

        ccr_num_credit_providers = np.clip(rng.poisson(np.where(credit_norm > 0.5, 3, 2), size=n), 1, 15)

        # =============================================================
        # BNPL-specific features
        # =============================================================
        has_bnpl_mask = num_bnpl_accounts > 0
        ccr_bnpl_total_limit = np.where(
            has_bnpl_mask, np.clip(num_bnpl_accounts * rng.uniform(500, 2000, size=n), 0, 15000), 0
        ).round(2)

        ccr_bnpl_utilization_pct = np.where(has_bnpl_mask, np.clip(rng.beta(3, 4, size=n), 0, 1), 0).round(3)

        ccr_bnpl_late_payments_12m = np.where(
            has_bnpl_mask,
            np.where(credit_norm > 0.6, rng.choice([0, 0, 0, 1], size=n), rng.choice([0, 1, 2, 3], size=n)),
            0,
        )

        ccr_bnpl_monthly_commitment = np.where(
            has_bnpl_mask, np.clip(ccr_bnpl_total_limit * rng.uniform(0.05, 0.15, size=n), 0, 2000), 0
        ).round(2)

        # =============================================================
        # CDR/Open Banking transaction features
        # =============================================================
        cdr_income_source_count = np.where(
            employment_type == "self_employed",
            rng.choice([1, 2, 3, 4], size=n, p=[0.15, 0.35, 0.30, 0.20]),
            rng.choice([1, 2, 3], size=n, p=[0.65, 0.25, 0.10]),
        )

        is_renter = np.array([h == "rent" for h in home_ownership])
        cdr_rent_payment_regularity = np.where(
            is_renter, np.clip(rng.beta(8, 2, size=n) * (credit_norm * 0.3 + 0.7), 0.3, 1.0), np.nan
        ).astype(float)

        cdr_utility_payment_regularity = np.clip(rng.beta(9, 2, size=n) * (credit_norm * 0.2 + 0.8), 0.4, 1.0).round(2)

        cdr_essential_to_total_spend = np.clip(rng.beta(5, 4, size=n) + number_of_dependants * 0.03, 0.20, 0.90).round(
            3
        )

        cdr_subscription_burden = np.clip(rng.lognormal(mean=np.log(0.04), sigma=0.6, size=n), 0.005, 0.30).round(4)

        cdr_balance_before_payday = np.clip(
            rng.lognormal(mean=np.log(2000), sigma=1.2, size=n) * (credit_norm * 0.6 + 0.4), -500, 50000
        ).round(2)

        cdr_min_balance_30d = np.clip(cdr_balance_before_payday * rng.uniform(0.1, 0.8, size=n), -2000, 40000).round(2)

        neg_bal_lambda = np.where(credit_norm > 0.7, 0.3, np.where(credit_norm > 0.4, 2.0, 6.0))
        cdr_days_negative_balance_90d = np.clip(rng.poisson(neg_bal_lambda), 0, 90)

        # =============================================================
        # Geographic risk features
        # =============================================================
        state_default_rates = {
            "NSW": 0.012,
            "VIC": 0.013,
            "QLD": 0.016,
            "WA": 0.015,
            "SA": 0.014,
            "TAS": 0.011,
            "ACT": 0.008,
            "NT": 0.020,
        }
        base_default_rate = np.array([state_default_rates.get(s, 0.015) for s in state])
        if self._benchmarks_raw and "sa4_unemployment" in self._benchmarks_raw:
            sa4_unemp = self._benchmarks_raw["sa4_unemployment"]
            national_avg_unemp = 0.040
            _sa3_to_sa4 = {sa3: sa4 for sa4, sa3_list in self._property_service._sa4_to_sa3.items() for sa3 in sa3_list}
            for i in range(n):
                sa4_code = _sa3_to_sa4.get(sa3_codes[i])
                if sa4_code:
                    local_unemp = sa4_unemp.get(sa4_code, national_avg_unemp)
                    unemp_factor = 1.0 + 0.5 * (local_unemp - national_avg_unemp) / national_avg_unemp
                    base_default_rate[i] *= max(unemp_factor, 0.5)
        geo_postcode_default_rate = base_default_rate + rng.normal(0, 0.003, size=n)
        geo_postcode_default_rate = np.clip(geo_postcode_default_rate, 0.002, 0.05).round(4)

        _high_risk_industries = {"A", "B", "E", "H"}
        _low_risk_industries = {"K", "O", "P", "Q"}
        _tiers = ["low", "medium", "high", "very_high"]
        geo_industry_risk_tier = np.empty(n, dtype="<U9")
        _low_mask = np.isin(industry_anzsic, list(_low_risk_industries))
        _high_mask = np.isin(industry_anzsic, list(_high_risk_industries))
        _other_mask = ~(_low_mask | _high_mask)
        if _low_mask.sum() > 0:
            geo_industry_risk_tier[_low_mask] = rng.choice(_tiers, size=_low_mask.sum(), p=[0.55, 0.30, 0.12, 0.03])
        if _high_mask.sum() > 0:
            geo_industry_risk_tier[_high_mask] = rng.choice(_tiers, size=_high_mask.sum(), p=[0.20, 0.35, 0.30, 0.15])
        if _other_mask.sum() > 0:
            geo_industry_risk_tier[_other_mask] = rng.choice(_tiers, size=_other_mask.sum(), p=[0.40, 0.35, 0.18, 0.07])

        # =============================================================
        # Phase 2: Behavioral realism features
        # =============================================================
        behavioral_rngs = rng.spawn(6)

        application_channel = self._assign_application_channel(age_proxy, purpose, sub_pop, behavioral_rngs[0])

        inflated_income, _true_income, strategic_gap = self._apply_income_inflation(
            annual_income, employment_type, is_fraud_signal, behavioral_rngs[1]
        )
        is_strategic_inflator = strategic_gap > 1.0
        annual_income = inflated_income
        income_verification_gap = np.where(
            is_strategic_inflator & (is_fraud_signal == 0),
            strategic_gap,
            income_verification_gap,
        )

        loan_amount, optimism_bias_flag = self._apply_optimism_bias(loan_amount, age_proxy, sub_pop, behavioral_rngs[2])
        loan_amount = np.clip(loan_amount, 5000, 3500000)
        new_loan_dti = loan_amount / annual_income
        debt_to_income = (existing_dti + new_loan_dti).round(2)

        financial_literacy_score = self._assign_financial_literacy(age_proxy, credit_score, sub_pop, behavioral_rngs[3])

        loan_trigger_event = self._assign_life_event_trigger(purpose, sub_pop, behavioral_rngs[5])

        product_rate = self._compute_product_rates(rba_cash_rate, purpose, sub_pop, n)

        data = {
            "annual_income": annual_income,
            "credit_score": credit_score,
            "loan_amount": loan_amount,
            "loan_term_months": loan_term_months,
            "debt_to_income": debt_to_income,
            "employment_length": employment_length,
            "purpose": purpose,
            "home_ownership": home_ownership,
            "has_cosigner": has_cosigner,
            "property_value": property_value,
            "deposit_amount": deposit_amount,
            "monthly_expenses": monthly_expenses,
            "existing_credit_card_limit": existing_credit_card_limit,
            "monthly_rent": monthly_rent,
            "number_of_dependants": number_of_dependants,
            "employment_type": employment_type,
            "applicant_type": applicant_type,
            "has_hecs": has_hecs,
            "hecs_debt_balance": hecs_debt_balance,
            "help_repayment_monthly": help_repayment_monthly,
            "has_bankruptcy": has_bankruptcy,
            "existing_property_count": existing_property_count,
            "state": state,
            "sa3_region": sa3_codes,
            "sa3_name": sa3_names,
            "industry_anzsic": industry_anzsic,
            "application_date": application_date,
            "application_quarter": application_quarter,
            "origination_quarter": pd.to_datetime(application_date).to_period("Q").astype(str),
            "cash_rate": rba_cash_rate,
            "product_rate": product_rate,
            "stress_test_rate": product_rate + self.STRESS_TEST_BUFFER,
            "rba_cash_rate": rba_cash_rate,
            "unemployment_rate": unemployment_rate,
            "property_growth_12m": property_growth_12m,
            "consumer_confidence": consumer_confidence,
            "num_credit_enquiries_6m": num_credit_enquiries_6m,
            "worst_arrears_months": worst_arrears_months,
            "num_defaults_5yr": num_defaults_5yr,
            "credit_history_months": credit_history_months,
            "total_open_accounts": total_open_accounts,
            "num_bnpl_accounts": num_bnpl_accounts,
            "cash_advance_count_12m": cash_advance_count_12m,
            "is_existing_customer": is_existing_customer,
            "savings_balance": savings_balance,
            "salary_credit_regularity": salary_credit_regularity,
            "num_dishonours_12m": num_dishonours_12m,
            "avg_monthly_savings_rate": avg_monthly_savings_rate,
            "days_in_overdraft_12m": days_in_overdraft_12m,
            "is_fraud_signal": is_fraud_signal,
            "income_verification_gap": income_verification_gap,
            "address_tenure_months": address_tenure_months,
            "document_consistency_score": document_consistency_score,
            "savings_trend_3m": ob_savings_trend_3m,
            "discretionary_spend_ratio": ob_discretionary_spend_ratio,
            "gambling_transaction_flag": ob_gambling_transaction_flag.astype(int),
            "gambling_spend_ratio": gambling_spend_ratio,
            "bnpl_active_count": ob_bnpl_active_count,
            "overdraft_frequency_90d": ob_overdraft_frequency_90d,
            "income_verification_score": ob_income_verification_score,
            "num_late_payments_24m": ccr_num_late_payments_24m,
            "worst_late_payment_days": ccr_worst_late_payment_days,
            "total_credit_limit": ccr_total_credit_limit,
            "credit_utilization_pct": ccr_credit_utilization_pct,
            "num_hardship_flags": ccr_num_hardship_flags,
            "months_since_last_default": ccr_months_since_last_default,
            "num_credit_providers": ccr_num_credit_providers,
            "bnpl_total_limit": ccr_bnpl_total_limit,
            "bnpl_utilization_pct": ccr_bnpl_utilization_pct,
            "bnpl_late_payments_12m": ccr_bnpl_late_payments_12m,
            "bnpl_monthly_commitment": ccr_bnpl_monthly_commitment,
            "income_source_count": cdr_income_source_count,
            "rent_payment_regularity": cdr_rent_payment_regularity,
            "utility_payment_regularity": cdr_utility_payment_regularity,
            "essential_to_total_spend": cdr_essential_to_total_spend,
            "subscription_burden": cdr_subscription_burden,
            "balance_before_payday": cdr_balance_before_payday,
            "min_balance_30d": cdr_min_balance_30d,
            "days_negative_balance_90d": cdr_days_negative_balance_90d,
            "postcode_default_rate": geo_postcode_default_rate,
            "industry_risk_tier": geo_industry_risk_tier,
            "application_channel": application_channel,
            "optimism_bias_flag": optimism_bias_flag,
            "financial_literacy_score": financial_literacy_score,
            "loan_trigger_event": loan_trigger_event,
        }

        df = pd.DataFrame(data)
        df["_existing_dti"] = existing_dti
        df["_age_proxy"] = age_proxy

        # --- Derived ratios ---
        _monthly_income = df["annual_income"] / 12.0
        _stressed_rate = df["stress_test_rate"].values / 100 / 12
        _term = df["loan_term_months"].clip(lower=1)
        df["stressed_repayment"] = np.where(
            _term > 0,
            df["loan_amount"] * _stressed_rate * (1 + _stressed_rate) ** _term / ((1 + _stressed_rate) ** _term - 1),
            0.0,
        )
        df["stressed_dsr"] = np.where(
            _monthly_income > 0,
            df["stressed_repayment"] / _monthly_income,
            0.0,
        )
        df["hem_surplus"] = _monthly_income - df["monthly_expenses"] - df["stressed_repayment"]
        _cc_commit = df["existing_credit_card_limit"] * 0.03
        _bnpl_commit = df["bnpl_monthly_commitment"]
        df["uncommitted_monthly_income"] = (
            _monthly_income - df["monthly_expenses"] - _cc_commit - _bnpl_commit - df["stressed_repayment"]
        )
        df["savings_to_loan_ratio"] = np.where(
            df["loan_amount"] > 0,
            df["savings_balance"].fillna(0) / df["loan_amount"],
            0.0,
        )
        _total_debt_service = df["stressed_repayment"] + _cc_commit + _bnpl_commit
        df["debt_service_coverage"] = np.where(
            _total_debt_service > 0,
            _monthly_income / _total_debt_service,
            10.0,
        )
        df["bnpl_to_income_ratio"] = np.where(
            _monthly_income > 0,
            _bnpl_commit / _monthly_income,
            0.0,
        )
        df["enquiry_to_account_ratio"] = np.where(
            df["total_open_accounts"] > 0,
            df["num_credit_enquiries_6m"] / np.maximum(df["total_open_accounts"], 1),
            0.0,
        )
        df["stress_index"] = np.clip(
            df["credit_utilization_pct"].fillna(0.3) * 30
            + df["days_negative_balance_90d"] * 1.5
            + df["overdraft_frequency_90d"] * 3
            + df["stressed_dsr"] * 40,
            0,
            100,
        )
        df["log_annual_income"] = np.log1p(df["annual_income"])
        df["log_loan_amount"] = np.log1p(df["loan_amount"])

        # Compute approval using TRUE values (banks verify documents)
        approved, approval_type, conditions_list = self._compute_approval(df, rng)
        df["approved"] = approved
        df["approval_type"] = approval_type
        df["conditions"] = conditions_list
        df["requires_human_review"] = np.isin(approval_type, ["human_review", "review"])
        df["n_conditions"] = [len(c) for c in conditions_list]

        # 2E. Prepayment buffer + negative equity (computed after approval)
        buffer_months, neg_equity = self._compute_prepayment_buffer(df, behavioral_rngs[4])
        df["prepayment_buffer_months"] = buffer_months
        df["negative_equity_flag"] = neg_equity

        df.drop(columns=["_existing_dti", "_age_proxy"], inplace=True)

        # Default probability calibrated to real APRA/RBA/S&P statistics
        df["default_probability"] = self._calibrate_default_probability(df, rng)

        # =========================================================
        # MEASUREMENT NOISE
        # =========================================================
        income_noise = rng.normal(1.0, 0.08, size=n)
        df["annual_income"] = np.clip((df["annual_income"] * income_noise).round(2), 30000, 600000)

        expense_noise = rng.normal(0.70, 0.15, size=n)
        df["monthly_expenses"] = np.clip((df["monthly_expenses"] * expense_noise).round(2), 800, 10000)

        credit_score_drift = rng.integers(-40, 41, size=n)
        df["credit_score"] = np.clip(df["credit_score"] + credit_score_drift, 300, 1200)
        df.loc[df["purpose"] == "home", "credit_score"] = df.loc[df["purpose"] == "home", "credit_score"].clip(
            lower=700
        )
        df.loc[df["purpose"] != "home", "credit_score"] = df.loc[df["purpose"] != "home", "credit_score"].clip(
            lower=650
        )

        if "hecs_debt_balance" in df.columns:
            hecs_noise = rng.normal(1.0, 0.10, size=n)
            df["hecs_debt_balance"] = np.where(
                df["hecs_debt_balance"] > 0,
                np.clip((df["hecs_debt_balance"] * hecs_noise).round(0), 5000, 120000),
                0.0,
            )

        if "monthly_rent" in df.columns:
            rent_noise = rng.normal(1.0, 0.05, size=n)
            df["monthly_rent"] = np.where(
                df["monthly_rent"] > 0,
                np.clip((df["monthly_rent"] * rent_noise).round(0), 800, 6000),
                0.0,
            )

        df["debt_to_income"] = (
            df["loan_amount"] / df["annual_income"] + existing_dti * (annual_income / df["annual_income"])
        ).round(2)

        # =========================================================
        # MISSING DATA
        # =========================================================
        expense_missing = rng.random(n) < 0.11
        df.loc[expense_missing, "monthly_expenses"] = np.nan

        cc_missing = rng.random(n) < 0.08
        df.loc[cc_missing, "existing_credit_card_limit"] = np.nan

        home_mask = df["purpose"] == "home"
        pv_missing = home_mask & (rng.random(n) < 0.05)
        df.loc[pv_missing, "property_value"] = np.nan
        df.loc[pv_missing, "deposit_amount"] = np.nan

        non_existing = df["is_existing_customer"] == 0
        bureau_cols = [
            "num_credit_enquiries_6m",
            "worst_arrears_months",
            "num_defaults_5yr",
            "credit_history_months",
            "total_open_accounts",
            "num_bnpl_accounts",
        ]
        for col in bureau_cols:
            miss_rate = rng.uniform(0.08, 0.12)
            bureau_missing = non_existing & (rng.random(n) < miss_rate)
            df.loc[bureau_missing, col] = np.nan

        thin_file = df["credit_history_months"].notna() & (df["credit_history_months"] < 36)
        for col in bureau_cols:
            thin_miss = thin_file & (rng.random(n) < 0.25)
            df.loc[thin_miss, col] = np.nan

        if "hecs_debt_balance" in df.columns:
            hecs_missing = (df["hecs_debt_balance"] > 0) & (rng.random(n) < 0.06)
            df.loc[hecs_missing, "hecs_debt_balance"] = np.nan

        if "monthly_rent" in df.columns:
            rent_missing = (df["monthly_rent"] > 0) & (rng.random(n) < 0.07)
            df.loc[rent_missing, "monthly_rent"] = np.nan

        if "cash_advance_count_12m" in df.columns:
            cash_adv_missing = rng.random(n) < 0.10
            df.loc[cash_adv_missing, "cash_advance_count_12m"] = np.nan

        if "gambling_spend_ratio" in df.columns:
            gambling_missing = rng.random(n) < 0.12
            df.loc[gambling_missing, "gambling_spend_ratio"] = np.nan

        # MNAR
        credit_norm_mnar = np.clip((df["credit_score"] - 300) / 900, 0, 1)
        mnar_prob = 0.08 * (1 - credit_norm_mnar)
        mnar_expense = (~expense_missing) & (rng.random(n) < mnar_prob)
        df.loc[mnar_expense, "monthly_expenses"] = np.nan
        mnar_cc = (~cc_missing) & (rng.random(n) < mnar_prob)
        df.loc[mnar_cc, "existing_credit_card_limit"] = np.nan

        # =========================================================
        # LABEL NOISE
        # =========================================================
        approved_mask = df["approved"] == 1
        n_approved = approved_mask.sum()
        if n_approved > 0:
            approved_dp = df.loc[approved_mask, "default_probability"].values
            flip_weights = approved_dp / max(approved_dp.mean(), 1e-6) * label_noise_rate
            flip_weights = np.clip(flip_weights, 0.0, 0.25)
            flip_mask = rng.random(n_approved) < flip_weights
            flip_indices = df.index[approved_mask][flip_mask]
            df.loc[flip_indices, "approved"] = 0
            df.loc[flip_indices, "approval_type"] = "denied"
            df.loc[flip_indices, "conditions"] = df.loc[flip_indices, "conditions"].apply(lambda _: [])
            df.loc[flip_indices, "n_conditions"] = 0

        # =========================================================
        # REJECT INFERENCE (parcelling method)
        # =========================================================
        denied_mask = df["approved"] == 0
        n_denied = denied_mask.sum()
        if n_denied > 0:
            denied_credit = df.loc[denied_mask, "credit_score"].values
            denied_dti = df.loc[denied_mask, "debt_to_income"].values

            credit_norm = np.clip((denied_credit - 650) / 400, 0, 1)
            dti_norm = np.clip(1 - denied_dti / 6.0, 0, 1)
            p_good = self.REJECT_INFERENCE_CREDIT_WEIGHT * credit_norm + self.REJECT_INFERENCE_DTI_WEIGHT * dti_norm

            would_have_repaid = (rng.random(n_denied) < p_good).astype(int)

            self.reject_inference_labels = pd.Series(np.nan, index=df.index, name="reject_inference_label")
            self.reject_inference_labels.loc[denied_mask] = would_have_repaid

        # === Outcome Simulation ===
        approved_mask = df["approved"] == 1

        base_pd = np.full(len(df), 0.015)

        base_pd = np.where(df["credit_score"] < 650, base_pd * 3.0, base_pd)
        base_pd = np.where(df["credit_score"] > 850, base_pd * 0.4, base_pd)
        base_pd = np.where(df["num_defaults_5yr"] > 0, base_pd * 2.5, base_pd)
        if "stress_index" in df.columns:
            base_pd = np.where(df["stress_index"] > 60, base_pd * 2.5, base_pd)
        if "overdraft_frequency_90d" in df.columns:
            base_pd = np.where(df["overdraft_frequency_90d"] > 5, base_pd * 2.0, base_pd)
        if "gambling_transaction_flag" in df.columns:
            base_pd = np.where(df["gambling_transaction_flag"], base_pd * 1.8, base_pd)
        if "worst_late_payment_days" in df.columns:
            base_pd = np.where(df["worst_late_payment_days"] >= 60, base_pd * 2.0, base_pd)
        if "bnpl_late_payments_12m" in df.columns:
            base_pd = np.where(df["bnpl_late_payments_12m"] > 2, base_pd * 1.5, base_pd)
        if "savings_to_loan_ratio" in df.columns:
            base_pd = np.where(df["savings_to_loan_ratio"] > 0.3, base_pd * 0.6, base_pd)
        if "debt_service_coverage" in df.columns:
            base_pd = np.where(df["debt_service_coverage"] > 2.0, base_pd * 0.5, base_pd)

        if "quarter" in df.columns:
            base_pd = np.where(df["quarter"] == 1, base_pd * 1.3, base_pd)
            base_pd = np.where(df["quarter"] == 3, base_pd * 1.15, base_pd)
            base_pd = np.where(df["quarter"] == 4, base_pd * 0.95, base_pd)

        base_pd = np.clip(base_pd, 0.001, 0.50)

        outcome_roll = rng.random(len(df))
        prepaid_threshold = 0.035

        outcomes = np.where(
            ~approved_mask,
            None,
            np.where(
                outcome_roll < base_pd * 0.3,
                "arrears_90",
                np.where(
                    outcome_roll < base_pd * 0.6,
                    "arrears_60",
                    np.where(
                        outcome_roll < base_pd,
                        "arrears_30",
                        np.where(outcome_roll < base_pd + prepaid_threshold, "prepaid", "performing"),
                    ),
                ),
            ),
        )
        default_roll = rng.random(len(df))
        outcomes = np.where((outcomes == "arrears_90") & (default_roll < 0.5), "default", outcomes)

        df["actual_outcome"] = outcomes

        df["months_to_outcome"] = np.where(
            approved_mask & df["actual_outcome"].isin(["default", "arrears_90"]),
            np.clip(rng.lognormal(mean=np.log(18), sigma=0.5, size=len(df)).astype(int), 3, 36),
            np.where(
                approved_mask & df["actual_outcome"].isin(["arrears_30", "arrears_60"]),
                np.clip(rng.lognormal(mean=np.log(12), sigma=0.6, size=len(df)).astype(int), 1, 36),
                np.where(
                    approved_mask & (df["actual_outcome"] == "prepaid"),
                    np.clip(rng.poisson(4, len(df)), 1, 12),
                    np.where(approved_mask, 12, np.nan),
                ),
            ),
        )

        df = self._simulate_loan_performance(df)

        return df

    @staticmethod
    def _sanitize_csv_value(val):
        """Prefix formula-injection characters to prevent Excel macro execution."""
        if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@"):
            return "'" + val
        return val

    def save_to_csv(self, df, path):
        """Save DataFrame to CSV, creating directories as needed."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        safe_df = df.apply(lambda col: col.map(self._sanitize_csv_value) if col.dtype == object else col)
        safe_df.to_csv(path, index=False)
        return path
