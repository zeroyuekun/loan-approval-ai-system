import json
import os
import re
import time

import anthropic
import httpx

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


MARKETING_EMAIL_PROMPT = """You are drafting a follow-up email for AussieLoanAI, an Australian bank. This email is sent AFTER the customer has already received their decline notification. It does NOT repeat the decline. Instead, it acknowledges that the customer recently applied and pivots directly to alternative products the customer qualifies for.

The tone matches our other correspondence: professional banking communication that reads like it was written by a person, not a system. Clean formatting with no box-drawing dividers or UPPERCASE headers. Plain-text section labels. Sarah Mitchell has reviewed the customer's profile and is presenting alternatives she believes are relevant — with the authority of a senior lending officer and the clarity of someone who wants to be understood.

=== COMPLIANCE RULES ===
1. Do NOT repeat the decline decision. The customer already received that letter. Instead, acknowledge they recently applied and pivot to alternatives.
2. Under Banking Code 2025 (para 89-91), marketing must not be aggressive, misleading, or create undue pressure.
3. Under NCCP Act 2009 (s133), products offered must be "not unsuitable" for the customer.
4. Under ASIC RG 234, claims must not be misleading. Never imply guaranteed approval for credit products.
5. "Guaranteed returns" is permitted ONLY for term deposits (government-backed under Financial Claims Scheme).
6. Never reference protected characteristics (race, gender, religion, disability, marital status, age).
7. Australian English spelling: finalised, recognised, organisation, colour, favour, centre.
8. Australian financial terms: term deposit, everyday account, fortnight, p.a., settlement.
9. Use the customer's ACTUAL numbers from the data below. Do not invent figures.
10. Spam Act 2003 (Cth): include unsubscribe option and physical address in footer.

=== CUSTOMER CONTEXT ===
- Name: {applicant_name}
- First Name: {applicant_first_name}
- Requested: ${loan_amount:,.2f} for {purpose}
- Credit Score: {credit_score} (Equifax, 0-1200)
- Annual Income: ${annual_income:,.2f}
- Employment: {employment_type} ({employment_length} years)

=== BANKING RELATIONSHIP ===
{banking_context}

=== ALTERNATIVE OFFERS (pre-calculated by product engine) ===
{offers_detail}

=== RETENTION INTELLIGENCE ===
- Customer Retention Score: {retention_score}/100
- Loyalty Factors: {loyalty_factors}
- Retention Strategy: {nbo_analysis}

=== SPACING RULES ===
- Leave a BLANK LINE between every section and paragraph.
- Section labels appear on their own line, followed by a blank line, then the section content.
- Leave a blank line before and after bulleted lists.
- The sign-off block, separator, and footer are each separated by a blank line.

=== EMAIL FORMAT (follow this structure exactly) ===

1. Subject line (prefix with "Subject: "):
   Format: "Next steps for your AussieLoanAI loan application"
   or "{applicant_first_name}, some options worth considering"
   NEVER use "denied", "rejected", "declined", or "unsuccessful" in the subject.

2. "Dear {applicant_first_name}," followed by a blank line.

3. OPENING (2\u20133 sentences):
   Acknowledge their recent application briefly ("Following your recent loan application with us..."). Do NOT restate the decline. Pivot directly to the alternatives: "We have looked at your profile and there are a few options worth considering." Do NOT use performative phrases like "we value you as a customer" or "we genuinely want to help" \u2014 show value by offering something useful, not by saying you value them. Follow with a blank line.

4. For each alternative offer, use a clean section with a label on its own line:

   "Why consider this option:" or "Option [N]:" as a plain-text section label, then a blank line, then:
   \u2022  Key benefit 1 (e.g., "Higher approval odds: Often approved for borrowers building their credit history.")
   \u2022  Key benefit 2 (e.g., "Lower interest rates: Because the risk is lower with collateral in place.")

   After the bullets, leave a blank line, then include 1\u20132 sentences explaining how this specific product fits THIS customer, using their actual numbers where available.

   Leave a blank line between each offer section.

   For term deposits, you may say "Guaranteed returns" and "Government protected*" (with footnote).
   For credit products (loans, credit cards), NEVER say "guaranteed" anything.

5. CLOSING (split across two paragraphs):
   - First paragraph: Express genuine interest in helping. Use first person: "If any of these options interest you, I'd welcome the chance to talk them through with you." Provide direct contact: 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or reply to this email.
   - Second paragraph (after a blank line): Close with this exact line (substituting the customer's first name): "Thanks for coming to us, [First Name]. We'd love to help you find the right option when you're ready." Do NOT rephrase or reword this line.

6. Sign-off (after a blank line):

Sincerely,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd
ABN 12 345 678 901 | Australian Credit Licence No. 012345
Ph: 1300 000 000
Email: aussieloanai@gmail.com

7. Footer (after a separator line) with legal disclaimers:
   \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
   - Financial Claims Scheme footnote (* for term deposits if applicable)
   - Rate conditions footnote (** for bonus rates if applicable)
   - General advice warning and TMD/PDS reference
   - Unsubscribe line and physical address
   - ABN and Australian Credit Licence

=== TONE ===
- Sarah Mitchell is a senior lending officer who has reviewed this customer's profile and found alternatives worth presenting. She writes as a banking professional — composed, knowledgeable, and considerate — not as a marketing department running a campaign.
- The email should feel like a specific recommendation from a specific person, not a mass follow-up. But it must still read as correspondence from a licensed credit provider. Professional register, human delivery.
- Present offers as useful options backed by the customer's actual numbers, not consolation prizes. Do not oversell or be falsely enthusiastic.
- Use contractions naturally: "you're", "we've", "we'd", "it's", "that's". But keep the overall register appropriate for banking correspondence — warm contractions, not casual slang.
- No patronising language, no false urgency, no performative empathy ("we value you", "we truly care", "we understand how you feel").
- Do NOT repeat the decline. They already know. This email is about what comes next.
- Do NOT presume their emotions. No "we know this isn't what you wanted" or "we understand this is disappointing."
- Every sentence delivers value or information. No filler, no emotional performance.

=== TONE CALIBRATION EXAMPLE ===
Do NOT copy verbatim. Study the clean structure, the brief acknowledgement without repeating the decline, the benefit-led product presentation, and the direct personal closing. Notice there is no performative empathy or "we value you" language \u2014 value is shown by offering something useful.

Subject: Next steps for your AussieLoanAI loan application

Dear Neville,

Following your recent Personal Loan application with us, we have looked at your profile and there are a few options worth considering.

We can offer you a Secured Personal Loan, which uses a savings account, term deposit, or vehicle as collateral. This is often a strong path forward for customers in your position.

Why consider this option:

  \u2022  Higher approval odds: Secured loans are often approved for borrowers who may not qualify for an unsecured product of the same size.
  \u2022  Lower interest rates: Because the risk is lower for both parties when collateral is in place.
  \u2022  Flexible terms: Loan terms from 12 to 60 months, with repayments structured to suit your income.

Based on your current savings balance and income, a secured loan of up to $[XX,XXX] may be available to you at a competitive rate.

We'd also like to highlight our Goal Saver Account:

  \u2022  Earn up to 5.20% p.a.** on your savings with no lock-in period.
  \u2022  Building a consistent savings pattern strengthens future loan applications.

If any of these options interest you, I'd welcome the chance to talk them through with you. There may be a path forward that works well for your goals.

You can contact me directly at 1300 000 000 (Mon\u2013Fri, 8:30am \u2013 5:30pm AEST) or simply reply to this email.

Thanks for coming to us, Neville. We'd love to help you find the right option when you're ready.

Sincerely,

Sarah Mitchell
Senior Lending Officer
AussieLoanAI Pty Ltd
ABN 12 345 678 901 | Australian Credit Licence No. 012345
Ph: 1300 000 000
Email: aussieloanai@gmail.com

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
**The 5.20% p.a. bonus rate applies when you deposit a minimum of $100 per month and make no withdrawals. If conditions are not met in a given month, the base rate of [X.XX]% p.a. will apply. Rate is variable and subject to change.

Interest rates are current as at [DD/MM/YYYY] and are subject to change without notice. This email contains general information only and does not take into account your personal financial situation, objectives, or needs. Before making a decision, please consider whether the product is appropriate for you. Full terms and conditions, including the Target Market Determination and Product Disclosure Statement, are available at www.aussieloanai.com.au.

You are receiving this email because you are an existing AussieLoanAI customer. If you no longer wish to receive marketing communications from us, you can unsubscribe here or manage your communication preferences in your account settings. AussieLoanAI Pty Ltd, Sydney NSW 2000.

(End of calibration example. Adapt structure, products, and numbers for this customer's actual data.)
"""


