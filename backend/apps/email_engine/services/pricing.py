"""Product pricing engine for loan approval emails.

Provides realistic Australian lending rates, fees, and repayment calculations
based on loan purpose, amount, term, credit score, and employment type.

Rate tables are based on Big 4 Australian bank published rates (2025/2026):
- Home loans: RBA cash rate + margin (~6.0-7.5% variable, ~5.8-6.8% fixed)
- Personal loans: 7.0-15.0% depending on security and credit
- Business loans: 8.0-14.0% depending on security, size, and credit
- Auto loans: 6.5-12.0% (secured by vehicle)
- Education loans: 7.0-10.0% (unsecured)

Comparison rates are calculated per ASIC RG 262 using a $30,000 benchmark
for unsecured products and $150,000 for home loans over 5 years / 25 years
respectively.
"""

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Rate tables by purpose, indexed by credit score band
# Each entry: (base_rate_fixed, base_rate_variable, comparison_rate_addon)
# ---------------------------------------------------------------------------

RATE_TABLE = {
    "home": {
        # Home loans: lower rates, secured by property
        "excellent": (5.89, 6.14, 0.35),  # credit >= 850
        "good": (6.19, 6.44, 0.38),  # credit >= 750
        "fair": (6.59, 6.89, 0.42),  # credit >= 650
        "low": (7.29, 7.59, 0.50),  # credit < 650
    },
    "auto": {
        # Auto loans: secured by vehicle
        "excellent": (6.49, 6.99, 0.45),
        "good": (7.49, 7.99, 0.52),
        "fair": (8.99, 9.49, 0.60),
        "low": (10.99, 11.49, 0.72),
    },
    "personal": {
        # Personal loans: unsecured, higher risk
        "excellent": (7.49, 7.99, 0.55),
        "good": (8.99, 9.49, 0.62),
        "fair": (10.99, 11.49, 0.70),
        "low": (13.49, 13.99, 0.85),
    },
    "business": {
        # Business loans: risk based on ABN tenure and financials
        "excellent": (8.49, 8.99, 0.58),
        "good": (9.49, 9.99, 0.65),
        "fair": (11.49, 11.99, 0.75),
        "low": (13.49, 13.99, 0.88),
    },
    "education": {
        # Education loans: unsecured, lower amounts
        "excellent": (6.99, 7.49, 0.50),
        "good": (7.99, 8.49, 0.55),
        "fair": (9.49, 9.99, 0.62),
        "low": (11.49, 11.99, 0.75),
    },
}

# Establishment fees by purpose
ESTABLISHMENT_FEES = {
    "home": 395.00,
    "auto": 295.00,
    "personal": 250.00,
    "business": 495.00,
    "education": 150.00,
}

# Employment type discount/premium (basis points adjustment)
EMPLOYMENT_ADJUSTMENTS = {
    "payg_permanent": -0.25,  # discount for stable employment
    "payg_casual": 0.50,  # premium for casual
    "self_employed": 0.35,  # premium for self-employed
    "contract": 0.25,  # small premium for contract
}


def _credit_band(credit_score):
    """Map Equifax AU score (0-1200) to rate band."""
    if credit_score >= 850:
        return "excellent"
    elif credit_score >= 750:
        return "good"
    elif credit_score >= 650:
        return "fair"
    else:
        return "low"


def _monthly_repayment(principal, annual_rate, term_months):
    """Calculate monthly P&I repayment."""
    if annual_rate <= 0 or term_months <= 0:
        return 0.0
    monthly_rate = annual_rate / 100 / 12
    if monthly_rate == 0:
        return principal / term_months
    payment = principal * monthly_rate * (1 + monthly_rate) ** term_months / ((1 + monthly_rate) ** term_months - 1)
    return round(payment, 2)


def _comparison_rate_irr(principal, annual_rate, term_months, establishment_fee, tol=1e-8, max_iter=100):
    """Calculate ASIC RG 262 comparison rate using Newton's method on the IRR.

    The comparison rate is the single annual rate at which the present value of
    all repayments equals the net loan amount (principal + fees financed).

    ASIC requires benchmark amounts:
      - $30,000 over 60 months for unsecured products
      - $150,000 over 300 months for home loans
    The caller is responsible for passing the correct benchmark values.
    """
    if annual_rate <= 0 or term_months <= 0:
        return annual_rate

    # Monthly repayment on the nominal loan (fees NOT rolled in)
    monthly_rate = annual_rate / 100 / 12
    monthly_payment = (
        principal * monthly_rate * (1 + monthly_rate) ** term_months / ((1 + monthly_rate) ** term_months - 1)
    )

    # The borrower receives (principal - establishment_fee) but repays monthly_payment
    # for term_months. The comparison rate is the IRR of this cash flow.
    net_amount = principal - establishment_fee

    # Newton's method: find r such that NPV(r) = 0
    # NPV(r) = -net_amount + sum_{t=1}^{N} monthly_payment / (1+r)^t
    r = annual_rate / 100 / 12  # initial guess = nominal monthly rate

    for _ in range(max_iter):
        # NPV and its derivative
        npv = -net_amount
        dnpv = 0.0
        discount = 1.0
        for t in range(1, term_months + 1):
            discount /= 1 + r
            npv += monthly_payment * discount
            dnpv -= t * monthly_payment * discount / (1 + r)

        if abs(npv) < tol:
            break

        if abs(dnpv) < 1e-14:
            break

        r = r - npv / dnpv

        # Guard against negative rates
        if r <= 0:
            r = 1e-6

    return round(r * 12 * 100, 2)


