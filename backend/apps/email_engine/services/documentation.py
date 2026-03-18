"""Builds the required-documentation checklist for approved loan emails.

Based on standard Australian Big 4 bank requirements (CBA, ANZ, Westpac, NAB)
as of 2025/2026. The checklist is tailored to the applicant's loan purpose,
employment type, applicant type, and circumstances.
"""


def build_documentation_checklist(application) -> str:
    """Return a formatted text block listing required documents.

    This is injected into the approval email prompt so Claude includes
    the correct list in the email body.
    """
    purpose = application.purpose
    emp_type = application.employment_type
    applicant_type = application.applicant_type
    has_cosigner = application.has_cosigner
    has_hecs = getattr(application, 'has_hecs', False)

    docs = []

    # ------------------------------------------------------------------
    # Identity & address (all loans)
    # ------------------------------------------------------------------
    docs.append('Current photo identification (Australian driver licence or passport)')
    docs.append('Proof of current residential address (utility bill, council rates notice, or bank statement dated within the last 3 months)')

    # ------------------------------------------------------------------
    # Income verification (varies by employment type)
    # ------------------------------------------------------------------
    if emp_type == 'payg_permanent':
        docs.append('Two most recent payslips (no older than 45 days)')
        docs.append('Most recent PAYG payment summary or ATO Notice of Assessment')
    elif emp_type == 'payg_casual':
        docs.append('Three months of consecutive payslips')
        docs.append('Tax returns for the last 2 financial years')
        docs.append('ATO Notice of Assessment for the last 2 years')
    elif emp_type == 'self_employed':
        docs.append('Last 2 years of personal and business tax returns')
        docs.append('ATO Notice of Assessment for the last 2 years')
        docs.append('Business Activity Statements (BAS) for the last 4 quarters')
        docs.append('Profit and loss statement and balance sheet prepared by your accountant')
        docs.append('ABN registration confirmation')
    elif emp_type == 'contract':
        docs.append('Current employment contract showing term, rate, and employer')
        docs.append('Two most recent payslips')
        docs.append('Tax returns for the last 2 financial years')

    # ------------------------------------------------------------------
    # Bank statements (all loans)
    # ------------------------------------------------------------------
    docs.append('Bank statements for all transaction and savings accounts (last 3 months)')

    # ------------------------------------------------------------------
    # Existing debts
    # ------------------------------------------------------------------
    docs.append('Recent statements for any existing loans, credit cards, or buy-now-pay-later accounts')

    # ------------------------------------------------------------------
    # Home loan specific
    # ------------------------------------------------------------------
    if purpose == 'home':
        docs.append('Signed contract of sale (or evidence of the property being purchased)')
        docs.append('Most recent council rates notice for the property')
        docs.append('Building and pest inspection reports (if available)')
        docs.append('Home and contents insurance quote or certificate of currency')
        docs.append('Details of your solicitor or conveyancer (name, firm, contact number)')
        docs.append('Evidence of genuine savings (savings account statements showing at least 3 months of regular deposits)')

    # ------------------------------------------------------------------
    # Auto loan specific
    # ------------------------------------------------------------------
    if purpose == 'auto':
        docs.append('Purchase agreement or dealer quote for the vehicle')
        docs.append('Vehicle registration details (if purchasing privately)')
        docs.append('Comprehensive motor vehicle insurance quote')

    # ------------------------------------------------------------------
    # Business loan specific
    # ------------------------------------------------------------------
    if purpose == 'business':
        docs.append('Business plan or purpose statement for the loan funds')
        docs.append('ABN/ACN registration confirmation')
        docs.append('Last 2 years of business financial statements')

    # ------------------------------------------------------------------
    # Education loan specific
    # ------------------------------------------------------------------
    if purpose == 'education':
        docs.append('Letter of offer or enrolment confirmation from the education provider')
        docs.append('Fee schedule or invoice from the institution')

    # ------------------------------------------------------------------
    # HECS/HELP debt
    # ------------------------------------------------------------------
    if has_hecs:
        docs.append('MyGov HECS/HELP balance statement (accessible via your myGov account linked to the ATO)')

    # ------------------------------------------------------------------
    # Co-signer / guarantor
    # ------------------------------------------------------------------
    if has_cosigner:
        docs.append("Co-signer's current photo identification (driver licence or passport)")
        docs.append("Co-signer's proof of income (payslips or tax returns as applicable)")
        docs.append("Co-signer's bank statements (last 3 months)")
        docs.append("Co-signer's signed consent to act as guarantor")

    # ------------------------------------------------------------------
    # Couple / joint application
    # ------------------------------------------------------------------
    if applicant_type == 'couple':
        docs.append('All of the above documents are required for both applicants')

    # Format as a prompt-injection-safe text block for the email prompt
    lines = [
        'The following documents are required based on this applicant\'s circumstances. '
        'Include ALL of these in the email as a numbered list:'
    ]
    for i, doc in enumerate(docs, 1):
        lines.append(f'  {i}. {doc}')

    return '\n'.join(lines)
