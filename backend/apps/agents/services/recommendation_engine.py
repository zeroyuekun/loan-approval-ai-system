"""Deterministic product recommendation engine for denied loan applicants.

Calculates which products the customer qualifies for using APRA serviceability
rules and real Australian lending criteria. All amounts, rates, and eligibility
are computed deterministically — the LLM only writes messaging text.

Financial constants (ASSESSMENT_BUFFER, BASE_RATE, FLOOR_RATE, HEM_TABLE,
INCOME_SHADING, tax brackets) are replicated from data_generator.py which is
the source of truth for the synthetic data pipeline.
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants — copied from ml_engine/services/data_generator.py
# ---------------------------------------------------------------------------

ASSESSMENT_BUFFER = 0.03
BASE_RATE = 0.065
FLOOR_RATE = 0.0575

HEM_TABLE = {
    ('single', 0, 'low'):  1600, ('single', 0, 'mid'):  2050, ('single', 0, 'high'): 2500,
    ('single', 1, 'low'):  2150, ('single', 1, 'mid'):  2600, ('single', 1, 'high'): 3050,
    ('single', 2, 'low'):  2500, ('single', 2, 'mid'):  3050, ('single', 2, 'high'): 3500,
    ('couple', 0, 'low'):  2400, ('couple', 0, 'mid'):  2950, ('couple', 0, 'high'): 3500,
    ('couple', 1, 'low'):  2850, ('couple', 1, 'mid'):  3400, ('couple', 1, 'high'): 3950,
    ('couple', 2, 'low'):  3200, ('couple', 2, 'mid'):  3850, ('couple', 2, 'high'): 4400,
}

INCOME_SHADING = {
    'payg_permanent': 1.00,
    'payg_casual': 0.80,
    'self_employed': 0.75,
    'contract': 0.85,
}

CREDIT_CARD_MONTHLY_RATE = 0.03


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CustomerSnapshot:
    """All financial data extracted once from LoanApplication + CustomerProfile."""

    # From application
    annual_income: float
    credit_score: int
    loan_amount: float
    loan_term_months: int
    debt_to_income: float
    employment_type: str
    employment_length: int
    applicant_type: str
    number_of_dependants: int
    purpose: str
    home_ownership: str
    property_value: float
    deposit_amount: float
    monthly_expenses: float
    existing_credit_card_limit: float
    has_cosigner: bool
    has_hecs: bool
    has_bankruptcy: bool

    # From profile
    savings_balance: float = 0.0
    checking_balance: float = 0.0
    account_tenure_years: int = 0
    loyalty_tier: str = 'standard'
    has_credit_card: bool = False
    has_mortgage: bool = False
    has_auto_loan: bool = False
    num_products: int = 1
    on_time_payment_pct: float = 100.0
    previous_loans_repaid: int = 0
    is_loyal_customer: bool = False

    # Derived — computed in __post_init__
    shaded_monthly_income: float = field(init=False)
    monthly_tax: float = field(init=False)
    hem_expenses: float = field(init=False)
    effective_expenses: float = field(init=False)
    existing_debt_monthly: float = field(init=False)
    credit_card_monthly: float = field(init=False)
    hecs_monthly: float = field(init=False)
    monthly_surplus: float = field(init=False)
    total_deposits: float = field(init=False)
    risk_tier: str = field(init=False)

    def __post_init__(self):
        shade = INCOME_SHADING.get(self.employment_type, 1.0)
        self.shaded_monthly_income = (self.annual_income * shade) / 12

        annual_tax = _calculate_tax(self.annual_income)
        self.monthly_tax = annual_tax / 12

        self.hem_expenses = _get_hem(
            self.applicant_type, self.number_of_dependants, self.annual_income,
        )
        self.effective_expenses = max(self.monthly_expenses, self.hem_expenses)

        # Existing debt servicing: replicate data_generator logic
        # debt_to_income includes the new loan; existing_dti = dti - (loan_amount / income)
        new_loan_dti = self.loan_amount / self.annual_income if self.annual_income > 0 else 0
        existing_dti = max(self.debt_to_income - new_loan_dti, 0)
        total_existing_debt = self.annual_income * existing_dti
        self.existing_debt_monthly = total_existing_debt * 0.0072

        self.credit_card_monthly = self.existing_credit_card_limit * CREDIT_CARD_MONTHLY_RATE

        self.hecs_monthly = (self.annual_income * 0.035 / 12) if self.has_hecs else 0.0

        # Monthly surplus BEFORE new loan repayment
        self.monthly_surplus = (
            self.shaded_monthly_income
            - self.monthly_tax
            - self.effective_expenses
            - self.existing_debt_monthly
            - self.credit_card_monthly
            - self.hecs_monthly
        )

        self.total_deposits = self.savings_balance + self.checking_balance
        self.risk_tier = _get_risk_tier(self.credit_score)


@dataclass
class ProductRecommendation:
    """A single calculated product offer."""

    product_id: str
    type: str
    name: str
    amount: float | None
    term_months: int | None
    estimated_rate: float | None
    monthly_repayment: float | None
    fortnightly_repayment: float | None
    benefit: str
    eligibility_met: bool
    eligibility_reasons: list[str]
    suitability_score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    reasoning: str = ''


# ---------------------------------------------------------------------------
# Standalone calculation helpers
# ---------------------------------------------------------------------------

def _calculate_tax(annual_income: float) -> float:
    """Australian Stage 3 marginal tax. Returns annual tax amount."""
    if annual_income <= 18200:
        return 0.0
    elif annual_income <= 45000:
        return (annual_income - 18200) * 0.16
    elif annual_income <= 135000:
        return 4288 + (annual_income - 45000) * 0.30
    elif annual_income <= 190000:
        return 31288 + (annual_income - 135000) * 0.37
    else:
        return 51638 + (annual_income - 190000) * 0.45


def _get_hem(applicant_type: str, dependants: int, annual_income: float) -> float:
    """HEM lookup — same logic as DataGenerator._get_hem."""
    if annual_income < 60000:
        bracket = 'low'
    elif annual_income < 120000:
        bracket = 'mid'
    else:
        bracket = 'high'
    dep_key = min(dependants, 2)
    return HEM_TABLE.get((applicant_type, dep_key, bracket), 2950)


def _get_risk_tier(credit_score: int) -> str:
    if credit_score >= 800:
        return 'premium'
    elif credit_score >= 750:
        return 'good'
    elif credit_score >= 700:
        return 'standard'
    elif credit_score >= 650:
        return 'subprime'
    else:
        return 'ineligible'


def _max_serviceable_amount(monthly_surplus: float, product_rate_pct: float, term_months: int) -> float:
    """Core APRA serviceability calc — solve annuity formula for max principal.

    Uses assessment rate (product rate + buffer, floored at FLOOR_RATE).
    monthly_surplus is surplus BEFORE the new loan repayment.
    """
    if monthly_surplus <= 0 or term_months <= 0:
        return 0.0

    assessment_rate = max(product_rate_pct / 100 + ASSESSMENT_BUFFER, FLOOR_RATE)
    r = assessment_rate / 12
    n = term_months

    # max_principal = surplus * ((1+r)^n - 1) / (r * (1+r)^n)
    compound = (1 + r) ** n
    if compound * r == 0:
        return 0.0
    return monthly_surplus * (compound - 1) / (r * compound)


def _monthly_repayment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    """Standard P&I repayment at the product rate (not assessment rate)."""
    if principal <= 0 or term_months <= 0 or annual_rate_pct <= 0:
        return 0.0
    r = annual_rate_pct / 100 / 12
    n = term_months
    compound = (1 + r) ** n
    return principal * r * compound / (compound - 1)


def _get_rate_for_tier(rate_tiers: dict, credit_score: int, purpose: str | None = None) -> float:
    """Look up rate from a product's rate_tiers dict by credit band.

    rate_tiers format:
      {'premium': X, 'good': X, 'standard': X, 'subprime': X}
      or with purpose: {'home': {...}, 'auto': {...}, ...}
    """
    tier = _get_risk_tier(credit_score)

    # Check if rates are purpose-segmented
    first_value = next(iter(rate_tiers.values()), None)
    if isinstance(first_value, dict):
        purpose_rates = rate_tiers.get(purpose, rate_tiers.get('personal', {}))
        return purpose_rates.get(tier, purpose_rates.get('subprime', 12.0))

    return rate_tiers.get(tier, rate_tiers.get('subprime', 12.0))


# ---------------------------------------------------------------------------
# Product Catalog
# ---------------------------------------------------------------------------

PRODUCT_CATALOG = {
    'reduced_loan': {
        'name': 'Reduced Amount Loan',
        'min_credit': 650,
        'min_employment_years': {'payg_permanent': 1, 'payg_casual': 1, 'self_employed': 2, 'contract': 1},
        'rate_tiers': {
            'home':      {'premium': 6.29, 'good': 6.49, 'standard': 6.79, 'subprime': 7.19},
            'auto':      {'premium': 7.49, 'good': 7.99, 'standard': 8.49, 'subprime': 9.49},
            'education': {'premium': 7.99, 'good': 8.49, 'standard': 8.99, 'subprime': 9.99},
            'personal':  {'premium': 8.99, 'good': 9.49, 'standard': 9.99, 'subprime': 11.99},
            'business':  {'premium': 8.49, 'good': 8.99, 'standard': 9.49, 'subprime': 10.99},
        },
        'min_amounts': {'home': 20000, 'auto': 5000, 'education': 5000, 'personal': 5000, 'business': 5000},
        'max_amount': 3000000,
        'terms': {'home': [240, 300, 360], 'other': [12, 24, 36, 60, 84]},
    },
    'secured_personal': {
        'name': 'Secured Personal Loan',
        'min_credit': 600,
        'min_savings': 5000,
        'rate_tiers': {'premium': 6.49, 'good': 7.49, 'standard': 8.49, 'subprime': 9.99},
        'max_amount': 100000,
        'terms': [12, 24, 36, 60, 84],
    },
    'unsecured_personal': {
        'name': 'Personal Loan',
        'min_credit': 700,
        'rate_tiers': {'premium': 8.99, 'good': 9.99, 'standard': 10.99, 'subprime': 12.49},
        'max_amount': 50000,
        'terms': [12, 24, 36, 60],
    },
    'low_rate_credit_card': {
        'name': 'Low Rate Credit Card',
        'min_credit': 700,
        'requires_no_existing_card': True,
        'fixed_rate': 11.99,
        'credit_limits': {'premium': 20000, 'good': 15000, 'standard': 10000, 'subprime': 5000},
    },
    'term_deposit': {
        'name': 'Term Deposit',
        'min_credit': None,
        'min_savings': 5000,
        'rate_tiers': {6: 4.50, 9: 4.70, 12: 4.90},
        'loyalty_bonus': 0.10,
    },
    'debt_consolidation': {
        'name': 'Debt Consolidation Loan',
        'min_credit': 650,
        'min_dti': 2.5,
        'rate_tiers': {'premium': 7.99, 'good': 9.49, 'standard': 10.99, 'subprime': 12.99},
        'max_amount': 100000,
        'terms': [24, 36, 60, 84],
    },
    'goal_saver_reapply': {
        'name': 'Goal Saver + Reapplication Pathway',
        'min_credit': None,
        'bonus_rate': 5.20,
    },
    'guarantor_loan': {
        'name': 'Family Guarantee Home Loan',
        'min_credit': 650,
        'home_only': True,
        'rate_tiers': {'premium': 6.19, 'good': 6.49, 'standard': 6.79, 'subprime': 7.19},
        'max_lvr_with_guarantor': 1.00,
    },
}


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------

class RecommendationEngine:
    """Deterministic product recommendation engine for denied applicants."""

    def recommend(self, application, denial_reasons: str = '') -> dict:
        """Entry point: build snapshot, evaluate products, score, and return results.

        Returns dict in the same shape the orchestrator/frontend already consume.
        """
        snapshot = self._build_customer_snapshot(application)

        # Evaluate all products
        evaluators = [
            self._evaluate_reduced_loan,
            self._evaluate_secured_personal,
            self._evaluate_unsecured_personal,
            self._evaluate_credit_card,
            self._evaluate_term_deposit,
            self._evaluate_debt_consolidation,
            self._evaluate_goal_saver,
            self._evaluate_guarantor_loan,
        ]

        recommendations = []
        for evaluator in evaluators:
            rec = evaluator(snapshot)
            if rec is not None and rec.eligibility_met:
                rec.suitability_score = self._score_product(rec, snapshot)
                recommendations.append(rec)

        # Sort by suitability score descending
        recommendations.sort(key=lambda r: r.suitability_score, reverse=True)

        # Take top 3; always include goal_saver if fewer than 2 eligible products
        top = recommendations[:3]
        has_goal_saver = any(r.product_id == 'goal_saver_reapply' for r in top)
        if len(top) < 2 and not has_goal_saver:
            goal_saver = self._evaluate_goal_saver(snapshot)
            if goal_saver and goal_saver not in top:
                goal_saver.suitability_score = self._score_product(goal_saver, snapshot)
                top.append(goal_saver)

        retention_score = self._build_retention_score(snapshot)
        loyalty_factors = self._build_loyalty_factors(snapshot)

        offers = []
        for rec in top:
            offers.append({
                'type': rec.type,
                'name': rec.name,
                'amount': round(rec.amount, 2) if rec.amount else None,
                'term_months': rec.term_months,
                'estimated_rate': rec.estimated_rate,
                'benefit': rec.benefit,
                'reasoning': rec.reasoning,  # Empty — LLM fills this
                'monthly_repayment': round(rec.monthly_repayment, 2) if rec.monthly_repayment else None,
                'fortnightly_repayment': round(rec.fortnightly_repayment, 2) if rec.fortnightly_repayment else None,
                'suitability_score': round(rec.suitability_score, 3),
                'score_breakdown': rec.score_breakdown,
            })

        return {
            'customer_retention_score': retention_score,
            'loyalty_factors': loyalty_factors,
            'offers': offers,
            'analysis': '',  # LLM fills this
            'personalized_message': '',  # LLM fills this
        }

    # -------------------------------------------------------------------
    # Snapshot builder
    # -------------------------------------------------------------------

    def _build_customer_snapshot(self, application) -> CustomerSnapshot:
        """Extract all financial data from LoanApplication + CustomerProfile."""
        kwargs = {
            'annual_income': float(application.annual_income),
            'credit_score': application.credit_score,
            'loan_amount': float(application.loan_amount),
            'loan_term_months': application.loan_term_months,
            'debt_to_income': float(application.debt_to_income),
            'employment_type': application.employment_type,
            'employment_length': application.employment_length,
            'applicant_type': application.applicant_type,
            'number_of_dependants': application.number_of_dependants,
            'purpose': application.purpose,
            'home_ownership': application.home_ownership,
            'property_value': float(application.property_value or 0),
            'deposit_amount': float(application.deposit_amount or 0),
            'monthly_expenses': float(application.monthly_expenses or 0),
            'existing_credit_card_limit': float(application.existing_credit_card_limit or 0),
            'has_cosigner': bool(application.has_cosigner),
            'has_hecs': bool(application.has_hecs),
            'has_bankruptcy': bool(application.has_bankruptcy),
        }

        try:
            profile = application.applicant.profile
            kwargs.update({
                'savings_balance': float(profile.savings_balance),
                'checking_balance': float(profile.checking_balance),
                'account_tenure_years': profile.account_tenure_years,
                'loyalty_tier': profile.loyalty_tier,
                'has_credit_card': profile.has_credit_card,
                'has_mortgage': profile.has_mortgage,
                'has_auto_loan': profile.has_auto_loan,
                'num_products': profile.num_products,
                'on_time_payment_pct': profile.on_time_payment_pct,
                'previous_loans_repaid': profile.previous_loans_repaid,
                'is_loyal_customer': profile.is_loyal_customer,
            })
        except Exception:
            pass  # New customer — defaults are fine

        return CustomerSnapshot(**kwargs)

    # -------------------------------------------------------------------
    # Product evaluators
    # -------------------------------------------------------------------

    def _evaluate_reduced_loan(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Same-purpose loan at a reduced amount that passes APRA serviceability."""
        catalog = PRODUCT_CATALOG['reduced_loan']
        reasons = []

        if s.credit_score < catalog['min_credit']:
            return None

        min_emp = catalog['min_employment_years'].get(s.employment_type, 1)
        if s.employment_length < min_emp:
            return None

        if s.has_bankruptcy:
            return None

        rate = _get_rate_for_tier(catalog['rate_tiers'], s.credit_score, s.purpose)

        # Use original term if it's a valid choice, otherwise pick a reasonable default
        if s.purpose == 'home':
            available_terms = catalog['terms']['home']
        else:
            available_terms = catalog['terms']['other']

        term = s.loan_term_months if s.loan_term_months in available_terms else available_terms[-1]

        max_amount = _max_serviceable_amount(s.monthly_surplus, rate, term)
        max_amount = min(max_amount, catalog['max_amount'])

        # Round down to nearest $1,000
        max_amount = math.floor(max_amount / 1000) * 1000

        min_amount = catalog['min_amounts'].get(s.purpose, 5000)
        if max_amount < min_amount:
            return None

        # Only offer if >= 60% of requested amount
        if max_amount < s.loan_amount * 0.60:
            return None

        repayment = _monthly_repayment(max_amount, rate, term)
        fortnightly = repayment / 2

        pct_of_requested = round(max_amount / s.loan_amount * 100) if s.loan_amount > 0 else 0
        benefit = (
            f"${max_amount:,.0f} for {s.purpose} at {rate:.2f}% p.a. "
            f"({pct_of_requested}% of your requested amount), "
            f"${repayment:,.0f}/month repayments"
        )

        return ProductRecommendation(
            product_id='reduced_loan',
            type='reduced_loan',
            name=catalog['name'],
            amount=max_amount,
            term_months=term,
            estimated_rate=rate,
            monthly_repayment=repayment,
            fortnightly_repayment=fortnightly,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=reasons,
        )

    def _evaluate_secured_personal(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Secured personal loan against savings."""
        catalog = PRODUCT_CATALOG['secured_personal']

        if s.credit_score < catalog['min_credit']:
            return None
        if s.savings_balance < catalog['min_savings']:
            return None

        rate = _get_rate_for_tier(catalog['rate_tiers'], s.credit_score)

        max_amount = min(
            s.savings_balance * 0.90,
            _max_serviceable_amount(s.monthly_surplus, rate, 60),
            catalog['max_amount'],
        )
        max_amount = math.floor(max_amount / 1000) * 1000

        if max_amount < 2000:
            return None

        # Pick term to keep repayments under 15% of monthly income
        monthly_income = s.annual_income / 12
        target_repayment = monthly_income * 0.15

        term = 60  # default
        for t in catalog['terms']:
            rep = _monthly_repayment(max_amount, rate, t)
            if rep <= target_repayment:
                term = t
                break

        repayment = _monthly_repayment(max_amount, rate, term)
        fortnightly = repayment / 2

        benefit = (
            f"${max_amount:,.0f} secured against your ${s.savings_balance:,.0f} savings "
            f"at {rate:.2f}% p.a., ${repayment:,.0f}/month over {term} months"
        )

        return ProductRecommendation(
            product_id='secured_personal',
            type='secured_personal',
            name=catalog['name'],
            amount=max_amount,
            term_months=term,
            estimated_rate=rate,
            monthly_repayment=repayment,
            fortnightly_repayment=fortnightly,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    def _evaluate_unsecured_personal(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Unsecured personal loan."""
        catalog = PRODUCT_CATALOG['unsecured_personal']

        if s.credit_score < catalog['min_credit']:
            return None

        rate = _get_rate_for_tier(catalog['rate_tiers'], s.credit_score)

        max_amount = min(
            _max_serviceable_amount(s.monthly_surplus, rate, 60),
            catalog['max_amount'],
        )
        max_amount = math.floor(max_amount / 1000) * 1000

        if max_amount < 3000:
            return None

        # Pick the longest term that keeps it reasonable
        term = 60
        for t in sorted(catalog['terms'], reverse=True):
            rep = _monthly_repayment(max_amount, rate, t)
            if rep > 0:
                term = t
                break

        repayment = _monthly_repayment(max_amount, rate, term)
        fortnightly = repayment / 2

        benefit = (
            f"${max_amount:,.0f} unsecured personal loan at {rate:.2f}% p.a., "
            f"${repayment:,.0f}/month over {term} months"
        )

        return ProductRecommendation(
            product_id='unsecured_personal',
            type='unsecured_personal',
            name=catalog['name'],
            amount=max_amount,
            term_months=term,
            estimated_rate=rate,
            monthly_repayment=repayment,
            fortnightly_repayment=fortnightly,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    def _evaluate_credit_card(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Low rate credit card."""
        catalog = PRODUCT_CATALOG['low_rate_credit_card']

        if s.credit_score < catalog['min_credit']:
            return None
        if s.has_credit_card:
            return None

        tier = _get_risk_tier(s.credit_score)
        limit = catalog['credit_limits'].get(tier, 5000)

        # Minimum repayment estimate (3% of limit)
        min_monthly = limit * 0.03

        benefit = (
            f"${limit:,.0f} limit low rate credit card at {catalog['fixed_rate']:.2f}% p.a. "
            f"(~${min_monthly:,.0f}/month minimum repayment)"
        )

        return ProductRecommendation(
            product_id='low_rate_credit_card',
            type='credit_card',
            name=catalog['name'],
            amount=limit,
            term_months=None,
            estimated_rate=catalog['fixed_rate'],
            monthly_repayment=min_monthly,
            fortnightly_repayment=min_monthly / 2,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    def _evaluate_term_deposit(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Term deposit for savers."""
        catalog = PRODUCT_CATALOG['term_deposit']

        if s.savings_balance < catalog['min_savings']:
            return None

        # Pick optimal term — 12mo gives highest rate
        best_term = 12
        best_rate = catalog['rate_tiers'][12]

        # Loyalty bonus
        if s.is_loyal_customer:
            best_rate += catalog['loyalty_bonus']

        deposit_amount = math.floor(s.savings_balance / 100) * 100
        annual_interest = deposit_amount * best_rate / 100

        benefit = (
            f"${deposit_amount:,.0f} term deposit at {best_rate:.2f}% p.a. for {best_term} months "
            f"(~${annual_interest:,.0f} interest earned)"
        )

        return ProductRecommendation(
            product_id='term_deposit',
            type='term_deposit',
            name=catalog['name'],
            amount=deposit_amount,
            term_months=best_term,
            estimated_rate=best_rate,
            monthly_repayment=None,
            fortnightly_repayment=None,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    def _evaluate_debt_consolidation(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Debt consolidation loan for customers with multiple obligations."""
        catalog = PRODUCT_CATALOG['debt_consolidation']

        if s.credit_score < catalog['min_credit']:
            return None
        if s.debt_to_income < catalog['min_dti']:
            return None

        rate = _get_rate_for_tier(catalog['rate_tiers'], s.credit_score)

        # Estimate existing debt to consolidate
        new_loan_dti = s.loan_amount / s.annual_income if s.annual_income > 0 else 0
        existing_dti = max(s.debt_to_income - new_loan_dti, 0)
        estimated_debt = s.annual_income * existing_dti
        # Add credit card balance estimate (assume 50% utilisation)
        estimated_debt += s.existing_credit_card_limit * 0.50

        consolidation_amount = min(
            estimated_debt,
            _max_serviceable_amount(s.monthly_surplus, rate, 60),
            catalog['max_amount'],
        )
        consolidation_amount = math.floor(consolidation_amount / 1000) * 1000

        if consolidation_amount < 5000:
            return None

        term = 60
        repayment = _monthly_repayment(consolidation_amount, rate, term)
        fortnightly = repayment / 2

        # Estimate current monthly debt cost vs consolidated
        current_monthly_cost = s.existing_debt_monthly + s.credit_card_monthly
        monthly_saving = max(current_monthly_cost - repayment, 0)

        benefit = (
            f"Consolidate ${consolidation_amount:,.0f} of existing debt at {rate:.2f}% p.a., "
            f"${repayment:,.0f}/month over {term} months"
        )
        if monthly_saving > 50:
            benefit += f" (save ~${monthly_saving:,.0f}/month vs current repayments)"

        return ProductRecommendation(
            product_id='debt_consolidation',
            type='debt_consolidation',
            name=catalog['name'],
            amount=consolidation_amount,
            term_months=term,
            estimated_rate=rate,
            monthly_repayment=repayment,
            fortnightly_repayment=fortnightly,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    def _evaluate_goal_saver(self, s: CustomerSnapshot) -> ProductRecommendation:
        """Goal saver + reapplication pathway — always eligible."""
        catalog = PRODUCT_CATALOG['goal_saver_reapply']

        # Calculate suggested monthly savings to build toward reapplication
        # Target: save enough to strengthen the application in 12 months
        gap = s.loan_amount - _max_serviceable_amount(s.monthly_surplus, 7.0, s.loan_term_months)
        suggested_monthly = max(min(gap / 12, s.monthly_surplus * 0.30), 100) if s.monthly_surplus > 0 else 100
        suggested_monthly = round(suggested_monthly / 10) * 10  # Round to nearest $10

        annual_interest = suggested_monthly * 12 * catalog['bonus_rate'] / 100

        benefit = (
            f"Goal Saver account at {catalog['bonus_rate']:.2f}% p.a. bonus rate — "
            f"save ${suggested_monthly:,.0f}/month to strengthen your next application "
            f"(~${annual_interest:,.0f} interest in 12 months)"
        )

        return ProductRecommendation(
            product_id='goal_saver_reapply',
            type='savings',
            name=catalog['name'],
            amount=None,
            term_months=12,
            estimated_rate=catalog['bonus_rate'],
            monthly_repayment=None,
            fortnightly_repayment=None,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    def _evaluate_guarantor_loan(self, s: CustomerSnapshot) -> ProductRecommendation | None:
        """Family guarantee home loan — home purpose only."""
        catalog = PRODUCT_CATALOG['guarantor_loan']

        if s.purpose != 'home':
            return None
        if s.credit_score < catalog['min_credit']:
            return None

        rate = _get_rate_for_tier(catalog['rate_tiers'], s.credit_score)

        # With guarantor, can go up to 100% LVR (no LMI)
        max_amount = _max_serviceable_amount(s.monthly_surplus, rate, s.loan_term_months)
        max_amount = math.floor(max_amount / 1000) * 1000

        if max_amount < 50000:
            return None

        term = s.loan_term_months if s.loan_term_months in [240, 300, 360] else 300
        repayment = _monthly_repayment(max_amount, rate, term)
        fortnightly = repayment / 2

        pct_of_requested = round(max_amount / s.loan_amount * 100) if s.loan_amount > 0 else 0
        benefit = (
            f"${max_amount:,.0f} home loan with family guarantee at {rate:.2f}% p.a. "
            f"({pct_of_requested}% of your requested amount), "
            f"no LMI required, ${repayment:,.0f}/month"
        )

        return ProductRecommendation(
            product_id='guarantor_loan',
            type='guarantor_loan',
            name=catalog['name'],
            amount=max_amount,
            term_months=term,
            estimated_rate=rate,
            monthly_repayment=repayment,
            fortnightly_repayment=fortnightly,
            benefit=benefit,
            eligibility_met=True,
            eligibility_reasons=[],
        )

    # -------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------

    def _score_product(self, rec: ProductRecommendation, s: CustomerSnapshot) -> float:
        """Weighted composite suitability score (0.0 to 1.0)."""

        # Need alignment: how well does the product address the original purpose?
        need_map = {
            'reduced_loan': 1.0,        # Same purpose
            'guarantor_loan': 0.95,     # Same purpose with guarantee
            'debt_consolidation': 0.6,  # Addresses root cause
            'secured_personal': 0.7 if s.purpose in ('auto', 'personal') else 0.5,
            'unsecured_personal': 0.6 if s.purpose == 'personal' else 0.4,
            'low_rate_credit_card': 0.35,
            'term_deposit': 0.30,
            'goal_saver_reapply': 0.25,
        }
        need_alignment = need_map.get(rec.product_id, 0.3)

        # Affordability fit: repayment as % of surplus, peaks at 60% utilisation
        if rec.monthly_repayment and s.monthly_surplus > 0:
            utilisation = rec.monthly_repayment / s.monthly_surplus
            # Bell curve peaking at 0.6
            affordability_fit = max(0, 1.0 - abs(utilisation - 0.6) / 0.6)
        else:
            affordability_fit = 0.5  # Non-loan products

        # Gap coverage: how much of the original need does it cover?
        if rec.amount and s.loan_amount > 0:
            gap_coverage = min(rec.amount / s.loan_amount, 1.0)
        else:
            gap_coverage = 0.1

        # Relationship value: cross-sell potential
        relationship_value = 0.3  # Base
        existing_types = set()
        if s.has_credit_card:
            existing_types.add('credit_card')
        if s.has_mortgage:
            existing_types.add('home_loan')
        if s.has_auto_loan:
            existing_types.add('auto_loan')

        product_type_map = {
            'low_rate_credit_card': 'credit_card',
            'reduced_loan': 'home_loan' if s.purpose == 'home' else 'personal_loan',
            'guarantor_loan': 'home_loan',
            'secured_personal': 'personal_loan',
            'unsecured_personal': 'personal_loan',
            'debt_consolidation': 'consolidation',
            'term_deposit': 'deposit',
            'goal_saver_reapply': 'savings',
        }
        new_type = product_type_map.get(rec.product_id, 'other')
        if new_type not in existing_types:
            relationship_value += 0.3  # New product type bonus

        # Loyalty tier upgrade potential
        if s.num_products <= 2:
            relationship_value += 0.2
        if s.loyalty_tier in ('standard', 'silver'):
            relationship_value += 0.1

        relationship_value = min(relationship_value, 1.0)

        # Weighted composite
        score = (
            0.35 * need_alignment
            + 0.25 * affordability_fit
            + 0.20 * gap_coverage
            + 0.20 * relationship_value
        )

        rec.score_breakdown = {
            'need_alignment': round(need_alignment, 3),
            'affordability_fit': round(affordability_fit, 3),
            'gap_coverage': round(gap_coverage, 3),
            'relationship_value': round(relationship_value, 3),
        }

        return max(0.0, min(score, 1.0))

    # -------------------------------------------------------------------
    # Retention score
    # -------------------------------------------------------------------

    def _build_retention_score(self, s: CustomerSnapshot) -> int:
        """Deterministic retention score 0-100."""
        score = 0

        # Account tenure: 0-20pts
        if s.account_tenure_years >= 10:
            score += 20
        elif s.account_tenure_years >= 5:
            score += 15
        elif s.account_tenure_years >= 3:
            score += 10
        else:
            score += min(s.account_tenure_years * 3, 9)

        # Total deposits: 0-20pts
        if s.total_deposits >= 100000:
            score += 20
        elif s.total_deposits >= 50000:
            score += 16
        elif s.total_deposits >= 25000:
            score += 12
        elif s.total_deposits >= 10000:
            score += 8
        else:
            score += min(int(s.total_deposits / 2000), 7)

        # Num products: 0-15pts
        if s.num_products >= 5:
            score += 15
        elif s.num_products >= 4:
            score += 12
        elif s.num_products >= 3:
            score += 9
        elif s.num_products >= 2:
            score += 6
        else:
            score += 3

        # On-time payment pct: 0-15pts
        if s.on_time_payment_pct >= 100:
            score += 15
        elif s.on_time_payment_pct >= 95:
            score += 12
        elif s.on_time_payment_pct >= 90:
            score += 9
        else:
            score += 5

        # Loyalty tier: 0-15pts
        tier_points = {'standard': 3, 'silver': 6, 'gold': 10, 'platinum': 15}
        score += tier_points.get(s.loyalty_tier, 3)

        # Previous loans repaid: 0-15pts
        if s.previous_loans_repaid >= 3:
            score += 15
        elif s.previous_loans_repaid >= 2:
            score += 12
        elif s.previous_loans_repaid >= 1:
            score += 8
        else:
            score += 0

        return min(score, 100)

    def _build_loyalty_factors(self, s: CustomerSnapshot) -> list[str]:
        """Generate specific loyalty factors from the customer's profile data."""
        factors = []

        if s.account_tenure_years >= 3:
            factors.append(f"{s.account_tenure_years}-year banking relationship")
        if s.total_deposits >= 10000:
            factors.append(f"${s.total_deposits:,.0f} in total deposits")
        if s.num_products >= 3:
            factors.append(f"{s.num_products} active banking products")
        if s.on_time_payment_pct >= 95:
            factors.append(f"{s.on_time_payment_pct:.0f}% on-time payment history")
        if s.previous_loans_repaid >= 1:
            factors.append(f"{s.previous_loans_repaid} previous loan(s) successfully repaid")
        if s.loyalty_tier in ('gold', 'platinum'):
            factors.append(f"{s.loyalty_tier.capitalize()} tier customer")

        if not factors:
            factors.append("New customer — opportunity to build relationship")

        return factors
