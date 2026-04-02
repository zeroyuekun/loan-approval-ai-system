"""Smart template emails replicating the Claude-generated email format.

These templates produce emails identical in structure, tone, and compliance
to what Claude generates — same Sarah Mitchell signoff, same section labels,
same AFCA/hardship/cooling-off elements, same Australian English conventions.

No API credits required. All applicant-specific details are dynamically filled.
"""

import hashlib
from datetime import date, timedelta


def _ref_number(purpose, applicant_name):
    """Generate a deterministic reference number from purpose + name."""
    type_codes = {
        "home": "HL",
        "auto": "VL",
        "personal": "PL",
        "business": "BL",
        "education": "EL",
    }
    code = type_codes.get(purpose.lower(), "PL")
    today = date.today().strftime("%Y%m%d")
    # Deterministic 4-digit suffix from name hash
    suffix = int(hashlib.sha256(applicant_name.encode()).hexdigest()[:4], 16) % 10000  # noqa: S324
    return f"{code}-{today}-{suffix:04d}"


def _loan_type(purpose):
    """Convert purpose to display loan type."""
    mapping = {
        "home": "Home Purchase",
        "auto": "Vehicle",
        "personal": "Personal",
        "business": "Business",
        "education": "Education",
    }
    return mapping.get(purpose.lower(), purpose.title())


def _first_name(applicant_name):
    """Extract first name from full name."""
    return applicant_name.split()[0] if applicant_name else "Customer"


