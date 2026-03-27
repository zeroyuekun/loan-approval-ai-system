import json
import os
import re
import time
from datetime import date

import anthropic
import httpx

from apps.agents.services.api_budget import BudgetExhausted, guarded_api_call
from apps.email_engine.services.guardrails import GuardrailChecker


_INJECTION_BLOCKLIST = re.compile(
    r'(?:ignore\s+(?:previous|above|all)\s+instructions'
    r'|disregard\s+(?:previous|above|all)\s+instructions'
    r'|system\s+prompt'
    r'|you\s+are\s+now'
    r'|new\s+instructions'
    r'|forget\s+(?:previous|your|all)\s+instructions'
    r'|override\s+(?:previous|your|all)\s+instructions)',
    re.IGNORECASE,
)


def _sanitize_prompt_input(value, max_length=500):
    """Strip characters and patterns that could manipulate prompt structure."""
    if not isinstance(value, str):
        return value
    value = re.sub(r'[<>\[\]{}]', '', value)
    value = re.sub(r'\s+', ' ', value)
    value = _INJECTION_BLOCKLIST.sub('', value)
    return value[:max_length].strip()


MARKETING_EMAIL_PROMPT = """You are filling in a templated follow-up email for AussieLoanAI. This email is sent AFTER the customer has already received their decline notification. It does NOT repeat the decline.

YOUR JOB: Fill in ONLY the bracketed placeholders below. Do NOT rewrite, rephrase, or rearrange the template. Every word outside a bracket must appear EXACTLY as written. If a section is wrapped in {{IF ...}} / {{END IF}}, include it only when the condition is true; otherwise omit that entire block (including its label).

=== COMPLIANCE RULES ===
1. Do NOT repeat the decline decision or use "declined", "denied", "rejected", "unsuccessful".
2. Use ONLY the figures from the OFFER DATA below. Do NOT invent numbers.
3. "Guaranteed returns" is permitted ONLY for term deposits (Financial Claims Scheme).
4. For credit products, NEVER say "guaranteed" anything.
5. Australian English spelling throughout.
6. Never reference protected characteristics.

=== CUSTOMER DATA ===
- Full Name: {applicant_name}
- First Name: {applicant_first_name}
- Requested: ${loan_amount:,.2f} for {purpose}
- Credit Score: {credit_score}
- Annual Income: ${annual_income:,.2f}
- Employment: {employment_type} ({employment_length} years)

=== BANKING RELATIONSHIP ===
{banking_context}

=== OFFER DATA (from product engine \u2013 use these exact figures) ===
{offers_detail}

=== RETENTION INTELLIGENCE ===
- Retention Score: {retention_score}/100
- Loyalty Factors: {loyalty_factors}
- Strategy: {nbo_analysis}

=== EMAIL TEMPLATE (output this exactly, filling only the [...] placeholders) ===

Subject: Next steps for your AussieLoanAI loan application

Dear {applicant_first_name},

Following your recent loan application with us, we've looked at your profile and there are a few options worth considering.

[FOR EACH OFFER in the OFFER DATA above, output one block in this exact format. Output up to 3 offers.]

Option [N]: [Offer Name]

\u2022  [Benefit headline 1]: [One sentence explaining the benefit, 10\u201320 words.]
\u2022  [Benefit headline 2]: [One sentence explaining the benefit, 10\u201320 words.]
\u2022  [Benefit headline 3 \u2013 only if the offer data provides a third distinct benefit]: [One sentence, 10\u201320 words.]

[One sentence connecting this offer to the customer's actual numbers from the data above. Use a specific figure \u2013 e.g. their savings balance, income, or payment history. Keep to 15\u201325 words.]

[END FOR EACH]

If any of these options interest you, I'd be happy to talk them through with you. You can contact me directly at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or simply reply to this email.

Thanks for coming to us, {applicant_first_name}. We'd love to help you find the right option when you're ready.

Kind regards,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd
ABN 12 345 678 901 | Australian Credit Licence No. 012345
Ph: 1300 000 000
Email: aussieloanai@gmail.com

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
{{IF any offer is a term deposit}}
*Deposits up to $250,000 per account holder per authorised deposit-taking institution are protected under the Australian Government's Financial Claims Scheme.
{{END IF}}

{{IF any offer references a bonus interest rate}}
**The [X.XX]% p.a. bonus rate applies when you deposit a minimum of $[XXX] per month and make no withdrawals. If conditions are not met in a given month, the base rate of [X.XX]% p.a. will apply. Rate is variable and subject to change.
{{END IF}}

Interest rates are current as at [DD/MM/YYYY \u2013 use today's date] and are subject to change without notice. This email contains general information only and does not take into account your personal financial situation, objectives, or needs. Before making a decision, please consider whether the product is appropriate for you. Full terms and conditions, including the Target Market Determination and Product Disclosure Statement, are available at www.aussieloanai.com.au.

You are receiving this email because you are an existing AussieLoanAI customer. If you no longer wish to receive marketing communications from us, you can unsubscribe here or manage your communication preferences in your account settings. AussieLoanAI Pty Ltd, Sydney NSW 2000.

=== RULES FOR FILLING PLACEHOLDERS ===
1. Benefit headlines are 2\u20135 words (e.g. "Lower interest rates", "Guaranteed returns*", "No lock-in period").
2. Benefit sentences are factual, 10\u201320 words, no performative language.
3. The customer-fit sentence must cite a SPECIFIC number from their data.
4. Do NOT add sections, paragraphs, or sentences beyond what the template specifies.
5. Do NOT rephrase the opening line, closing lines, sign-off, or footer. Copy them verbatim.
6. For term deposit benefits you may use "Guaranteed returns*" and "Government protected*".
7. No filler words: "additionally", "furthermore", "moreover", "in addition", "we value you".
8. BANNED words/phrases: "leverage", "risk-free", "empower", "navigate", "journey", "rest assured", "comprehensive", "holistic". Use plain alternatives (e.g. "use" not "leverage", "no-risk" or "guaranteed" not "risk-free").
12. NEVER use em dashes (\u2014). Use en dashes (\u2013) or commas instead.
11. The customer-fit sentence must state a FACT from their data, not judge the customer's character. NEVER write "you've proven", "you've demonstrated", "you've shown", "your track record proves", or any phrasing that grades the customer's behaviour. Instead, cite the number directly: "With $12,000 in savings, this account could start earning from day one." The customer is not being evaluated \u2013 they are being offered a product.
9. Use contractions naturally: "you're", "we've", "it's". No slang.
10. Remove any {{IF ...}} / {{END IF}} markers from the output \u2013 they are instructions, not content.
"""


