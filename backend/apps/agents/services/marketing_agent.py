import json
import os
import re
import time

import anthropic

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


MARKETING_EMAIL_PROMPT = """You are drafting a polished retention email for AussieLoanAI, an Australian bank. This email is a forward-looking follow-up sent 1-2 hours AFTER the decline notification. It NEVER references the decline. It presents alternative products the customer qualifies for, using their real financial data.

The email uses a modern, structured marketing format with divider lines, product highlight cards, and a professional footer with legal disclaimers. It should look like a premium retention email from a Big 4 Australian bank's digital marketing team.

=== COMPLIANCE RULES ===
1. NEVER reference the decline, rejection, or unsuccessful application. This is forward-looking only.
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

=== EMAIL FORMAT (follow this structure exactly) ===

1. Subject line (prefix with "Subject: "):
   Personalised and benefit-led. Use the customer's first name and a specific number.
   Examples: "{applicant_first_name}, your savings could be earning you $X,XXX this year"
   or "{applicant_first_name}, we've found two options worth a look"
   NEVER reference the decline. No exclamation marks.

2. Greeting: "Hi {applicant_first_name},"

3. Opening paragraph (2-3 sentences):
   Reference their banking relationship (tenure, payment history, savings) to show you looked at their file. Frame the email as "we've identified options tailored to your situation." Warm, confident, forward-looking. Do NOT mention the decline.

4. For each offer, create a PRODUCT CARD using this format:

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u2726  OUR TOP PICK FOR YOU (or ALSO WORTH CONSIDERING for 2nd/3rd offers)
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

Product Name
Rate  |  Key benefit  |  Key feature

2-3 sentences explaining how this product fits THIS customer specifically, using their actual numbers (savings balance, income, payment history). Calculate approximate returns or repayments where possible.

\u2192  Call to action: [Action text]

   Use the FIRST offer as "OUR TOP PICK FOR YOU" and subsequent offers as "ALSO WORTH CONSIDERING".
   For term deposits, you may say "Guaranteed returns" and "Government protected*" (with footnote).
   For credit products (loans, credit cards), NEVER say "guaranteed" anything.

5. After the last product card, add a closing divider and a bridge paragraph:
   "Which one suits you best?" then introduce Sarah Mitchell as their dedicated lending officer.
   Include phone emoji (\U0001f4de) and email emoji (\U0001f4e7) for contact details:
   \U0001f4de  Call Sarah directly: 1300 000 000 (Mon\u2013Fri, 8:30am\u20135:30pm AEST)
   \U0001f4e7  Or simply reply to this email

6. Closing line: "We're here to help your money go further." or similar warm, genuine line.

7. Sign-off:
Warm regards,
The AussieLoanAI Team

8. Footer (after a divider line) with legal disclaimers:
   - Financial Claims Scheme footnote (* for term deposits if applicable)
   - Rate conditions footnote (** for bonus rates if applicable)
   - General advice warning and TMD/PDS reference
   - Unsubscribe line and physical address
   - ABN and Australian Credit Licence placeholders

=== TONE ===
- Warm, confident, modern. Like a fintech retention email, not a stuffy bank letter.
- The customer should feel valued and that someone actually looked at their profile.
- Present offers as genuinely useful options, not consolation prizes.
- Use contractions naturally: "you're", "we've", "we'd", "it's", "that's".
- No patronising language, no false urgency, no decline references.
- You may use "tailored" and "comprehensive" when describing specific product features.

=== TONE CALIBRATION EXAMPLE ===
Do NOT copy verbatim. Study the structure: personalised subject with a number, relationship-anchored opening, product cards with dividers and specific numbers, emoji contact details, legal footer.

Subject: {applicant_first_name}, your savings could be earning you $1,625 this year

Hi {applicant_first_name},

Six years of banking with us hasn't gone unnoticed. You're one of our most valued customers, and we'd like to make sure your money is working just as hard as you are.

We've taken a look at your account profile and identified two options tailored to your situation, both designed to help you grow your savings with confidence.

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u2726  OUR TOP PICK FOR YOU
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

AussieLoanAI 12-Month Term Deposit
5.00% p.a.  |  Guaranteed returns  |  Government protected*

Based on your current balance of $32,500, you could earn approximately $1,625 in interest over 12 months, guaranteed, with no market risk to your capital.

That's your money earning for you while you focus on what matters.

\u2192  Lock in your rate today

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u2726  ALSO WORTH CONSIDERING
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

AussieLoanAI Goal Saver
5.20% p.a. bonus rate**  |  No lock-in  |  Full flexibility

Deposit just $100 per month and you'll earn the bonus rate on your entire balance. It's a simple, flexible way to build consistent savings habits, and it looks great on future credit applications too.

\u2192  Start saving smarter

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

Which one suits you best? Your dedicated lending officer, Sarah Mitchell, is across your profile and happy to walk you through either option, no obligation, no pressure.

\U0001f4de  Call Sarah directly: 1300 000 000 (Mon\u2013Fri, 8:30am\u20135:30pm AEST)
\U0001f4e7  Or simply reply to this email

We're here to help your money go further.

Warm regards,
The AussieLoanAI Team

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

*Deposits up to $250,000 per account holder are protected under the Australian Government's Financial Claims Scheme. Terms and conditions apply. AussieLoanAI Pty Ltd ABN [XX XXX XXX XXX]. Australian Credit Licence No. [XXXXXX].

**The 5.20% p.a. bonus rate applies when you deposit a minimum of $100 per month and make no withdrawals. If conditions are not met in a given month, the base rate of [X.XX]% p.a. will apply for that month. Rate is variable and subject to change.

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
        self.client = anthropic.Anthropic(api_key=api_key)
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

        return self._generate_with_retries(application, prompt, start_time)

    def _generate_with_retries(self, application, prompt, start_time, attempt=1):
        """Generate the email with guardrail retry logic."""
        from django.conf import settings as django_settings
        current_prompt = prompt
        if attempt > 1:
            feedback = getattr(self, '_last_feedback', '')
            current_prompt += f"\n\nIMPORTANT: Previous attempt failed compliance checks: {feedback}. Fix these issues."
            current_prompt += f"\n\n(This is generation attempt {attempt} of {self.MAX_RETRIES}.)"

        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1500,
            temperature=getattr(django_settings, 'AI_TEMPERATURE_MARKETING', 0.2),
            messages=[{'role': 'user', 'content': current_prompt}],
        )

        response_text = response.content[0].text
        generation_time_ms = int((time.time() - start_time) * 1000)

        subject, body = self._parse_response(response_text)

        # Run guardrails — marketing emails use the 'marketing' context
        guardrail_results = self._run_marketing_guardrails(body, application)
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r['passed']]
            self._last_feedback = "; ".join(f"{r['check_name']}: {r['details']}" for r in failed_checks)
            return self._generate_with_retries(application, prompt, start_time, attempt + 1)

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
        """Marketing emails must not reference the decline — this is a forward-looking message."""
        import re
        text_lower = text.lower()
        decline_phrases = [
            r'\b(declined|denied|rejected|unsuccessful|turned down)\b',
            r'\b(did not meet|does not meet|failed to meet)\b',
            r'\b(unable to approve|cannot approve|could not approve)\b',
            r'\bapplication was not\b',
        ]
        found = []
        for pattern in decline_phrases:
            matches = re.findall(pattern, text_lower)
            if matches:
                found.extend(matches)

        passed = len(found) == 0
        details = f"Found decline references: {', '.join(str(f) for f in found)}" if not passed else "No decline language detected"
        return {
            'check_name': 'no_decline_language',
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
            'check_name': 'patronising_language',
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
            'check_name': 'false_urgency',
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
            'check_name': 'no_guaranteed_approval',
            'passed': passed,
            'details': details,
        }

    # Marketing-specific AI-giveaway terms — excludes "comprehensive" and "tailored"
    # which are legitimate in product descriptions (e.g. "comprehensive insurance package",
    # "tailored repayment schedule").
    MARKETING_AI_GIVEAWAY_TERMS = [
        r'\bpleased to (?:confirm|inform|advise)\b',
        r'\bdelighted\b',
        r'\bthrilled\b',
        r'\bgreat news\b',
        r'\bexciting\b',
        r'\bwe are happy to\b',
        r'\bI wanted to reach out\b',
        r'\bnavigate\b',
        r'\bjourney\b',
        r'\bleverage\b',
        r'\bempower\b',
        r'\brest assured\b',
        r'\bdon[\u2019\']t hesitate\b',
        r'\bwe are here to help\b',
        # r'\bwalk you through\b',  # Removed: legitimate in marketing retention context
        r'\bevery step of the way\b',
        r'\bwe understand how important\b',
        r'\bwe understand this (?:may be|is) disappointing\b',
        r'\bwe appreciate the trust\b',
        r'\bregardless of (?:this|the) outcome\b',
        r'\bshould you have any questions at all\b',
        r'\bplease do not hesitate to contact\b',
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
        # Performative empathy
        r'\bwe understand that\b',
        r'\bwe recognise that\b',
        r'\bwe appreciate that\b',
        r'\bwe value your\b',
        # Over-formal constructions
        r'\bwe would like to\b',
        r'\bwe would like you to\b',
        r'\bshould you wish to\b',
        r'\bshould you require\b',
        r'\bshould you have any\b',
        r'\bwe wish you\b',
        # NOTE: "we look forward to" is natural in retention context — intentionally excluded
        # AI closing/filler patterns
        r'\bplease feel free to\b',
        # r'\bdo not hesitate\b',  # Removed: legitimate in formal marketing correspondence
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
            'check_name': 'ai_giveaway_language',
            'passed': passed,
            'details': details,
        }

    def _check_marketing_format(self, text):
        """Check marketing email format — allows Unicode dividers, emoji, and arrows
        but still blocks markdown, HTML, and em dashes."""
        formatting_issues = []

        if re.search(r'\*\*[^*]+\*\*', text):
            formatting_issues.append('bold markdown (**text**)')
        if re.search(r'(?<!\w)#{1,6}\s+', text):
            formatting_issues.append('markdown headers (#)')
        if re.search(r'<[a-zA-Z][^>]*>', text):
            formatting_issues.append('HTML tags')
        if re.search(r'\u2014', text):
            formatting_issues.append('em dashes')
        # Note: Unicode box-drawing (\u2500, \u2501), arrows (\u2192), stars (\u2726),
        # bullets (\u2022), en dashes (\u2013), and emoji are all ALLOWED in marketing format.

        passed = len(formatting_issues) == 0
        details = (
            f"Formatting issues: {', '.join(formatting_issues)}"
            if not passed
            else "Marketing format verified"
        )

        return {
            'check_name': 'plain_text_format',
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
        ]
        has_cta = any(phrase in text_lower for phrase in cta_phrases)
        return {
            'check_name': 'call_to_action',
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
            subject = "Your lending options with AussieLoanAI"

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
        except Exception:
            return "- No banking relationship data available"