# Denial reason explanations — contextual, dignity-preserving language
_REASON_EXPLANATIONS = {
    "Credit score below our lending threshold": (
        "Credit profile: Your credit profile at the time of assessment "
        "fell below the threshold we require for a loan of this type and size."
    ),
    "Debt-to-income ratio above acceptable range": (
        "Debt-to-income ratio: The total of your existing financial "
        "commitments relative to your verified income exceeded our "
        "serviceability thresholds."
    ),
    "Employment tenure below minimum requirement": (
        "Employment type and tenure: Your current employment arrangements "
        "fell outside the parameters we require for a loan of this size."
    ),
    "Income insufficient for requested loan amount": (
        "Income and loan amount: The requested loan amount relative to "
        "your verified income exceeded our serviceability thresholds."
    ),
    "Requested loan amount exceeds serviceable limit": (
        "Loan serviceability: The requested amount exceeded what our "
        "assessment determined to be a manageable repayment level based "
        "on your current financial position."
    ),
    "Debt service coverage outside acceptable range": (
        "Debt servicing capacity: Based on your income, existing debts, and "
        "living expenses, the total repayments required would exceed what we "
        "consider manageable for your current financial position."
    ),
    "Employment stability outside acceptable range": (
        "Employment stability: Your current employment type or length of time "
        "in your role fell outside the requirements for a loan of this size. "
        "We look for a demonstrated period of stable income."
    ),
    "Monthly repayment ratio outside acceptable range": (
        "Repayment affordability: The estimated monthly repayments for this "
        "loan would represent a higher share of your income than our "
        "lending criteria allow."
    ),
    "Stress index outside acceptable range": (
        "Financial resilience: Our assessment considers how your repayments "
        "would be affected if interest rates were to rise. Under a stressed "
        "scenario, the repayments may not be sustainable."
    ),
    "Bureau risk score outside acceptable range": (
        "Credit history: The information in your credit file, including "
        "enquiries, repayment history, and existing accounts, did not meet "
        "our requirements for a loan of this type."
    ),
    "Savings to loan ratio outside acceptable range": (
        "Savings position: The level of genuine savings relative to the "
        "loan amount was below what we require, as savings demonstrate "
        "capacity to manage repayments."
    ),
    "Rate stress buffer outside acceptable range": (
        "Rate stress buffer: Our assessment considers how your repayments "
        "would be affected if interest rates were to rise. Under a stressed "
        "scenario, the projected repayments exceeded what we consider "
        "sustainable for your financial position."
    ),
    "Stressed repayment capacity outside acceptable range": (
        "Stressed repayment capacity: Under a higher interest rate scenario, "
        "the estimated monthly repayments would exceed what our assessment "
        "determined to be affordable based on your current income and commitments."
    ),
    "Debt service ratio under stress outside acceptable range": (
        "Debt service ratio under stress: When your total debt repayments "
        "are assessed under a stressed interest rate, the ratio of repayments "
        "to income exceeded our serviceability threshold."
    ),
    "Financial stress indicators above acceptable range": (
        "Financial resilience: Our assessment considers how your repayments "
        "would be affected if interest rates were to rise. Under a stressed "
        "scenario, the repayments may not be sustainable."
    ),
    "Household expenditure surplus below acceptable range": (
        "Household expenditure surplus: After accounting for the household "
        "expenditure measure and your committed expenses, the remaining "
        "surplus was below the minimum we require to service this loan."
    ),
    "Uncommitted monthly income below acceptable range": (
        "Uncommitted monthly income: The portion of your income remaining "
        "after all existing financial commitments was below the minimum "
        "threshold for a loan of this size."
    ),
    "Employment type outside acceptable range": (
        "Employment type and tenure: Your current employment arrangements "
        "fell outside the parameters we require for a loan of this size."
    ),
    "Loan-to-income ratio above acceptable range": (
        "Loan-to-income ratio: The requested loan amount relative to your "
        "annual income exceeded our maximum lending ratio for this product."
    ),
    "Serviceability ratio outside acceptable range": (
        "Serviceability ratio: Your total financial commitments as a "
        "proportion of your income exceeded our serviceability threshold."
    ),
    "Expense-to-income ratio above acceptable range": (
        "Expense-to-income ratio: Your monthly expenses relative to your "
        "income exceeded the maximum ratio permitted under our lending criteria."
    ),
    "Net monthly surplus below acceptable range": (
        "Net monthly surplus: After all commitments and the proposed loan "
        "repayment, the remaining monthly surplus was below the minimum "
        "buffer we require."
    ),
    "Loan-to-value ratio above acceptable range": (
        "Loan-to-value ratio: The loan amount relative to the property "
        "value exceeded the maximum ratio for this loan product."
    ),
    "Deposit contribution below acceptable range": (
        "Deposit contribution: The deposit amount relative to the property "
        "value was below the minimum we require for this loan type."
    ),
    "Savings to loan ratio below acceptable range": (
        "Savings position: The level of genuine savings relative to the "
        "loan amount was below what we require, as savings demonstrate "
        "capacity to manage repayments."
    ),
    "Credit utilisation ratio above acceptable range": (
        "Credit utilisation: The proportion of your available credit that "
        "is currently in use exceeded our acceptable threshold."
    ),
    "Recent credit enquiry frequency above acceptable range": (
        "Credit enquiries: The number of credit enquiries on your file in "
        "the recent period exceeded the threshold we apply for this product."
    ),
}