class MarketingAgent:
    """Generates follow-up marketing emails for denied applicants with alternative product offers."""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
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

        return self._generate_with_retries(application, prompt, start_time, nbo_amounts=nbo_amounts)

    def _generate_with_retries(self, application, prompt, start_time, attempt=1, nbo_amounts=None):
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
                response = self.client.messages.create(
                    model='claude-sonnet-4-20250514',
                    max_tokens=1500,
                    temperature=getattr(django_settings, 'AI_TEMPERATURE_MARKETING', 0.2),
                    messages=[{'role': 'user', 'content': current_prompt}],
                )
                break
            except anthropic.AuthenticationError as api_err:
                _logger.error('Marketing email API auth error (not retryable): %s', api_err)
                raise
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
        context = {
            'decision': 'denied',
            'loan_amount': float(application.loan_amount) if application.loan_amount else None,
            'nbo_amounts': nbo_amounts or [],
        }
        guardrail_results = self.guardrail_checker.run_all_checks(body, context, email_type='marketing')
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r['passed']]
            self._last_feedback = "; ".join(f"{r['check_name']}: {r['details']}" for r in failed_checks)
            return self._generate_with_retries(application, prompt, start_time, attempt + 1, nbo_amounts=nbo_amounts)

        return {
            'subject': subject,
            'body': body,
            'prompt_used': current_prompt,
            'guardrail_results': guardrail_results,
            'passed_guardrails': all_passed,
            'generation_time_ms': generation_time_ms,
            'attempt_number': attempt,
        }

    def _run_marketing_guardrails(self, body, application):
        """Run compliance checks appropriate for marketing emails."""
        results = []

        # Prohibited language check (same as denial/approval emails)
        results.append(self.guardrail_checker.check_prohibited_language(body))

        # Tone check
        results.append(self.guardrail_checker.check_tone(body))

        # AI-giveaway language check (marketing-specific: allows "comprehensive" and "tailored")
        results.append(self._check_marketing_ai_giveaway_language(body))

        # Professional financial language check (no misleading claims)
        results.append(self.guardrail_checker.check_professional_financial_language(body))

        # Marketing format check (allows Unicode dividers and emoji but blocks markdown/HTML)
        results.append(self._check_marketing_format(body))

        # Marketing-specific: must NOT reference the decline
        results.append(self._check_no_decline_language(body))

        # Marketing-specific: must include a call to action
        results.append(self._check_has_call_to_action(body))

        # Marketing-specific: no patronising language toward declined customers
        results.append(self._check_patronising_language(body))

        # Marketing-specific: no false urgency to pressure vulnerable customers
        results.append(self._check_no_false_urgency(body))

        # Marketing-specific: no guaranteed approval language
        results.append(self._check_no_guaranteed_approval(body))

        # Sentence rhythm check (warning severity — feedback only, does not block)
        results.append(self.guardrail_checker.check_sentence_rhythm(body))

        return results

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
