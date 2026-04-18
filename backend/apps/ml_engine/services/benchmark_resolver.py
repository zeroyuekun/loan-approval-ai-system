"""Benchmark resolver — pulls live calibration parameters or falls back to hard-coded defaults.

Extracted from `DataGenerator` so benchmark resolution can be swapped out (e.g. for
production-data-only calibration) without touching synthetic-data generation logic.
"""

import numpy as np


class BenchmarkResolver:
    """Resolves calibration parameters from live benchmarks or hardcoded defaults.

    Extracted from DataGenerator to isolate benchmark-resolution logic.
    All methods accept the same parameters they did as DataGenerator methods.
    """

    # Baseline national industry weights (ABS Labour Force Aug 2025)
    _NATIONAL_INDUSTRY_WEIGHTS = [
        0.025,  # A Agriculture
        0.020,  # B Mining
        0.055,  # C Manufacturing
        0.095,  # E Construction
        0.091,  # G Retail
        0.065,  # H Accommodation/Food
        0.050,  # I Transport
        0.025,  # J Info/Media
        0.040,  # K Finance
        0.090,  # M Professional
        0.035,  # N Administrative
        0.060,  # O Public Admin
        0.085,  # P Education
        0.145,  # Q Healthcare
        0.019,  # S Other Services
    ]

    # State-specific adjustments (multipliers applied to national weights)
    _STATE_INDUSTRY_ADJUSTMENTS = {
        "NSW": {"K": 1.6, "M": 1.4, "J": 1.5, "A": 0.5, "B": 0.3},
        "VIC": {"K": 1.3, "M": 1.3, "P": 1.2, "A": 0.6, "B": 0.2},
        "QLD": {"A": 1.8, "B": 1.5, "H": 1.4, "E": 1.2, "K": 0.7},
        "WA": {"B": 4.0, "E": 1.4, "A": 1.3, "K": 0.6, "M": 0.7},
        "SA": {"C": 1.4, "A": 1.5, "Q": 1.1, "B": 0.8, "K": 0.7},
        "TAS": {"A": 2.0, "H": 1.5, "Q": 1.2, "K": 0.5, "B": 0.3},
        "ACT": {"O": 3.5, "P": 1.5, "M": 1.3, "A": 0.1, "B": 0.1, "C": 0.2},
        "NT": {"O": 2.0, "B": 2.5, "A": 1.5, "Q": 1.3, "K": 0.4},
    }

    # HELP repayment thresholds 2025-26 (ATO)
    HELP_REPAYMENT_THRESHOLDS = [
        (54_435, 0.00),
        (62_851, 0.01),
        (66_621, 0.02),
        (70_619, 0.025),
        (74_856, 0.03),
        (79_347, 0.035),
        (84_108, 0.04),
        (89_155, 0.045),
        (94_504, 0.05),
        (100_175, 0.055),
        (106_186, 0.06),
        (112_560, 0.065),
        (119_320, 0.07),
        (126_491, 0.075),
        (134_099, 0.08),
        (142_173, 0.085),
        (150_741, 0.09),
        (159_834, 0.095),
        (169_486, 0.10),
    ]

    # Temporal rate modelling — product rate = cash rate + spread
    RATE_SPREAD_OVER_CASH = 2.15  # Big 4 avg spread over RBA cash rate (%)

    # Quarterly RBA cash rate (actual historical + projected)
    RBA_RATE_HISTORY = {
        "2023Q3": 4.10,
        "2023Q4": 4.35,
        "2024Q1": 4.35,
        "2024Q2": 4.35,
        "2024Q3": 4.35,
        "2024Q4": 4.35,
        "2025Q1": 4.10,
        "2025Q2": 4.10,
        "2025Q3": 3.85,
        "2025Q4": 3.85,
        "2026Q1": 3.60,
        "2026Q2": 3.60,
    }

    # Property growth 12-month % by state and quarter (CoreLogic-calibrated)
    PROPERTY_GROWTH = {
        "2023Q3": {"NSW": 8.1, "VIC": 3.2, "QLD": 12.4, "WA": 15.8, "SA": 9.7, "TAS": -0.5, "ACT": 1.2, "NT": 0.8},
        "2023Q4": {"NSW": 10.2, "VIC": 4.1, "QLD": 13.1, "WA": 17.2, "SA": 11.3, "TAS": 0.2, "ACT": 2.0, "NT": 1.5},
        "2024Q1": {"NSW": 7.5, "VIC": 2.8, "QLD": 14.8, "WA": 20.1, "SA": 13.5, "TAS": 1.0, "ACT": 2.5, "NT": 2.0},
        "2024Q2": {"NSW": 5.8, "VIC": 1.5, "QLD": 13.2, "WA": 22.3, "SA": 14.1, "TAS": 0.8, "ACT": 1.8, "NT": 1.2},
        "2024Q3": {"NSW": 4.2, "VIC": 0.8, "QLD": 10.5, "WA": 18.7, "SA": 12.8, "TAS": 0.5, "ACT": 1.5, "NT": 0.9},
        "2024Q4": {"NSW": 3.5, "VIC": -0.2, "QLD": 8.8, "WA": 15.4, "SA": 11.2, "TAS": -0.3, "ACT": 0.8, "NT": 0.5},
        "2025Q1": {"NSW": 2.8, "VIC": -1.0, "QLD": 6.5, "WA": 10.2, "SA": 8.5, "TAS": -0.8, "ACT": 0.5, "NT": 0.2},
        "2025Q2": {"NSW": 3.2, "VIC": 0.5, "QLD": 5.8, "WA": 8.1, "SA": 7.2, "TAS": 0.0, "ACT": 1.0, "NT": 0.5},
        "2025Q3": {"NSW": 4.0, "VIC": 1.2, "QLD": 5.5, "WA": 7.5, "SA": 6.8, "TAS": 0.5, "ACT": 1.5, "NT": 0.8},
        "2025Q4": {"NSW": 4.5, "VIC": 2.0, "QLD": 5.2, "WA": 6.8, "SA": 6.5, "TAS": 1.0, "ACT": 2.0, "NT": 1.0},
        "2026Q1": {"NSW": 5.0, "VIC": 2.8, "QLD": 5.0, "WA": 6.2, "SA": 6.0, "TAS": 1.5, "ACT": 2.5, "NT": 1.2},
        "2026Q2": {"NSW": 5.2, "VIC": 3.0, "QLD": 4.8, "WA": 5.8, "SA": 5.5, "TAS": 1.8, "ACT": 2.8, "NT": 1.5},
    }

    # State unemployment rates by quarter (ABS Labour Force)
    UNEMPLOYMENT_RATES = {
        "2023Q3": {"NSW": 3.1, "VIC": 3.5, "QLD": 3.8, "WA": 3.2, "SA": 4.0, "TAS": 4.2, "ACT": 2.8, "NT": 3.5},
        "2023Q4": {"NSW": 3.3, "VIC": 3.7, "QLD": 3.9, "WA": 3.4, "SA": 4.1, "TAS": 4.3, "ACT": 2.9, "NT": 3.6},
        "2024Q1": {"NSW": 3.5, "VIC": 3.9, "QLD": 4.0, "WA": 3.5, "SA": 4.2, "TAS": 4.4, "ACT": 3.0, "NT": 3.7},
        "2024Q2": {"NSW": 3.8, "VIC": 4.2, "QLD": 4.2, "WA": 3.7, "SA": 4.5, "TAS": 4.6, "ACT": 3.2, "NT": 3.9},
        "2024Q3": {"NSW": 4.0, "VIC": 4.5, "QLD": 4.3, "WA": 3.8, "SA": 4.7, "TAS": 4.8, "ACT": 3.3, "NT": 4.0},
        "2024Q4": {"NSW": 4.1, "VIC": 4.6, "QLD": 4.2, "WA": 3.7, "SA": 4.6, "TAS": 4.7, "ACT": 3.2, "NT": 3.9},
        "2025Q1": {"NSW": 4.0, "VIC": 4.4, "QLD": 4.0, "WA": 3.5, "SA": 4.4, "TAS": 4.5, "ACT": 3.0, "NT": 3.7},
        "2025Q2": {"NSW": 3.8, "VIC": 4.2, "QLD": 3.8, "WA": 3.3, "SA": 4.2, "TAS": 4.3, "ACT": 2.9, "NT": 3.5},
        "2025Q3": {"NSW": 3.6, "VIC": 4.0, "QLD": 3.7, "WA": 3.2, "SA": 4.0, "TAS": 4.1, "ACT": 2.8, "NT": 3.4},
        "2025Q4": {"NSW": 3.5, "VIC": 3.8, "QLD": 3.5, "WA": 3.0, "SA": 3.8, "TAS": 3.9, "ACT": 2.7, "NT": 3.3},
        "2026Q1": {"NSW": 3.4, "VIC": 3.7, "QLD": 3.4, "WA": 2.9, "SA": 3.7, "TAS": 3.8, "ACT": 2.6, "NT": 3.2},
        "2026Q2": {"NSW": 3.3, "VIC": 3.6, "QLD": 3.3, "WA": 2.8, "SA": 3.6, "TAS": 3.7, "ACT": 2.5, "NT": 3.1},
    }

    # Westpac-Melbourne Institute Consumer Confidence Index (100 = neutral)
    CONSUMER_CONFIDENCE = {
        "2023Q3": 79.7,
        "2023Q4": 82.0,
        "2024Q1": 84.5,
        "2024Q2": 82.2,
        "2024Q3": 84.6,
        "2024Q4": 86.8,
        "2025Q1": 92.2,
        "2025Q2": 95.5,
        "2025Q3": 96.0,
        "2025Q4": 97.5,
        "2026Q1": 98.0,
        "2026Q2": 99.0,
    }

    ANZSIC_DIVISIONS = [
        "A",  # Agriculture
        "B",  # Mining
        "C",  # Manufacturing
        "E",  # Construction
        "G",  # Retail Trade
        "H",  # Accommodation/Food
        "I",  # Transport/Postal
        "J",  # Info/Media/Telecom
        "K",  # Financial/Insurance
        "M",  # Professional/Scientific
        "N",  # Administrative
        "O",  # Public Administration
        "P",  # Education/Training
        "Q",  # Healthcare/Social
        "S",  # Other Services
    ]

    def __init__(self, benchmarks: dict = None, use_live_macro: bool = False):
        self._benchmarks = benchmarks
        self._use_live_macro = use_live_macro
        self._macro_cache: dict = {}

    def resolve_income_params(self, pop_name, is_couple, state_mult, sub_populations):
        """Return (mean_array, sigma_array) for income lognormal."""
        pop = sub_populations[pop_name]
        inc_mean = np.where(is_couple, pop["income_couple_mean"], pop["income_single_mean"])
        inc_mean = inc_mean * state_mult
        inc_sigma = np.where(is_couple, 0.50, 0.55)

        if self._benchmarks and "income_percentiles" in self._benchmarks:
            live_p50 = self._benchmarks["income_percentiles"].get("P50")
            assumed_p50 = 74_100
            if live_p50 and live_p50 != assumed_p50:
                inc_mean = inc_mean * (live_p50 / assumed_p50)

        return inc_mean, inc_sigma

    def resolve_loan_multiplier(self, pop_name, sub_populations):
        """Return (mean, std) for loan-to-income multiplier."""
        pop = sub_populations[pop_name]
        mult_mean = pop["loan_mult_mean"]
        mult_std = pop["loan_mult_std"]

        if self._benchmarks and "avg_loan_sizes" in self._benchmarks:
            live_oo = self._benchmarks["avg_loan_sizes"].get("owner_occupier")
            assumed_oo = 693_801
            if live_oo and live_oo != assumed_oo and pop.get("purpose_override") == "home":
                mult_mean = mult_mean * (live_oo / assumed_oo)

        return mult_mean, mult_std

    def resolve_credit_score_params(self, pop_name, state_credit_adj, sub_populations):
        """Return (mean, std, state_adj) for credit score normal."""
        pop = sub_populations[pop_name]
        cs_mean = pop["credit_score_mean"]
        cs_std = pop["credit_score_std"]

        if self._benchmarks and "credit_score_distributions" in self._benchmarks:
            cs_dist = self._benchmarks["credit_score_distributions"]
            age_bracket_map = {
                "first_home_buyer": "31_40",
                "upgrader": "41_50",
                "refinancer": "41_50",
                "personal_borrower": "31_40",
                "business_borrower": "41_50",
                "investor": "41_50",
            }
            bracket = age_bracket_map.get(pop_name)
            if bracket and bracket in cs_dist:
                live_mean = cs_dist[bracket].get("mean")
                live_std = cs_dist[bracket].get("std")
                if live_mean:
                    cs_mean = live_mean
                if live_std:
                    cs_std = live_std

        return cs_mean, cs_std, state_credit_adj

    def resolve_default_base_rate(self):
        """Return base PD for calibrate_default_probability."""
        if self._benchmarks and "apra_arrears" in self._benchmarks:
            live_npl = self._benchmarks["apra_arrears"].get("npl_rate")
            if live_npl:
                return live_npl
        return 0.0104

    def resolve_macro_for_quarter(self, quarter, state):
        """Return macro indicators for a specific quarter+state.

        Results are cached per (quarter, state) to avoid repeated API calls.
        """
        cache_key = (quarter, state)
        if cache_key in self._macro_cache:
            return self._macro_cache[cache_key]

        latest_quarter = max(self.RBA_RATE_HISTORY.keys())
        if self._use_live_macro and quarter == latest_quarter:
            try:
                from .macro_data_service import MacroDataService

                if not hasattr(self, "_macro_svc"):
                    self._macro_svc = MacroDataService()
                result = {
                    "rba_cash_rate": self._macro_svc.get_rba_cash_rate(),
                    "unemployment_rate": self._macro_svc.get_unemployment_rate(state),
                    "property_growth_12m": self._macro_svc.get_property_growth(state),
                    "consumer_confidence": self._macro_svc.get_consumer_confidence(),
                }
                self._macro_cache[cache_key] = result
                return result
            except Exception:
                pass

        result = {
            "rba_cash_rate": self.RBA_RATE_HISTORY[quarter],
            "unemployment_rate": self.UNEMPLOYMENT_RATES[quarter][state],
            "property_growth_12m": self.PROPERTY_GROWTH[quarter][state],
            "consumer_confidence": self.CONSUMER_CONFIDENCE[quarter],
        }
        self._macro_cache[cache_key] = result
        return result

    def get_state_industry_weights(self, state_code: str) -> np.ndarray:
        """Return normalized industry probability weights for a state."""
        base = np.array(self._NATIONAL_INDUSTRY_WEIGHTS, dtype=float)
        adjustments = self._STATE_INDUSTRY_ADJUSTMENTS.get(state_code, {})
        for i, div in enumerate(self.ANZSIC_DIVISIONS):
            if div in adjustments:
                base[i] *= adjustments[div]
        base /= base.sum()
        return base

    def get_help_repayment_rate(self, income: float) -> float:
        """Return HELP repayment rate for given income (ATO 2025-26 thresholds)."""
        rate = 0.0
        for threshold, r in self.HELP_REPAYMENT_THRESHOLDS:
            if income >= threshold:
                rate = r
            else:
                break
        return rate

    def compute_product_rates(self, rba_cash_rate, purpose, sub_pop, n):
        """Compute product rates using F6 rate tiering when available."""
        base_spread = self.RATE_SPREAD_OVER_CASH  # ~2.15%

        if self._benchmarks and "f6_rates" in self._benchmarks:
            f6 = self._benchmarks["f6_rates"]
            oo_var = f6.get("owner_occupier_variable")
            inv_var = f6.get("investor_variable")
            # Fall back to per-record arrays if F6 keys missing
            if oo_var is None:
                oo_var = rba_cash_rate + base_spread
            if inv_var is None:
                inv_var = rba_cash_rate + base_spread + 0.31

            # Investor loans get higher rates
            is_investor = sub_pop == "investor"
            rates = np.where(is_investor, inv_var, oo_var)
            if np.ndim(rates) == 0:
                rates = np.full(n, float(rates))
            # Personal/business loans: higher margin
            is_non_home = purpose != "home"
            rates[is_non_home] = rba_cash_rate[is_non_home] + base_spread + 1.5
            return rates

        # Fallback: existing flat rate calculation
        return rba_cash_rate + base_spread