def _first_repayment_date(days_from_now=30):
    """Calculate first repayment date (approximately 30 days from today)."""
    target = date.today() + timedelta(days=days_from_now)
    # Round to the 25th of the month (common Australian bank repayment date)
    if target.day > 25:
        # Push to 25th of next month
        if target.month == 12:
            target = target.replace(year=target.year + 1, month=1, day=25)
        else:
            target = target.replace(month=target.month + 1, day=25)
    else:
        target = target.replace(day=25)
    return target


def _sign_by_date(days_from_now=14):
    """Calculate the sign-by date (14 days from today)."""
    return date.today() + timedelta(days=days_from_now)


def _format_date(d):
    """Format date as 'DD Month YYYY' (Australian style)."""
    return d.strftime("%-d %B %Y") if hasattr(d, "strftime") else str(d)


def _format_date_windows(d):
    """Format date as 'D Month YYYY' — works on Windows (no %-d)."""
    try:
        return d.strftime("%-d %B %Y")
    except ValueError:
        # Windows doesn't support %-d, use #-d or manual strip
        return d.strftime("%d %B %Y").lstrip("0")


def calculate_loan_pricing(application):
    """Calculate all pricing details for a loan application.

    Args:
        application: LoanApplication instance

    Returns:
        dict with all pricing fields ready for email template injection
    """
    purpose = application.purpose
    credit_score = application.credit_score
    loan_amount = float(application.loan_amount)
    term_months = application.loan_term_months or 60
    employment_type = application.employment_type

    band = _credit_band(credit_score)
    rates = RATE_TABLE.get(purpose, RATE_TABLE["personal"])
    base_fixed, base_variable, _comparison_addon = rates.get(band, rates["fair"])

    # Apply employment adjustment
    emp_adj = EMPLOYMENT_ADJUSTMENTS.get(employment_type, 0.0)
    fixed_rate = round(base_fixed + emp_adj, 2)
    round(base_variable + emp_adj, 2)

    # Use fixed rate as the primary rate for the email
    primary_rate = fixed_rate
    rate_type = "Fixed"

    # Fees
    establishment_fee = ESTABLISHMENT_FEES.get(purpose, 250.00)

    # Comparison rate via IRR per ASIC RG 262 using benchmark amounts
    if purpose == "home":
        benchmark_principal = 150_000.0
        benchmark_term = 300  # 25 years
    else:
        benchmark_principal = 30_000.0
        benchmark_term = 60  # 5 years
    comparison_rate = _comparison_rate_irr(
        benchmark_principal,
        primary_rate,
        benchmark_term,
        establishment_fee,
    )

    # Monthly repayment
    monthly_payment = _monthly_repayment(loan_amount, primary_rate, term_months)

    # Dates
    first_repayment = _first_repayment_date(30)
    sign_by = _sign_by_date(14)

    # Term in years for display
    term_years = term_months / 12
    if term_years == int(term_years):
        term_display = f"{term_months} months ({int(term_years)} years)"
    else:
        term_display = f"{term_months} months"

    # Comparison rate benchmark amount (ASIC standard)
    if purpose == "home":
        comparison_benchmark = "$150,000 secured home loan over a 25-year term"
    else:
        comparison_benchmark = f"$30,000 unsecured {purpose} loan over a 5-year term"

    return {
        "interest_rate": f"{primary_rate}% p.a.",
        "interest_rate_number": primary_rate,
        "rate_type": rate_type,
        "comparison_rate": f"{comparison_rate}% p.a.",
        "comparison_rate_number": comparison_rate,
        "loan_term_display": term_display,
        "loan_term_months": term_months,
        "monthly_payment": f"${monthly_payment:,.2f}",
        "monthly_payment_number": monthly_payment,
        "establishment_fee": f"${establishment_fee:,.2f}",
        "establishment_fee_number": establishment_fee,
        "first_repayment_date": _format_date_windows(first_repayment),
        "sign_by_date": _format_date_windows(sign_by),
        "comparison_benchmark": comparison_benchmark,
        "credit_band": band,
    }
