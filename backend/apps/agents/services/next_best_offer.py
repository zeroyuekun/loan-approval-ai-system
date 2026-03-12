import json
import os

import anthropic


class NextBestOfferGenerator:
    """Generates alternative loan offers for denied applications using Claude."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

    def generate(self, application, denial_reasons=''):
        """
        Generate 2-3 alternative offers for a denied applicant.

        Args:
            application: LoanApplication instance
            denial_reasons: string describing why the original application was denied

        Returns:
            dict with offers list and analysis
        """
        prompt = f"""You are a financial advisor. A loan application was denied. Based on the applicant's profile,
suggest 2-3 realistic alternative loan offers they might qualify for.

Applicant Profile:
- Annual Income: ${float(application.annual_income):,.2f}
- Credit Score: {application.credit_score}
- Requested Loan Amount: ${float(application.loan_amount):,.2f}
- Requested Purpose: {application.get_purpose_display()}
- Loan Term: {application.loan_term_months} months
- Debt-to-Income Ratio: {float(application.debt_to_income):.2%}
- Employment Length: {application.employment_length} years
- Home Ownership: {application.home_ownership}
- Has Cosigner: {'Yes' if application.has_cosigner else 'No'}

Denial Reasons: {denial_reasons}

For each alternative offer, provide realistic and conservative suggestions.
Respond in JSON format only:
{{
    "offers": [
        {{
            "type": "<loan type>",
            "amount": <dollar amount>,
            "term_months": <number>,
            "estimated_rate": <percentage as decimal, e.g. 5.5>,
            "reasoning": "<why this might work for the applicant>"
        }}
    ],
    "analysis": "<overall analysis of the applicant's situation and recommendations>"
}}"""

        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1024,
            messages=[{'role': 'user', 'content': prompt}],
        )

        response_text = response.content[0].text

        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            result = json.loads(response_text[json_start:json_end])
        except (json.JSONDecodeError, ValueError):
            result = {
                'offers': [],
                'analysis': 'Unable to generate alternative offers at this time.',
            }

        return {
            'offers': result.get('offers', []),
            'analysis': result.get('analysis', ''),
        }
