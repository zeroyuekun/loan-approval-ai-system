"""Static template emails for when Claude API is unavailable.

These templates include all required compliance elements (AFCA, cooling-off,
hardship provisions) and are marked with template_fallback=True for human review.
"""


def generate_approval_template(applicant_name, loan_amount, purpose, pricing=None):
    """Generate a static approval email from template."""
    subject = f'Your {purpose} Loan Application Has Been Approved'

    pricing_section = ''
    if pricing:
        pricing_section = f"""
Loan Details:
- Interest Rate: {pricing.get('interest_rate', 'To be confirmed')} ({pricing.get('rate_type', 'Variable')})
- Comparison Rate: {pricing.get('comparison_rate', 'To be confirmed')}*
- Loan Term: {pricing.get('loan_term_display', 'As requested')}
- Estimated Monthly Payment: {pricing.get('monthly_payment', 'To be confirmed')}
- Establishment Fee: {pricing.get('establishment_fee', 'To be confirmed')}
"""

    body = f"""Dear {applicant_name},

We are pleased to advise that your application for a {purpose} loan of ${loan_amount:,.2f} has been approved.
{pricing_section}
Important Information:

1. Cooling-Off Period: You have 14 days from the date of this letter to withdraw from the loan contract without penalty, as provided under the National Consumer Credit Protection Act 2009 (NCCP Act).

2. Your loan contract and key fact sheet will be posted separately. Please review all documents carefully before signing.

3. If you experience financial difficulty at any time, please contact our hardship team on 1300 000 000. We are committed to working with you under the Banking Code of Practice 2025.

4. If you are not satisfied with any aspect of our service, you may lodge a complaint with the Australian Financial Complaints Authority (AFCA) at www.afca.org.au or by calling 1800 931 678.

*Comparison rate is calculated on a loan of $150,000 over 25 years. WARNING: This comparison rate is true only for the example given and may not include all fees and charges. Different terms, fees, or other loan amounts might result in a different comparison rate.

Kind regards,
AussieLoanAI Lending Team
Australian Credit Licence No. 000000
"""

    return {'subject': subject, 'body': body}


def generate_denial_template(applicant_name, loan_amount, purpose, denial_reasons=''):
    """Generate a static denial email from template."""
    subject = f'Update on Your {purpose} Loan Application'

    reasons_section = ''
    if denial_reasons:
        reasons_section = f"""
The primary factors in our assessment were:
- {denial_reasons.replace("; ", chr(10) + "- ")}
"""

    body = f"""Dear {applicant_name},

Thank you for your application for a {purpose} loan of ${loan_amount:,.2f}.

After careful assessment against our lending criteria under the National Consumer Credit Protection Act 2009, we are unable to approve your application at this time.
{reasons_section}
What You Can Do:

1. Request a copy of your credit report from Equifax (www.equifax.com.au) or illion (www.illion.com.au) to review the information held about you.

2. Contact our team on 1300 000 000 to discuss your application in detail. Our lending officers can explain the assessment and suggest potential next steps.

3. If you believe this decision is incorrect, you may request a review by writing to our Internal Dispute Resolution team.

4. You may also lodge a complaint with the Australian Financial Complaints Authority (AFCA) at www.afca.org.au or by calling 1800 931 678.

If your circumstances change in the future, we welcome you to apply again.

Kind regards,
AussieLoanAI Lending Team
Australian Credit Licence No. 000000
"""

    return {'subject': subject, 'body': body}