# Improvement steps matched to denial reasons
_IMPROVEMENT_STEPS = {
    "Credit score below our lending threshold": (
        "Reviewing your credit report for accuracy and taking steps to "
        "strengthen your credit profile, such as reducing existing credit "
        "card limits, ensuring all bills are paid on time, and limiting "
        "new credit enquiries for the next 6\u201312 months."
    ),
    "Debt-to-income ratio above acceptable range": (
        "Reducing your existing debt obligations to improve your "
        "debt-to-income ratio. Consolidating high-interest debts or "
        "paying down revolving balances may help."
    ),
    "Employment tenure below minimum requirement": (
        "Establishing a longer tenure in your current role, or transitioning to a permanent employment arrangement."
    ),
    "Income insufficient for requested loan amount": (
        "Considering a reduced loan amount that sits within a sustainable repayment range relative to your income."
    ),
    "Requested loan amount exceeds serviceable limit": (
        "Considering a reduced loan amount that sits within a sustainable repayment range relative to your income."
    ),
    "Debt service coverage outside acceptable range": (
        "Reducing your existing debt obligations before reapplying. "
        "Paying down credit cards, personal loans, or BNPL balances will "
        "improve your debt servicing capacity."
    ),
    "Employment stability outside acceptable range": (
        "Establishing a longer period in your current role. For permanent "
        "employees, we typically look for at least 6 months of continuous "
        "employment; for self-employed applicants, at least 2 years of trading."
    ),
    "Monthly repayment ratio outside acceptable range": (
        "Considering a smaller loan amount or a longer loan term to reduce "
        "the monthly repayment, or increasing your income through additional "
        "employment before reapplying."
    ),
    "Stress index outside acceptable range": (
        "Reducing your overall debt position so that your repayments remain "
        "manageable even if interest rates were to rise by 2\u20133 percentage points."
    ),
    "Bureau risk score outside acceptable range": (
        "Reviewing your credit report for accuracy and taking steps to "
        "strengthen your credit profile. Paying all bills on time and "
        "limiting new credit applications for 6\u201312 months will help."
    ),
    "Savings to loan ratio outside acceptable range": (
        "Building your savings over time to demonstrate a pattern of regular "
        "saving. A higher deposit or savings balance strengthens your application."
    ),
    "Rate stress buffer outside acceptable range": (
        "Reducing your overall debt position so that your repayments remain "
        "manageable even if interest rates were to rise by 2\u20133 percentage points. "
        "A smaller loan amount or larger deposit would also help."
    ),
    "Stressed repayment capacity outside acceptable range": (
        "Reducing your overall debt position so that your repayments remain "
        "manageable under a higher interest rate scenario."
    ),
    "Debt service ratio under stress outside acceptable range": (
        "Reducing existing debt obligations before reapplying. Lower total "
        "debt improves your debt-service ratio under stress testing."
    ),
    "Financial stress indicators above acceptable range": (
        "Reducing your overall debt position so that your repayments remain "
        "manageable even if interest rates were to rise by 2\u20133 percentage points."
    ),
    "Household expenditure surplus below acceptable range": (
        "Reducing monthly expenses or increasing income to ensure a larger "
        "surplus after household costs and loan repayments."
    ),
    "Uncommitted monthly income below acceptable range": (
        "Reducing existing financial commitments or increasing income so that "
        "a larger portion of your monthly income remains uncommitted."
    ),
    "Employment type outside acceptable range": (
        "Establishing a longer period in your current role. For permanent "
        "employees, we typically look for at least 6 months; for self-employed "
        "applicants, at least 2 years of trading."
    ),
    "Loan-to-income ratio above acceptable range": (
        "Considering a reduced loan amount relative to your annual income, or applying after a salary increase."
    ),
    "Serviceability ratio outside acceptable range": (
        "Reducing existing financial commitments to improve the ratio of total repayments to income."
    ),
    "Expense-to-income ratio above acceptable range": (
        "Reviewing and reducing monthly expenses to improve the proportion of income available for loan repayments."
    ),
    "Net monthly surplus below acceptable range": (
        "Reducing monthly commitments or increasing income to ensure a "
        "larger surplus remains after all expenses and the proposed repayment."
    ),
    "Loan-to-value ratio above acceptable range": (
        "Increasing your deposit or considering a lower loan amount to reduce the loan-to-value ratio."
    ),
    "Deposit contribution below acceptable range": (
        "Saving a larger deposit over time. A higher deposit reduces the loan amount and strengthens your application."
    ),
    "Savings to loan ratio below acceptable range": (
        "Building your savings over time to demonstrate a pattern of regular "
        "saving. A higher deposit or savings balance strengthens your application."
    ),
    "Credit utilisation ratio above acceptable range": (
        "Reducing balances on existing credit cards and revolving credit "
        "facilities to lower your overall credit utilisation ratio."
    ),
    "Recent credit enquiry frequency above acceptable range": (
        "Limiting new credit applications for the next 6\u201312 months to "
        "reduce the number of enquiries on your credit file."
    ),
}