class MarketingAgent:
    """Generates follow-up marketing emails for denied applicants with alternative product offers."""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if api_key:
            self.client = anthropic.Anthropic(
                api_key=api_key,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        else:
            self.client = None
        self.guardrail_checker = GuardrailChecker()

    def generate(self, application, nbo_result, denial_reasons=''):
        """Generate a marketing follow-up email based on NBO offers."""
        start_time = time.time()

        applicant_name = _sanitize_prompt_input(
            f"{application.applicant.first_name} {application.applicant.last_name}".strip(),
            max_length=200,
        )
        if not applicant_name:
            applicant_name = _sanitize_prompt_input(application.applicant.username, max_length=200)

        applicant_first_name = _sanitize_prompt_input(
            application.applicant.first_name or application.applicant.username,
            max_length=200,
        )

        banking_context = self._get_banking_context(application)
        offers_detail = self._format_offers(nbo_result.get('offers', []))

        prompt = MARKETING_EMAIL_PROMPT.format(
            applicant_name=applicant_name,
            applicant_first_name=applicant_first_name,
            loan_amount=float(application.loan_amount),
            purpose=application.get_purpose_display(),
            credit_score=application.credit_score,
            annual_income=float(application.annual_income),
            employment_type=application.get_employment_type_display(),
            employment_length=application.employment_length,
            denial_reasons=denial_reasons or 'Not specified',
            banking_context=banking_context,
            offers_detail=offers_detail,
            retention_score=nbo_result.get('customer_retention_score', 0),
            loyalty_factors=', '.join(nbo_result.get('loyalty_factors', [])) or 'N/A',
            nbo_analysis=nbo_result.get('analysis', 'N/A'),
        )

        # Extract NBO offer amounts for guardrail validation
        nbo_amounts = []
        for offer in nbo_result.get('offers', []):
            if offer.get('amount'):
                nbo_amounts.append(float(offer['amount']))
            if offer.get('monthly_repayment'):
                nbo_amounts.append(float(offer['monthly_repayment']))
            if offer.get('fortnightly_repayment'):
                nbo_amounts.append(float(offer['fortnightly_repayment']))

        return self._generate_with_retries(application, prompt, start_time, nbo_amounts=nbo_amounts, nbo_result=nbo_result)

    def _generate_with_retries(self, application, prompt, start_time, attempt=1, nbo_amounts=None, nbo_result=None):
        """Generate the email with guardrail retry logic."""
        from django.conf import settings as django_settings
        current_prompt = prompt
        if attempt > 1:
            feedback = getattr(self, '_last_feedback', '')
            current_prompt += f"\n\nIMPORTANT: Previous attempt failed compliance checks: {feedback}. Fix these issues."
            current_prompt += f"\n\n(This is generation attempt {attempt} of {self.MAX_RETRIES}.)"

        import logging as _logging
        _logger = _logging.getLogger('agents.marketing_agent')

        response = None
        for api_attempt in range(3):
            try:
                response = guarded_api_call(self.client,
                    model='claude-sonnet-4-20250514',
                    max_tokens=1500,
                    temperature=getattr(django_settings, 'AI_TEMPERATURE_MARKETING', 0.2),
                    messages=[{'role': 'user', 'content': current_prompt}],
                )
                break
            except BudgetExhausted:
                _logger.info('Marketing email API budget exhausted or no API key — using template')
                return self._marketing_template_fallback(application, nbo_amounts, start_time, nbo_result=nbo_result)
            except anthropic.AuthenticationError as api_err:
                _logger.error('Marketing email API auth error (not retryable): %s', api_err)
                return self._marketing_template_fallback(application, nbo_amounts, start_time, nbo_result=nbo_result)
            except anthropic.RateLimitError as api_err:
                _logger.warning('Marketing email API attempt %d rate limited: %s', api_attempt + 1, api_err)
                if api_attempt < 2:
                    time.sleep(2 ** (api_attempt + 1))
                else:
                    raise
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as api_err:
                _logger.warning('Marketing email API attempt %d failed: %s', api_attempt + 1, api_err)
                if api_attempt < 2:
                    time.sleep(2 ** api_attempt)
                else:
                    raise
            except anthropic.APIStatusError as api_err:
                if api_err.status_code >= 500:
                    _logger.warning('Marketing email API attempt %d server error (%d): %s', api_attempt + 1, api_err.status_code, api_err)
                    if api_attempt < 2:
                        time.sleep(2 ** api_attempt)
                    else:
                        raise
                elif 'credit' in str(api_err).lower() or 'balance' in str(api_err).lower():
                    _logger.warning('Marketing email API credit insufficient — using template')
                    return self._marketing_template_fallback(application, nbo_amounts, start_time, nbo_result=nbo_result)
                else:
                    _logger.error('Marketing email API client error (%d, not retryable): %s', api_err.status_code, api_err)
                    raise
            except Exception as api_err:
                _logger.critical('Marketing email API UNEXPECTED failure attempt %d: %s', api_attempt + 1, api_err, exc_info=True)
                raise

        response_text = response.content[0].text
        generation_time_ms = int((time.time() - start_time) * 1000)

        subject, body = self._parse_response(response_text)

        # Run unified guardrails with email_type='marketing'
        # Include customer profile amounts so guardrails don't flag them
        # as hallucinated (income, savings are real data cited in the email).
        context = {
            'decision': 'denied',
            'loan_amount': float(application.loan_amount) if application.loan_amount else None,
            'nbo_amounts': nbo_amounts or [],
            'annual_income': float(application.annual_income) if application.annual_income else None,
        }
        try:
            profile = application.applicant.profile
            context['savings_balance'] = float(profile.savings_balance) if profile.savings_balance else None
            context['checking_balance'] = float(profile.checking_balance) if profile.checking_balance else None
        except AttributeError:
            pass
        guardrail_results = self.guardrail_checker.run_all_checks(body, context, email_type='marketing')
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r['passed']]
            self._last_feedback = "; ".join(f"{r['check_name']}: {r['details']}" for r in failed_checks)
            return self._generate_with_retries(application, prompt, start_time, attempt + 1, nbo_amounts=nbo_amounts, nbo_result=nbo_result)

        return {
            'subject': subject,
            'body': body,
            'prompt_used': current_prompt,
            'guardrail_results': guardrail_results,
            'passed_guardrails': all_passed,
            'generation_time_ms': generation_time_ms,
            'attempt_number': attempt,
        }

    def _check_no_decline_language(self, text):
        """Marketing emails must not restate the decline decision.

        The email may acknowledge the customer's recent application, but must NOT
        repeat words like 'declined', 'denied', 'rejected', 'unsuccessful', or
        restate the decision itself ('unable to approve'). The customer already
        received the decline letter.
        """
        text_lower = text.lower()
        decline_phrases = [
            r'\b(declined|denied|rejected|unsuccessful|turned down)\b',
            r'\b(did not meet|does not meet|failed to meet)\b',
            r'\b(unable to approve|cannot approve|could not approve)\b',
            r'\bapplication was not\b',
            r'\bwe regret\b',
        ]
        found = []
        for pattern in decline_phrases:
            matches = re.findall(pattern, text_lower)
            if matches:
                found.extend(matches)

        passed = len(found) == 0
        details = f"Found decline references: {', '.join(str(f) for f in found)}" if not passed else "No decline language detected"
        return {
            'check_name': 'No Decline Language',
            'passed': passed,
            'details': details,
        }

    def _check_patronising_language(self, text):
        """Marketing emails must not patronise declined customers."""
        text_lower = text.lower()
        patronising_patterns = [
            r'\bwe know this is hard\b',
            r'\bwe know you[\u2019\']re disappointed\b',
            r'\bdon[\u2019\']t worry\b',
            r'\bit[\u2019\']s okay\b',
            r'\bcheer up\b',
            r'\bkeep your chin up\b',
            r'\bthis isn[\u2019\']t the end\b',
            r'\bwe understand how you feel\b',
            r'\bwe can imagine how\b',
            r'\bunfortunately for you\b',
            r'\byou[\u2019\']ve proven\b',
            r'\byou[\u2019\']ve demonstrated\b',
            r'\byou[\u2019\']ve shown\b',
            r'\byour track record proves\b',
            r'\byou can reliably\b',
        ]
        found = []
        for pattern in patronising_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                found.extend(matches)

        passed = len(found) == 0
        details = f"Patronising language found: {', '.join(found)}" if not passed else "No patronising language detected"
        return {
            'check_name': 'Patronising Language',
            'passed': passed,
            'details': details,
        }

    def _check_no_false_urgency(self, text):
        """Marketing emails must not create false urgency to pressure vulnerable customers."""
        text_lower = text.lower()
        urgency_patterns = [
            r'\blimited time\b',
            r'\bact now\b',
            r'\boffer expires\b',
            r'\bdon[\u2019\']t miss out\b',
            r'\brates are rising\b',
            r'\block in now\b',
            r'\bonly available to\b',
            r'\bhurry\b',
            r'\blast chance\b',
            r'\bbefore it[\u2019\']s too late\b',
        ]
        found = []
        for pattern in urgency_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                found.extend(matches)

        passed = len(found) == 0
        details = f"False urgency language found: {', '.join(found)}" if not passed else "No false urgency detected"
        return {
            'check_name': 'False Urgency',
            'passed': passed,
            'details': details,
        }

    def _check_no_guaranteed_approval(self, text):
        """Marketing emails must not imply guaranteed approval for alternative products (ASIC RG 234).

        Exception: "guaranteed returns" is allowed for term deposits (government-backed
        under the Financial Claims Scheme). This is factually correct, not misleading.
        """
        text_lower = text.lower()
        guarantee_patterns = [
            r'\bguaranteed\s+(?:approval|to\s+be\s+approved)\b',
            r'\b100%\s+(?:approval|chance|certain)\b',
            r'\byou\s+will\s+(?:definitely|certainly)\s+(?:be\s+approved|qualify)\b',
            r'\bpre[- ]?approved\b',
            r'\binstant\s+approval\b',
            r'\bautomatic(?:ally)?\s+approv(?:ed|al)\b',
            r'\bno\s+(?:credit\s+)?check(?:s)?\s+(?:required|needed)\b',
            r'\bno\s+questions\s+asked\b',
            # Note: "guaranteed returns" is NOT in this list — it's legitimate for
            # term deposits backed by the Australian Government Financial Claims Scheme.
        ]
        found = []
        for pattern in guarantee_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                found.extend(matches)

        passed = len(found) == 0
        details = (
            f"Guaranteed approval language found: {', '.join(found)}"
            if not passed
            else "No guaranteed approval language detected"
        )
        return {
            'check_name': 'No Guaranteed Approval',
            'passed': passed,
            'details': details,
        }

    # Marketing-specific AI-giveaway terms — excludes phrases legitimate in the
    # new customer-service-friendly marketing format:
    # - "comprehensive"/"tailored" OK in product descriptions
    # - "don't hesitate" OK in contact sections
    # - "we value you/your" OK in customer acknowledgement
    # - "we appreciate your" OK in closing
    # - "wanted to reach out" OK in marketing follow-up context
    MARKETING_AI_GIVEAWAY_TERMS = [
        r'\bpleased to (?:confirm|inform|advise)\b',
        r'\bdelighted\b',
        r'\bthrilled\b',
        r'\bgreat news\b',
        r'\bexciting\b',
        r'\bwe are happy to\b',
        r'\bnavigate\b',
        r'\bjourney\b',
        r'\bleverage\b',
        r'\bempower\b',
        r'\brest assured\b',
        r'\bevery step of the way\b',
        r'\bwe understand how important\b',
        r'\bwe understand this (?:may be|is) disappointing\b',
        r'\bnot the outcome you were hoping for\b',
        r'\bnot what you (?:were hoping|wanted|expected)\b',
        r'\bwe value you as a customer\b',
        r'\bwe (?:truly|genuinely) (?:want|care|value)\b',
        r'\bwe are pleased to inform you\b',
        r'\bwe want to be transparent about\b',
        r'\bregardless of (?:this|the) outcome\b',
        r'\bshould you have any questions at all\b',
        # Transitional adverbs (strongest AI-tell)
        r'\badditionally\b',
        r'\bfurthermore\b',
        r'\bmoreover\b',
        r'\bin addition\b',
        r'\bconsequently\b',
        r'\bas such\b',
        r'\baccordingly\b',
        # Hedging qualifiers
        r'\bmay potentially\b',
        r'\bcould potentially\b',
        r'\bit is possible that\b',
        r'\bmight be able to\b',
        # Performative empathy (excessive forms only)
        r'\bwe understand that\b',
        r'\bwe recognise that\b',
        # Over-formal constructions
        r'\bwe would like to\b',
        r'\bwe would like you to\b',
        r'\bshould you wish to\b',
        r'\bshould you require\b',
        r'\bshould you have any\b',
        r'\bwe wish you\b',
        # AI closing/filler patterns
        r'\bplease feel free to\b',
        r'\bwe are committed to\b',
        r'\bwe remain committed to\b',
        r'\bwe are available\b',
        r'\bthank you for choosing\b',
        r'\bthank you for trusting\b',
        r'\bin order to\b',
        r'\bat this point in time\b',
        r'\bit is important to note that\b',
        r'\bit is worth noting that\b',
        r'\bmoving forward\b',
        r'\bgoing forward\b',
    ]

    def _check_marketing_ai_giveaway_language(self, text):
        """Detect AI-generated phrasing, with marketing-appropriate exceptions.

        Unlike the general check, this allows "comprehensive" and "tailored" which
        are legitimate in product descriptions (e.g. "comprehensive insurance package").
        """
        text_lower = text.lower()
        found_phrases = []

        for pattern in self.MARKETING_AI_GIVEAWAY_TERMS:
            matches = re.findall(pattern, text_lower)
            if matches:
                found_phrases.extend(matches)

        passed = len(found_phrases) == 0
        details = (
            f"AI-giveaway phrases detected: {', '.join(found_phrases)}"
            if not passed
            else "Language sounds authentically human"
        )

        return {
            'check_name': 'AI Giveaway Language',
            'passed': passed,
            'details': details,
        }

    def _check_marketing_format(self, text):
        """Check marketing email format — plain text with bullets and en dashes allowed.
        Blocks markdown, HTML, and em dashes."""
        formatting_issues = []

        if re.search(r'\*\*[^*]+\*\*', text):
            formatting_issues.append('bold markdown (**text**)')
        if re.search(r'(?<!\w)#{1,6}\s+', text):
            formatting_issues.append('markdown headers (#)')
        if re.search(r'<[a-zA-Z][^>]*>', text):
            formatting_issues.append('HTML tags')
        if re.search(r'\u2014', text):
            formatting_issues.append('em dashes')
        # Allowed: Unicode box-drawing (\u2500, \u2501), arrows (\u2192), stars (\u2726),
        # bullets (\u2022), en dashes (\u2013), and emoji.

        passed = len(formatting_issues) == 0
        details = (
            f"Formatting issues: {', '.join(formatting_issues)}"
            if not passed
            else "Marketing format verified"
        )

        return {
            'check_name': 'Plain Text Format',
            'passed': passed,
            'details': details,
        }

    def _check_has_call_to_action(self, text):
        """Marketing emails must include a clear next step for the customer."""
        text_lower = text.lower()
        cta_phrases = [
            'give us a call', 'give us a ring', 'call us', 'phone us',
            'visit your nearest branch', 'drop into a branch', 'pop into',
            'reply to this email', 'get in touch', 'reach out',
            'book a', 'schedule a', 'arrange a',
            '1300 000 000', 'lending specialist', 'alternatives@',
            'sarah mitchell', 'lending officer', 'senior lending officer',
            'lending team', 'direct line', 'directly on',
            'contact me directly', 'contact me', 'aussieloanai@gmail.com',
        ]
        has_cta = any(phrase in text_lower for phrase in cta_phrases)
        return {
            'check_name': 'Call to Action',
            'passed': has_cta,
            'details': 'Clear call to action present' if has_cta else 'Missing call to action (phone, branch visit, or reply)',
        }

    def _marketing_template_fallback(self, application, nbo_amounts, start_time, nbo_result=None):
        """Generate a template marketing email with actual customer-specific offers."""
        import time as _time
        from apps.email_engine.services.guardrails import GuardrailChecker

        first_name = (
            application.applicant.first_name
            or application.applicant.username
        )
        applicant_name = (
            f"{application.applicant.first_name} {application.applicant.last_name}".strip()
            or application.applicant.username
        )
        purpose = application.get_purpose_display().lower()

        # Build offer details from NBO result
        offers = (nbo_result or {}).get('offers', [])
        if offers:
            offer_blocks = []
            for i, offer in enumerate(offers, 1):
                name = offer.get('name', offer.get('type', 'Product'))
                bullets = []
                if offer.get('amount'):
                    bullets.append(f'  \u2022  Amount: ${offer["amount"]:,.2f}')
                if offer.get('estimated_rate'):
                    bullets.append(f'  \u2022  Rate: {offer["estimated_rate"]:.2f}% p.a.')
                if offer.get('term_months'):
                    bullets.append(f'  \u2022  Term: {offer["term_months"]} months')
                if offer.get('monthly_repayment'):
                    bullets.append(f'  \u2022  Estimated repayment: ${offer["monthly_repayment"]:,.2f}/month')
                if offer.get('fortnightly_repayment'):
                    bullets.append(f'  \u2022  Estimated repayment: ${offer["fortnightly_repayment"]:,.2f}/fortnight')

                block = f'Option {i}: {name}\n\n' + '\n'.join(bullets)
                if offer.get('benefit'):
                    block += f'\n\n{offer["benefit"]}'
                if offer.get('reasoning') and offer['reasoning'] != offer.get('benefit', ''):
                    block += f'\n\n{offer["reasoning"]}'
                offer_blocks.append(block)
            offers_text = '\n\n'.join(offer_blocks)

            subject = f'Next steps for your AussieLoanAI loan application'

            # Check if any offer is a term deposit (for Financial Claims Scheme disclaimer)
            has_term_deposit = any(
                'term deposit' in (o.get('name', '') + o.get('type', '')).lower()
                for o in offers
            )

            today_str = date.today().strftime('%d/%m/%Y')

            footer_parts = []
            if has_term_deposit:
                footer_parts.append(
                    '*Deposits up to $250,000 per account holder per authorised '
                    'deposit-taking institution are protected under the Australian '
                    "Government's Financial Claims Scheme."
                )
            footer_parts.append(
                f'Interest rates are current as at {today_str} and are subject to '
                'change without notice. This email contains general information only '
                'and does not take into account your personal financial situation, '
                'objectives, or needs. Before making a decision, please consider '
                'whether the product is appropriate for you. Full terms and conditions, '
                'including the Target Market Determination and Product Disclosure '
                'Statement, are available at www.aussieloanai.com.au.'
            )
            footer_parts.append(
                'You are receiving this email because you are an existing AussieLoanAI '
                'customer. If you no longer wish to receive marketing communications '
                'from us, you can unsubscribe here or manage your communication '
                'preferences in your account settings. AussieLoanAI Pty Ltd, '
                'Sydney NSW 2000.'
            )
            footer_text = '\n\n'.join(footer_parts)

            body = (
                f'Dear {first_name},\n\n'
                f'Following your recent loan application with us, we\'ve looked at your '
                f'profile and there are a few options worth considering.\n\n'
                f'{offers_text}\n\n'
                f'If any of these options interest you, I\'d be happy to talk them through '
                f'with you. You can contact me directly at 1300 000 000 '
                f'(Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or simply reply to this email.\n\n'
                f'Thanks for coming to us, {first_name}. We\'d love to help you find the '
                f'right option when you\'re ready.\n\n'
                f'Kind regards,\n\n'
                f'Sarah Mitchell\n'
                f'Senior Lending Officer\n'
                f'AussieLoanAI Pty Ltd\n'
                f'ABN 12 345 678 901 | Australian Credit Licence No. 012345\n'
                f'Ph: 1300 000 000\n'
                f'Email: aussieloanai@gmail.com\n\n'
                f'\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
                f'{footer_text}'
            )
        else:
            subject = f'Next Steps for Your Banking Needs'
            body = (
                f'Dear {first_name},\n\n'
                f'Thank you for your recent {purpose} loan enquiry with AussieLoanAI. '
                f'We value your relationship with us and wanted to let you know that '
                f'our lending team is available to discuss alternative options that may '
                f'suit your current needs.\n\n'
                f'To arrange a time to talk through your options, please contact me '
                f'directly on 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or reply '
                f'to this email.\n\n'
                f'Kind regards,\n\n'
                f'Sarah Mitchell\n'
                f'Senior Lending Officer\n'
                f'AussieLoanAI Pty Ltd\n'
                f'ABN 12 345 678 901 | Australian Credit Licence No. 012345\n'
                f'Ph: 1300 000 000\n'
                f'Email: aussieloanai@gmail.com'
            )

        generation_time_ms = int((_time.time() - start_time) * 1000)
        checker = GuardrailChecker()
        context = {
            'decision': 'denied',
            'loan_amount': float(application.loan_amount) if application.loan_amount else None,
            'nbo_amounts': nbo_amounts or [],
        }
        guardrail_results = checker.run_all_checks(body, context, email_type='marketing')
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        return {
            'subject': subject,
            'body': body,
            'prompt_used': '[TEMPLATE FALLBACK — Claude API unavailable]',
            'passed_guardrails': all_passed,
            'guardrail_results': guardrail_results,
            'quality_score': checker.compute_quality_score(guardrail_results),
            'generation_time_ms': generation_time_ms,
            'attempt_number': 1,
            'template_fallback': True,
            'input_tokens': 0,
            'output_tokens': 0,
        }

    def _parse_response(self, text):
        """Parse Claude response into subject and body."""
        lines = text.strip().split('\n')
        subject = ''
        body_start = 0

        for i, line in enumerate(lines):
            if line.lower().startswith('subject:'):
                subject = line[len('Subject:'):].strip()
                body_start = i + 1
                break

        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1

        body = '\n'.join(lines[body_start:]).strip()

        if not subject:
            subject = "Next steps for your AussieLoanAI loan application"

        return subject, body

    def _format_offers(self, offers):
        """Format NBO offers for the prompt."""
        if not offers:
            return 'No specific offers generated.'

        lines = []
        for i, offer in enumerate(offers, 1):
            parts = [f"Offer {i}: {offer.get('name', offer.get('type', 'Product'))}"]
            if offer.get('amount'):
                parts.append(f"  Amount: ${offer['amount']:,.2f}")
            if offer.get('term_months'):
                parts.append(f"  Term: {offer['term_months']} months")
            if offer.get('estimated_rate'):
                parts.append(f"  Est. Rate: {offer['estimated_rate']}%")
            if offer.get('benefit'):
                parts.append(f"  Benefit: {offer['benefit']}")
            if offer.get('reasoning'):
                parts.append(f"  Why this suits them: {offer['reasoning']}")
            lines.append('\n'.join(parts))

        return '\n\n'.join(lines)

    def _get_banking_context(self, application):
        """Pull banking profile for the prompt."""
        try:
            profile = application.applicant.profile
            return (
                f"- Savings Balance: ${float(profile.savings_balance):,.2f}\n"
                f"- Everyday Account Balance: ${float(profile.checking_balance):,.2f}\n"
                f"- Account Tenure: {profile.account_tenure_years} years\n"
                f"- Loyalty Tier: {profile.get_loyalty_tier_display()}\n"
                f"- Total Banking Products: {profile.num_products}\n"
                f"- On-Time Payment Rate: {profile.on_time_payment_pct:.1f}%\n"
                f"- Loyal Customer: {'Yes' if profile.is_loyal_customer else 'No'}"
            )
        except (AttributeError,):  # RelatedObjectDoesNotExist is a subclass
            return "- No banking relationship data available"
