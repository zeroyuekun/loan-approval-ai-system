import json
import os

import anthropic
import httpx

from .recommendation_engine import RecommendationEngine


def _extract_tool_result(response, fallback):
    """Extract structured result from tool_use response, with fallback."""
    try:
        tool_block = next(b for b in response.content if b.type == 'tool_use')
        return tool_block.input
    except (StopIteration, AttributeError):
        text_block = next((b for b in response.content if b.type == 'text'), None)
        if text_block:
            try:
                json_start = text_block.text.find('{')
                json_end = text_block.text.rfind('}') + 1
                return json.loads(text_block.text[json_start:json_end])
            except (json.JSONDecodeError, ValueError):
                pass
        return fallback


class NextBestOfferGenerator:
    """Generates alternative offers for denied applicants based on their banking profile.

    Uses a deterministic RecommendationEngine for product eligibility, amounts, and
    rates. The LLM's role is limited to writing personalised reasoning text around
    pre-calculated numbers.
    """

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        self.engine = RecommendationEngine()

    def generate(self, application, denial_reasons=''):
        """Build alternative offers for a denied applicant.

        1. RecommendationEngine calculates eligible products with exact amounts/rates
        2. LLM writes personalised reasoning for each offer
        3. Returns combined result in the same dict shape the orchestrator expects
        """
        result = self.engine.recommend(application, denial_reasons)

        if not result['offers']:
            result['analysis'] = (
                'Based on your current financial profile, we recommend building your '
                'savings and credit history before reapplying. Our Goal Saver account '
                'can help you get started.'
            )
            result['personalized_message'] = (
                'We appreciate your interest in banking with us. While we were unable '
                'to approve your application at this time, we have options to help you '
                'work toward your financial goals.'
            )
            return result

        # Get LLM to write messaging around the pre-calculated offers
        messaging = self._generate_messaging(application, result['offers'], denial_reasons)

        # Merge LLM reasoning into each offer
        offer_reasonings = messaging.get('offer_reasoning', [])
        for i, offer in enumerate(result['offers']):
            if i < len(offer_reasonings):
                offer['reasoning'] = offer_reasonings[i]

        result['analysis'] = messaging.get('analysis', '')
        result['personalized_message'] = messaging.get('personalized_message', '')

        return result

    def _generate_messaging(self, application, offers, denial_reasons=''):
        """Ask the LLM to write personalised reasoning for pre-calculated offers.

        The LLM receives the exact product details and is instructed NOT to change
        any numbers — its job is ONLY to write human-readable reasoning text.
        """
        offers_detail = self._format_precalculated_offers(offers)
        profile_context = self._get_customer_context(application)

        prompt = f"""You are a marketing strategist at AussieLoanAI, an Australian bank. A customer's loan application was declined. Our product engine has already calculated which products this customer qualifies for, with exact amounts, rates, and repayments.

Your job is ONLY to write personalised reasoning text for each offer. DO NOT change any numbers, amounts, rates, or product details. DO NOT invent new offers. Use the pre-calculated details exactly as provided.

=== DECLINED APPLICATION ===
- Requested: ${float(application.loan_amount):,.2f} for {application.get_purpose_display()}
- Credit Score: {application.credit_score} (Equifax, 0-1200)
- Annual Income: ${float(application.annual_income):,.2f}
- Decline factors: {denial_reasons or 'Not specified'}

=== BANKING RELATIONSHIP ===
{profile_context}

=== PRE-CALCULATED OFFERS (do NOT change these numbers) ===
{offers_detail}

=== YOUR TASK ===
Write the following in JSON format:
{{
    "offer_reasoning": [
        "<reasoning for offer 1 — explain why this suits THIS customer, reference their actual numbers>",
        "<reasoning for offer 2>",
        "<reasoning for offer 3 if present>"
    ],
    "analysis": "<2-3 sentence retention strategy for this customer>",
    "personalized_message": "<warm 1-2 sentence message acknowledging their situation>"
}}

RULES:
- Reference the customer's ACTUAL numbers (income, savings, credit score)
- Australian English spelling (finalised, recognised, personalised)
- Australian financial terms (term deposit, everyday account, fortnight, p.a.)
- Each reasoning should be 2-3 sentences, specific to this customer
- DO NOT repeat the product details — focus on WHY it suits them
- Keep the personalised_message genuine and brief"""

        try:
            from django.conf import settings as django_settings

            NBO_MESSAGING_TOOL = {
                'name': 'record_offer_messaging',
                'description': 'Record the personalised messaging for pre-calculated offers.',
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'offer_reasoning': {
                            'type': 'array',
                            'items': {'type': 'string'},
                        },
                        'analysis': {'type': 'string'},
                        'personalized_message': {'type': 'string'},
                    },
                    'required': ['offer_reasoning', 'analysis', 'personalized_message'],
                },
            }

            response = self.client.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=1024,
                temperature=getattr(django_settings, 'AI_TEMPERATURE_ANALYSIS', 0.0),
                messages=[{'role': 'user', 'content': prompt}],
                tools=[NBO_MESSAGING_TOOL],
                tool_choice={'type': 'tool', 'name': 'record_offer_messaging'},
            )

            result = _extract_tool_result(response, None)
            if result is None:
                raise ValueError('No tool result extracted')
            return result
        except Exception:
            # Fallback: generate basic reasoning from the benefit text
            return {
                'offer_reasoning': [o.get('benefit', '') for o in offers],
                'analysis': 'We have identified alternative products based on your financial profile.',
                'personalized_message': (
                    'Thank you for your interest in banking with us. '
                    'We have some tailored options that may suit your needs.'
                ),
            }

    def _format_precalculated_offers(self, offers):
        """Format pre-calculated offers for the messaging prompt."""
        lines = []
        for i, o in enumerate(offers, 1):
            parts = [f"Offer {i}: {o.get('name', o.get('type', 'Product'))}"]
            if o.get('amount'):
                parts.append(f"  Amount: ${o['amount']:,.2f}")
            if o.get('term_months'):
                parts.append(f"  Term: {o['term_months']} months")
            if o.get('estimated_rate'):
                parts.append(f"  Rate: {o['estimated_rate']:.2f}% p.a.")
            if o.get('monthly_repayment'):
                parts.append(f"  Monthly repayment: ${o['monthly_repayment']:,.2f}")
            if o.get('fortnightly_repayment'):
                parts.append(f"  Fortnightly repayment: ${o['fortnightly_repayment']:,.2f}")
            if o.get('benefit'):
                parts.append(f"  Benefit: {o['benefit']}")
            lines.append('\n'.join(parts))
        return '\n\n'.join(lines)

    def generate_marketing_message(self, application, offers, denial_reasons=''):
        """Generate a customer-facing marketing message based on NBO offers for denial emails."""
        import time
        start = time.time()

        profile_context = self._get_customer_context(application)

        def _fmt_amount(amt):
            return f"${amt:,.2f}" if amt else "N/A"

        offers_summary = '\n'.join(
            f"- {o.get('name', o.get('type', 'Product'))}: "
            f"{_fmt_amount(o.get('amount'))}, "
            f"{o.get('benefit', '')}"
            for o in offers
        )

        prompt = f"""You are a marketing communications specialist at AussieLoanAI, an Australian bank. A customer's loan application was declined, and we've identified alternative products for them. Write a warm, professional marketing message that could be sent as a follow-up to their decline notification.

=== CUSTOMER CONTEXT ===
- Requested: ${float(application.loan_amount):,.2f} for {application.get_purpose_display()}
- Credit Score: {application.credit_score} (Equifax, 0-1200)
- Annual Income: ${float(application.annual_income):,.2f}
- Employment: {application.get_employment_type_display()} ({application.employment_length} years)
- Decline factors: {denial_reasons or 'Not specified'}

=== BANKING RELATIONSHIP ===
{profile_context}

=== ALTERNATIVE OFFERS AVAILABLE ===
{offers_summary}

=== WRITING GUIDELINES ===
- 3-4 short paragraphs, plain text (no markdown, no bullet points in the message body)
- Australian English spelling (finalised, recognised, colour)
- Australian financial terms (term deposit, everyday account, fortnight)
- Warm but professional tone — Big 4 Australian bank style
- Do NOT repeat the decline decision — assume the customer already knows
- Open with acknowledgement, then naturally introduce the alternatives
- Reference specific offer details (amounts, rates) where relevant
- Close with a clear next step (call, visit branch, reply to email)
- Do NOT use AI giveaway phrases ("I understand", "navigate", "journey", "leverage")
- Sign off as "The AussieLoanAI Team"

Respond with the marketing message text only, no JSON wrapping."""

        from django.conf import settings as django_settings
        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1024,
            temperature=getattr(django_settings, 'AI_TEMPERATURE_MARKETING', 0.2),
            messages=[{'role': 'user', 'content': prompt}],
        )

        generation_time_ms = int((time.time() - start) * 1000)

        return {
            'marketing_message': response.content[0].text.strip(),
            'generation_time_ms': generation_time_ms,
        }

    def _get_customer_context(self, application):
        """Pull banking profile into a string for the prompt."""
        try:
            profile = application.applicant.profile
            return (
                f"- Savings Balance: ${float(profile.savings_balance):,.2f}\n"
                f"- Everyday Account Balance: ${float(profile.checking_balance):,.2f}\n"
                f"- Total Deposits: ${float(profile.total_deposits):,.2f}\n"
                f"- Account Tenure: {profile.account_tenure_years} years\n"
                f"- Loyalty Tier: {profile.get_loyalty_tier_display()}\n"
                f"- Has Credit Card: {'Yes' if profile.has_credit_card else 'No'}\n"
                f"- Has Existing Mortgage: {'Yes' if profile.has_mortgage else 'No'}\n"
                f"- Has Auto Loan: {'Yes' if profile.has_auto_loan else 'No'}\n"
                f"- Total Banking Products: {profile.num_products}\n"
                f"- On-Time Payment Rate: {profile.on_time_payment_pct:.1f}%\n"
                f"- Previous Loans Repaid: {profile.previous_loans_repaid}\n"
                f"- Loyal Customer: {'Yes' if profile.is_loyal_customer else 'No'}"
            )
        except Exception:
            return (
                "- No banking relationship data available\n"
                "- This appears to be a new customer"
            )