def generate_approval_template(
    applicant_name,
    loan_amount,
    purpose,
    pricing=None,
    conditions=None,
    employment_type=None,
    applicant_type=None,
    has_cosigner=False,
):
    """Generate an approval email matching the Claude-generated format exactly."""
    loan_type = _loan_type(purpose)
    first = _first_name(applicant_name)
    today = date.today()
    sign_by = (today + timedelta(days=30)).strftime("%d %B %Y")

    subject = f"Congratulations! Your {loan_type} Loan is Approved"

    # Pricing section
    pricing_block = ""
    if pricing:
        pricing_block = f"""
Loan Details:

  Loan Amount:             ${loan_amount:,.2f}
  Interest Rate:           {pricing.get("interest_rate", "To be confirmed")} ({pricing.get("rate_type", "Variable")})
  Comparison Rate:         {pricing.get("comparison_rate", "To be confirmed")}*
  Loan Term:               {pricing.get("loan_term_display", "As requested")}
  Estimated Monthly Payment: {pricing.get("monthly_payment", "To be confirmed")}
  Establishment Fee:       {pricing.get("establishment_fee", "To be confirmed")}
  First Repayment Date:    {pricing.get("first_repayment_date", "To be confirmed")}
"""
    else:
        pricing_block = f"""
Loan Details:

  Loan Amount:             ${loan_amount:,.2f}
  Interest Rate:           To be confirmed
  Loan Term:               As requested
"""

    conditions_block = ""

    # Co-signer note
    cosigner_note = ""
    if has_cosigner:
        cosigner_note = "\nYour co-signer will receive separate documentation for their records.\n"
    elif applicant_type and applicant_type.lower() == "couple":
        cosigner_note = "\nAs a joint application, both parties will need to sign the loan contract.\n"

    # Purpose-specific next steps
    if purpose.lower() == "home":
        next_steps = f"""Next Steps:

Please review the attached loan agreement, which outlines all terms and conditions:

  1. Sign and return your documents by {sign_by} \u2013 you can sign electronically via our secure portal, or return them by email or in person.
  2. Arrange settlement with your solicitor or conveyancer.
  3. Ensure your building and contents insurance is in place before settlement."""
    else:
        next_steps = f"""Next Steps:

Please review the attached loan agreement, which outlines all terms and conditions:

  1. Sign and return your documents by {sign_by} \u2013 you can sign electronically via our secure portal, or return them by email or in person.
  2. Confirm your nominated bank account (BSB and account number) for the funds to be deposited into.
  3. Once received, funds are typically in your account within 1\u20132 business days."""

    opening = (
        f"We are pleased to advise that your application for a "
        f"{loan_type} Loan with AussieLoanAI has been approved. Congratulations!"
    )
    if conditions:
        opening = (
            f"We are pleased to advise that your application for a "
            f"{loan_type} Loan with AussieLoanAI has been conditionally approved. "
            f"Congratulations!"
        )

    body = f"""Dear {first},

{opening}
{pricing_block}{conditions_block}{cosigner_note}
{next_steps}

Before You Sign:

We want to make sure this loan is right for you. Please take the time to read the full terms carefully, including fees and what happens if a repayment is missed.
If your circumstances have changed since you applied, please let us know. You are also welcome to seek independent financial or legal advice before proceeding.
You will have access to a cooling-off period after signing, allowing you to withdraw without penalty. Details are in your loan agreement.

We're Here For You:

If at any point during your loan you experience financial difficulty, please contact us early. Our Financial Hardship team is here to help and can be reached on 1300 000 001 or at aussieloanai@gmail.com.

If you have any questions about your loan or the next steps, please don't hesitate to contact me directly at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or simply reply to this email.
Congratulations again, {first}. Thanks for choosing us at AussieLoanAI.

Kind regards,
Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd
ABN 12 345 678 901 | Australian Credit Licence No. 012345
Phone: 1300 000 000
Email: aussieloanai@gmail.com

Attachments:
  1. Loan Contract \u2013 {applicant_name}.pdf
  2. Key Facts Sheet \u2013 {loan_type} Loan.pdf
  3. Credit Guide \u2013 AussieLoanAI Pty Ltd.pdf

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
*Comparison rate is calculated on a $30,000 unsecured loan over a 5-year term. WARNING: This comparison rate applies only to the example given. Different amounts and terms will result in different comparison rates. Costs such as redraw fees and early repayment costs, and cost savings such as fee waivers, are not included in the comparison rate but may influence the cost of the loan.

This approval is valid for 30 days and is subject to no material change in your financial circumstances. If you are dissatisfied with any aspect of our service, please contact us first. If unresolved, you may contact the Australian Financial Complaints Authority (AFCA) on 1800 931 678 or at www.afca.org.au.

This communication is confidential and intended solely for the named recipient.
"""

    return {"subject": subject, "body": body}


def generate_denial_template(
    applicant_name,
    loan_amount,
    purpose,
    denial_reasons="",
    feature_importances=None,
    credit_score=None,
    debt_to_income=None,
    employment_type=None,
):
    """Generate a denial email matching the Claude-generated format exactly."""
    loan_type = _loan_type(purpose)
    first = _first_name(applicant_name)
    ref = _ref_number(purpose, applicant_name)

    subject = f"Update on Your {loan_type} Loan Application | Ref #{ref}"

    # Build assessment factor bullets
    reason_list = []
    if denial_reasons:
        reason_list = [r.strip() for r in denial_reasons.split(";") if r.strip()]

    factor_bullets = []
    for reason in reason_list:
        explanation = _REASON_EXPLANATIONS.get(
            reason,
            reason.replace("_", " ").capitalize(),
        )
        factor_bullets.append(f"  \u2022  {explanation}")

    if not factor_bullets:
        factor_bullets = [
            "  \u2022  Credit assessment criteria: Your financial profile "
            "at the time of assessment did not meet the requirements for "
            "a loan of this type and size."
        ]

    factors_text = "\n".join(factor_bullets)

    # Build improvement step bullets
    step_bullets = []
    for reason in reason_list:
        step = _IMPROVEMENT_STEPS.get(reason)
        if step:
            step_bullets.append(f"  \u2022  {step}")

    if not step_bullets:
        step_bullets = [
            "  \u2022  Reviewing your financial position and considering "
            "a loan amount that aligns with your current income and commitments."
        ]

    steps_text = "\n".join(step_bullets)

    body = f"""Dear {first},

Thank you for giving us the opportunity to review your application for a ${loan_amount:,.2f} {loan_type} Loan with AussieLoanAI.

We have carefully reviewed your application and are unable to approve it at this time. Here is what we looked at and what you can do from here.

This decision was based on a thorough review of your financial profile, specifically:

{factors_text}

This assessment was conducted in line with our responsible lending obligations, which exist to ensure any credit we provide is suitable and manageable for our customers.

What You Can Do:

This decision is based on your circumstances at the time of your application \u2013 it does not prevent you from applying with us in the future. The following steps may strengthen a future application:

{steps_text}

You are entitled to obtain a free copy of your credit report within 90 days of this notice to verify the information used in our assessment. You can request one from any of Australia's credit reporting bodies:

  \u2022  Equifax \u2013 equifax.com.au
  \u2022  Illion \u2013 illion.com.au
  \u2022  Experian \u2013 experian.com.au

We'd Still Like to Help:

If you'd like to explore whether a different loan product or a revised amount could be a better fit, I'd be happy to talk through your options.

If you have any questions about this decision, please don't hesitate to contact me directly at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or simply reply to this email.
Thanks for coming to us, {first}. We'd love to help you find the right option when you're ready.

Kind regards,
Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd
ABN 12 345 678 901 | Australian Credit Licence No. 012345
Phone: 1300 000 000
Email: aussieloanai@gmail.com

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
If you are dissatisfied with this decision, we encourage you to contact us first so we can address your concerns through our internal complaints process. If you remain dissatisfied, you may lodge a complaint with the Australian Financial Complaints Authority (AFCA):
Phone: 1800 931 678
Website: www.afca.org.au
Email: info@afca.org.au

This communication is confidential and intended solely for the named recipient.
"""

    return {"subject": subject, "body": body}


def generate_conditional_template(applicant_name, loan_amount, purpose, conditions, pricing=None):
    """Convenience wrapper — conditional uses the approval template with conditions."""
    return generate_approval_template(
        applicant_name,
        loan_amount,
        purpose,
        pricing=pricing,
        conditions=conditions,
    )
