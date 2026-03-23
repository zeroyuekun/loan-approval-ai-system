import re


class GuardrailChecker:
    """Runs compliance checks on generated emails."""

    PROHIBITED_TERMS = [
        # Discriminatory language patterns (use non-capturing groups so findall returns the full match)
        r'\b(?:race|racial|ethnicity|ethnic)\b',
        r'\b(?:religion|religious|church|mosque|synagogue|temple)\b',
        r'\b(?:gender|sex|male|female|transgender)\b',
        r'\b(?:pregnant|pregnancy|maternity)\b',
        r'\b(?:disability|disabled|handicap)\b',
        r'\b(?:national origin|nationality|immigrant|alien)\b',
        r'\b(?:marital status|married|divorced|widowed)\b',
        # "single" only triggers when NOT followed by common financial/application nouns
        r'\bsingle\b(?!\s+(?:\w+\s+)*?(?:payment|applicant|application|account|transaction|loan|source|income|person|borrower|repayment|monthly|amount|point|entry|deposit|product|obligation|contact|reference|instalment|rate|fee|charge|document|step|purpose|entity|item|place|call|email|platform|portal|goal|saver|everyday|savings|option|alternative|offer|phone|number|line|action|digit|click|visit))',
        # "age" only triggers when NOT in financial/legal contexts
        r'\bage\b(?!\s*(?:of|action|notice|requirement|pension|bracket|limit|discrimination|act|group|range|related|based|verification|eligibility|threshold))',
    ]

    AGGRESSIVE_TERMS = [
        r'\b(stupid|idiot|foolish|incompetent)\b',
        r'\b(demand|insist|must immediately)\b',
        r'\b(threat|threaten|consequences)\b',
        r'\b(never|always)\s+(will|should|can)\b',
        r'\b(you failed|your fault|blame)\b',
        r'\b(unacceptable|disgraceful|shocking)\b',
    ]

    # AI-giveaway phrases that real bank officers never use
    AI_GIVEAWAY_TERMS = [
        # "pleased to inform" and "pleased to confirm" are legitimate in formal approval letters
        # r'\bpleased to (?:inform|advise)\b',
        r'\bdelighted\b',
        r'\bthrilled\b',
        r'\bgreat news\b',
        r'\bexciting\b',
        r'\bwe are happy to\b',
        r'\bI wanted to reach out\b',
        r'\bnavigate\b',
        # r'\bjourney\b',  # Removed: legitimate in Australian lending ("home ownership journey")
        r'\bleverage\b',
        r'\bempower\b',
        # r'\bcomprehensive\b',  # Removed: legitimate in formal letters ("comprehensive loan agreement")
        r'\btailored\b',
        r'\brest assured\b',
        # r'\bdon[\u2019\']t hesitate\b',  # Removed: legitimate in formal approval/customer-service correspondence
        # r'\bwe are here to help\b',  # Removed: legitimate in hardship/customer-service sections
        r'\bwalk you through\b',
        r'\bevery step of the way\b',
        r'\bwe understand how important\b',
        r'\bwe understand this (?:may be|is) disappointing\b',
        r'\bnot the outcome you were hoping for\b',
        r'\bwe (?:understand|know) (?:this|how) (?:is|may be|must be) (?:difficult|hard|tough|frustrating)\b',
        r'\bwe want to be transparent about\b',
        # r'\bwe appreciate the trust\b',  # Removed: legitimate closing in approval letters
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
        # Performative empathy
        r'\bwe understand that\b',
        r'\bwe recognise that\b',
        r'\bwe appreciate that\b',
        # Over-formal constructions
        r'\bwe would like to\b',
        r'\bwe would like you to\b',
        r'\bshould you wish to\b',
        r'\bshould you require\b',
        r'\bshould you have any\b',
        r'\bwe wish you\b',
        # r'\bwe are pleased to inform you\b',  # Removed: industry-standard in AU banking (ANZ, CBA, Westpac all use it)
        r'\bwe appreciate your trust in\b',
        r'\bwe truly (?:value|care|appreciate)\b',
        r'\bit is our pleasure to\b',
        # r'\bwe look forward to\b',  # Removed: legitimate closing in approval letters
        # AI closing/filler patterns
        r'\bplease feel free to\b',
        r'\bwe are available\b',
        r'\bthank you for trusting\b',
        r'\bin order to\b',
        r'\bat this point in time\b',
        r'\bit is important to note that\b',
        r'\bit is worth noting that\b',
        r'\bmoving forward\b',
        r'\bgoing forward\b',
    ]

    # Unprofessional financial language — real banks never use these
    # Sources: ASIC RG 234 (misleading/deceptive conduct), NCCP Act s133
    UNPROFESSIONAL_FINANCIAL_TERMS = [
        r'\bguaranteed approval\b',
        r'\b100% approval\b',
        r'\bno questions asked\b',
        r'\brisk[- ]free\b',
        r'\btoo good to (?:be true|pass up)\b',
        r'\byou deserve\b',
        r'\byou[\u2019\']ve earned\b(?!\s+(?:through|over|with|by|during|in))',
        # "congratulations" removed: appropriate in formal approval letters
        r'\bexclusive(?:ly)? for you\b',
        r'\bbest (?:rate|deal|offer) (?:in|on the) (?:market|australia)\b',
        r'\blowest (?:rate|fee|cost)\b',
        r'\bno (?:hidden |extra )?(?:fees|charges|costs)\b',
        r'\b(?:pre[- ]?approved|already approved)\b',
        r'\blimited (?:time|spots?|availability)\b',
        r'\bdon[\u2019\']t miss (?:out|this)\b',
    ]

    # Phrases that are factually correct but demeaning in context.
    # Each tuple: (pattern, better_alternative, context_note)
    DIGNITY_VIOLATIONS = [
        (r'\byou (?:have |had )?no (?:job|employment|work|income)\b', 'your current employment situation', 'Implies personal failing rather than circumstance'),
        (r'\byou (?:are|were) unemployed\b', 'your employment status at the time of application', 'Labels the person, not the situation'),
        (r'\byou lost your job\b', 'a change in your employment circumstances', 'Assigns fault to the customer'),
        (r'\byou (?:are|were) (?:let go|fired|sacked|terminated|made redundant)\b', 'a change in your employment circumstances', 'Too blunt about job loss'),
        (r'\byou lack (?:stable |steady )?employment\b', 'your employment tenure at the time of application', 'Implies personal deficiency'),
        (r'\byou(?:r)? (?:do not|don[\u2019\']t) have a (?:stable |steady |permanent )?job\b', 'your current employment arrangement', 'Implies personal failing'),
        (r'\byou(?:r income is| earn| make) (?:too little|not enough|insufficient)\b', 'the loan amount relative to your verified income', 'Passes judgment on earning capacity'),
        (r'\byou cannot afford\b', 'the requested amount exceeded our serviceability thresholds', 'Implies personal inadequacy'),
        (r'\byou(?:r)? (?:do not|don[\u2019\']t) earn enough\b', 'your income relative to the loan amount', 'Judges the person not the ratio'),
        (r'\byour (?:poor|bad|low|weak) (?:credit|finances|financial)\b', 'your credit profile at the time of assessment', 'Value judgment on the person'),
        (r'\byou(?:r)? (?:failed|inability) to (?:pay|repay|meet|manage)\b', 'repayment capacity based on our assessment', 'Implies personal failure'),
        (r'\byour debt (?:is|was) too (?:high|much|large)\b', 'your existing obligations relative to income', 'Sounds like a personal lecture'),
        (r'\byou (?:are|were) (?:in |carrying )?too much debt\b', 'your debt-to-income ratio', 'Blames the customer'),
        (r'\byou(?:r)? (?:have |had )?(?:a )?(?:bad|poor|terrible|awful) credit\b', 'your credit history at the time of assessment', 'Labels the person through their credit'),
        (r'\byou (?:defaulted|missed payments)\b', 'your repayment history as reported by credit bureaus', 'Accusatory tone'),
        (r'\byou went bankrupt\b', 'a prior bankruptcy event on your credit file', 'Defines the person by the event'),
        (r'\byou (?:have |had )?no savings\b', 'your savings position at the time of application', 'Implies irresponsibility'),
        (r'\byou are too (?:old|young)\b', 'the loan term relative to standard lending criteria', 'Direct age discrimination'),
        (r'\byou(?:r)? (?:do not|don[\u2019\']t) own (?:a |your )?(?:home|property|house)\b', 'your current accommodation arrangements', 'Implies lesser status for renters'),
        (r'\byou (?:are|were) (?:not |un)?(?:suitable|eligible|qualified|worthy)\b', 'your application did not meet our lending criteria at this time', 'Labels the person as deficient'),
        (r'\byou (?:are|were) (?:a |an )?(?:high|greater|elevated) risk\b', 'the risk profile of this application', 'Labels the human as a risk'),
    ]

    # Psychology-informed reframes: (pattern, suggestion, research_basis)
    # Sources: Kahneman/Tversky framing effect, Hayne Royal Commission,
    # ABA Financial Difficulty Guideline 2025, Banking Code para 7(c),
    # Peak-end rule (Kahneman), dual-process theory (System 1/2)
    PSYCHOLOGY_REFRAMES = {
        'negative_framing': [
            (r'\bwe cannot (?:offer|provide|approve|give|extend|grant)\b',
             'reframe around what you CAN do: "what we can offer is..."',
             'Framing effect: gain-framed language improves perception by 15-30%'),
            (r'\byou are unable to\b',
             'reframe as situational: "your application at this time"',
             'Framing effect: attribute to situation, not the person'),
            (r'\bthis is not possible\b',
             '"what is possible is..." or "an option available to you is..."',
             'Positive reframing converts constraints into alternatives'),
            (r'\bthere is no (?:way|option|possibility)\b',
             '"the options available to you include..."',
             'Loss aversion: finality triggers 2x the emotional pain'),
        ],
        'institutional_coldness': [
            (r'\bthe bank has (?:determined|decided|concluded)\b',
             'use first person: "I\'ve reviewed..." or "after looking at your details..."',
             'Hayne Commission: institutional voice creates power imbalance'),
            (r'\bour systems? (?:indicate|show|flag|record)\b',
             '"when I reviewed your application..."',
             'Monzo: active voice always; never hide behind systems'),
            (r'\b(?:per|as per) our (?:policy|policies|records|guidelines)\b',
             'explain the reason directly: "because..." or "the reason is..."',
             'Banking Code para 7(c): treat with sensitivity, respect and compassion'),
            (r'\bit has been determined (?:that|by)\b',
             '"I\'ve found that..." or "after reviewing your application..."',
             'Passive voice hides accountability; active voice builds trust'),
        ],
        'finality_language': [
            (r'\bthis decision is final\b',
             '"this decision is based on your circumstances at the time of application"',
             'ABA Guideline 2025: frame as "not yet", not permanent rejection'),
            (r'\bthere is nothing (?:more|else|further) we can do\b',
             '"if your circumstances change, please reach out"',
             'Loss aversion: finality doubles emotional impact'),
            (r'\bwe have closed your\b',
             'describe what happens next rather than what has ended',
             'Peak-end rule: the final message determines the lasting memory'),
            (r'\bno further action (?:will be|is|can be) taken\b',
             '"if you\'d like to discuss this further..."',
             'Credit union research: supportive denials increase future loyalty'),
            (r'\bthis matter is (?:closed|concluded|finalised)\b',
             'end with forward-looking language and a direct contact',
             'Banking Code para 172: respond promptly to requests to discuss difficulties'),
        ],
        'weak_closings': [
            (r'\bwe wish you (?:well|all the best|good luck|the best)\b',
             'use specific warmth: "Thanks for coming to us, [Name]. We\'d love to help you find the right option when you\'re ready."',
             'Peak-end rule: generic well-wishes feel dismissive'),
            (r'\bgood luck (?:with|in|for)\b',
             '"if you\'d like to explore other options, I\'m here to help"',
             'Recency effect: final sentences determine overall satisfaction'),
        ],
    }

    # Grammar patterns that undermine professionalism in formal banking correspondence
    # Source: Australian Style Manual
    GRAMMAR_ISSUES = [
        (r"\bcan[\u2019']t\b", "cannot"),
        (r"\bwon[\u2019']t\b", "will not"),
        (r"\bshouldn[\u2019']t\b", "should not"),
        (r"\bcouldn[\u2019']t\b", "could not"),
        (r"\bwouldn[\u2019']t\b", "would not"),
        (r"\bhaven[\u2019']t\b", "have not"),
        (r"\bhasn[\u2019']t\b", "has not"),
        (r"\baren[\u2019']t\b", "are not"),
        (r"\bwasn[\u2019']t\b", "was not"),
        (r"\bweren[\u2019']t\b", "were not"),
        # Note: "don't", "isn't", "it's", "we'd", "you'll", "we're", "I'm" excluded
        # intentionally — our tone calibration uses these for warmth.
    ]

    # Comparison rate warning — mandatory under National Credit Code Reg 99
    COMPARISON_RATE_WARNING_REQUIRED = re.compile(
        r'comparison rate.*?applies only to the example',
        re.IGNORECASE | re.DOTALL,
    )

    # Australian legal disclosures are required — strip them before checking for prohibited terms
    COMPLIANCE_DISCLOSURE_PATTERN = re.compile(
        r'(?:'
        r'the equal credit opportunity act prohibits'
        r'|under australian law'
        r'|under the .{0,120}(?:privacy act|nccp act|national consumer credit|human rights|discrimination act|banking code|consumer law)'
        r'|(?:sex|racial|disability|age) discrimination act\s*\d*'
        r'|australian human rights commission act'
        r'|responsible lending (?:obligations|assessment|conduct)'
        r'|banking code of practice'
        r'|national consumer credit protection act'
        r'|afca|australian financial complaints authority'
        r'|equifax|illion|experian'
        r'|asic|australian securities and investments commission'
        r'|credit report(?:ing)?'
        r'|hayne royal commission'
        r'|anti[- ]money laundering'
        r').*?(?:\.|$)',
        re.IGNORECASE | re.DOTALL,
    )

    def check_prohibited_language(self, text):
        """Check for discriminatory terms in the email, excluding legal disclosures."""
        # First pass: check raw text to catch bias hidden in legal framing
        raw_lower = text.lower()
        found_terms = []

        for pattern in self.PROHIBITED_TERMS:
            matches = re.findall(pattern, raw_lower)
            if matches:
                found_terms.extend(matches)

        if found_terms:
            # Second pass: strip legal disclosures and re-check to avoid
            # false positives on legitimate compliance text
            text_stripped = self.COMPLIANCE_DISCLOSURE_PATTERN.sub('', text)
            text_lower = text_stripped.lower()
            found_terms = []

            for pattern in self.PROHIBITED_TERMS:
                matches = re.findall(pattern, text_lower)
                if matches:
                    found_terms.extend(matches)

        passed = len(found_terms) == 0
        details = f"Found prohibited terms: {', '.join(found_terms)}" if not passed else "No prohibited language detected"

        return {
            'check_name': 'Prohibited Language',
            'passed': passed,
            'details': details,
        }

    def check_hallucinated_numbers(self, text, context):
        """Verify dollar amounts and percentages match the application data."""
        # If loan_amount is None/missing, we cannot validate amounts — skip the check
        loan_amount = context.get('loan_amount')
        if loan_amount is None:
            return {
                'check_name': 'Hallucinated Numbers',
                'passed': True,
                'details': 'No loan amount in context; skipped hallucinated numbers check',
            }

        issues = []

        # Strip ASIC comparison rate footnotes before checking
        # (standard regulatory text contains fixed amounts like $30,000)
        text_to_check = re.sub(
            r'\*\s*[Cc]omparison rate (?:of|calculated).*?(?:cost of the loan\.|$)',
            '', text, flags=re.DOTALL,
        )
        # Strip Financial Claims Scheme disclosure (standard $250,000 guarantee)
        text_to_check = re.sub(
            r'\*?[Tt]erm deposits? up to \$250,000.*?Financial Claims Scheme\.?',
            '', text_to_check, flags=re.DOTALL,
        )

        # Extract dollar amounts from the email (excluding placeholder formats like $[X,XXX])
        dollar_pattern = r'\$[\d,]+(?:\.\d{2})?'
        found_amounts = re.findall(dollar_pattern, text_to_check)

        # Convert context amounts for comparison
        valid_amounts = set()
        amount = float(loan_amount)
        valid_amounts.add(f"${amount:,.2f}")
        valid_amounts.add(f"${amount:,.0f}")
        valid_amounts.add(f"${int(amount):,}")

        # Add NBO offer amounts as valid (for marketing emails)
        for nbo_amt in context.get('nbo_amounts', []):
            nbo_val = float(nbo_amt)
            valid_amounts.add(f"${nbo_val:,.2f}")
            valid_amounts.add(f"${nbo_val:,.0f}")
            valid_amounts.add(f"${int(nbo_val):,}")

        # Add pricing engine amounts as valid (monthly payment, establishment fee)
        pricing = context.get('pricing', {})
        if pricing.get('monthly_payment_number'):
            mp = pricing['monthly_payment_number']
            valid_amounts.add(f"${mp:,.2f}")
        if pricing.get('establishment_fee_number'):
            ef = pricing['establishment_fee_number']
            valid_amounts.add(f"${ef:,.2f}")

        # For marketing emails with NBO offers, also allow derived amounts
        # (interest earned, monthly savings targets, fortnightly amounts) that are
        # plausible calculations from the NBO offer data. These are typically small
        # amounts the LLM computes from offer principal × rate × term.
        nbo_amounts_list = context.get('nbo_amounts', [])
        has_nbo = len(nbo_amounts_list) > 0

        for found in found_amounts:
            cleaned = found.replace(',', '').replace('$', '')
            try:
                val = float(cleaned)
                # Check if this amount is close to any known valid amount
                is_valid = any(
                    abs(val - float(str(va).replace(',', '').replace('$', ''))) < 1.0
                    for va in valid_amounts
                )

                # For NBO marketing emails: allow small derived amounts (interest,
                # savings targets, etc.) that are plausible calculations from offers.
                # Amounts under $5,000 in NBO emails are typically computed values
                # like annual interest ($1,625 = $32,500 × 5%) or monthly targets.
                if not is_valid and has_nbo and val < 5000:
                    is_valid = True

                if not is_valid:
                    issues.append(f"Unrecognized amount: {found}")
            except ValueError:
                continue

        # Validate percentages (interest rate, comparison rate) against pricing engine
        if pricing:
            valid_rates = set()
            if pricing.get('interest_rate_number') is not None:
                valid_rates.add(float(pricing['interest_rate_number']))
            if pricing.get('comparison_rate_number') is not None:
                valid_rates.add(float(pricing['comparison_rate_number']))

            if valid_rates:
                # Extract percentages from email, excluding common disclaimers
                # (e.g. "80% LVR", "100% offset", percentage ranges in legal text)
                pct_pattern = r'(\d+\.?\d*)\s*%'
                # Exclude lines containing common disclaimer terms
                disclaimer_pattern = re.compile(
                    r'\b(?:LVR|offset|of\s+the\s+loan|'
                    r'Financial Claims Scheme|government|'
                    r'deposit|minimum|withdrawal|base rate)\b',
                    re.IGNORECASE,
                )
                for line in text_to_check.split('\n'):
                    if disclaimer_pattern.search(line):
                        continue
                    pct_matches = re.findall(pct_pattern, line)
                    for pct_str in pct_matches:
                        try:
                            pct_val = float(pct_str)
                        except ValueError:
                            continue
                        # Skip common non-rate percentages
                        if pct_val in (0, 100) or pct_val > 30:
                            continue
                        # Check if this percentage matches a known valid rate
                        is_valid_rate = any(
                            abs(pct_val - vr) < 0.05
                            for vr in valid_rates
                        )
                        if not is_valid_rate:
                            issues.append(f"Unrecognized interest rate: {pct_str}%")

        passed = len(issues) == 0
        details = "; ".join(issues) if issues else "All amounts and rates verified"

        return {
            'check_name': 'Hallucinated Numbers',
            'passed': passed,
            'details': details,
        }

    def check_tone(self, text):
        """Check for aggressive or inappropriate language."""
        text_lower = text.lower()
        found_issues = []

        for pattern in self.AGGRESSIVE_TERMS:
            matches = re.findall(pattern, text_lower)
            if matches:
                found_issues.extend(matches)

        passed = len(found_issues) == 0
        details = f"Tone issues found: {', '.join(str(i) for i in found_issues)}" if not passed else "Tone is professional"

        return {
            'check_name': 'Tone Check',
            'passed': passed,
            'details': details,
        }

    def check_ai_giveaway_language(self, text):
        """Detect AI-generated phrasing that real bank officers never use."""
        text_lower = text.lower()
        found_phrases = []

        for pattern in self.AI_GIVEAWAY_TERMS:
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

    def check_professional_financial_language(self, text):
        """Check for unprofessional or misleading financial language."""
        text_lower = text.lower()
        found_issues = []

        for pattern in self.UNPROFESSIONAL_FINANCIAL_TERMS:
            matches = re.findall(pattern, text_lower)
            if matches:
                found_issues.extend(matches)

        passed = len(found_issues) == 0
        details = (
            f"Unprofessional financial language found: {', '.join(str(i) for i in found_issues)}"
            if not passed
            else "Financial language meets institutional standards"
        )

        return {
            'check_name': 'Professional Financial Language',
            'passed': passed,
            'details': details,
        }

    def check_plain_text_format(self, text):
        """Ensure email is plain text with no markdown, HTML, or formatting artefacts."""
        formatting_issues = []

        if re.search(r'\*\*[^*]+\*\*', text):
            formatting_issues.append('bold markdown (**text**)')
        if re.search(r'(?<!\w)#{1,6}\s+', text):
            formatting_issues.append('markdown headers (#)')
        # Flag markdown-style bullet lists (- or *) but allow:
        # - Unicode bullet character (\u2022) for formal structured emails
        # - Asterisk footnote markers (e.g., "* Comparison rate calculated...")
        if re.search(r'^\s*-\s+', text, re.MULTILINE):
            formatting_issues.append('bullet points (use \u2022 instead of -)')
        if re.search(r'^\s*\*\s+(?![Cc]omparison|WARNING)', text, re.MULTILINE):
            formatting_issues.append('bullet points (use \u2022 instead of *)')
        if re.search(r'<[a-zA-Z][^>]*>', text):
            formatting_issues.append('HTML tags')
        if re.search(r'\u2014', text):
            formatting_issues.append('em dashes')

        passed = len(formatting_issues) == 0
        details = (
            f"Formatting issues: {', '.join(formatting_issues)}"
            if not passed
            else "Plain text format verified"
        )

        return {
            'check_name': 'Plain Text Format',
            'passed': passed,
            'details': details,
        }

    def check_required_elements(self, text, decision, email_type='decision'):
        """Check that required elements are present based on decision and email type.

        Marketing emails have different requirements than formal decision letters:
        - Decision emails (approval/denial) need full regulatory elements
        - Marketing emails need a call to action but NOT credit report/AFCA references
        """
        text_lower = text.lower()
        missing = []

        if email_type == 'marketing':
            # Marketing emails only need a call to action (checked separately)
            # They should NOT require credit report, AFCA, or other regulatory elements
            pass
        elif decision == 'approved':
            has_next = any(phrase in text_lower for phrase in ['next step', 'next steps', 'what happens next', 'from here', 'to proceed'])
            if not has_next:
                missing.append('next steps')
            if 'approved' not in text_lower and 'approval' not in text_lower:
                missing.append('approval confirmation')
            has_before_sign = any(phrase in text_lower for phrase in ['before you sign', 'before signing', 'take the time to read'])
            if not has_before_sign:
                missing.append('before-you-sign consumer protection notice')
            has_hardship = any(phrase in text_lower for phrase in ['financial difficulty', 'hardship', 'financial hardship'])
            if not has_hardship:
                missing.append('financial hardship team reference')
            has_cooling = any(phrase in text_lower for phrase in ['cooling-off', 'cooling off'])
            if not has_cooling:
                missing.append('cooling-off period notice')
            has_afca = any(phrase in text_lower for phrase in ['afca', 'australian financial complaints authority', '1800 931 678'])
            if not has_afca:
                missing.append('AFCA dispute resolution reference')
        elif decision == 'denied':
            has_reasons = any(phrase in text_lower for phrase in ['reason', 'because', 'based on', 'due to', 'unfortunately', 'factor', 'criteria', 'unable to approve', 'not approved', 'unable to offer', 'not in a position'])
            if not has_reasons:
                missing.append('reasons for decision')
            has_credit_report = any(phrase in text_lower for phrase in ['credit report', 'equifax', 'illion', 'experian'])
            has_free = 'free' in text_lower and has_credit_report
            if not has_credit_report:
                missing.append('credit report rights notice')
            elif not has_free:
                missing.append('must specify "free" credit report (Banking Code para 81)')
            has_afca = any(phrase in text_lower for phrase in ['afca', 'australian financial complaints authority', '1800 931 678'])
            if not has_afca:
                missing.append('AFCA dispute resolution reference')

        passed = len(missing) == 0
        details = f"Missing required elements: {', '.join(missing)}" if not passed else "All required elements present"

        return {
            'check_name': 'Required Elements',
            'passed': passed,
            'details': details,
        }

    def check_word_count(self, text, decision):
        """Enforce word count limits per financial institution best practice.

        Strips the greeting line and sign-off block before counting so that
        only the substantive body is measured.
        """
        lines = text.strip().split('\n')

        # Strip greeting (first non-empty line if it starts with "Dear")
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and stripped.lower().startswith('dear '):
                start = i + 1
                break

        # Strip sign-off block (from "Regards" / "Kind regards" / "Sincerely" / "Warm regards" onward)
        end = len(lines)
        sign_off_patterns = ('regards', 'kind regards', 'sincerely', 'warm regards', 'yours faithfully', 'best regards', 'warmest regards')
        for i in range(len(lines) - 1, max(start - 1, -1), -1):
            stripped = lines[i].strip().lower().rstrip(',')
            if stripped in sign_off_patterns:
                end = i
                break

        body_text = ' '.join(lines[start:end])
        words = body_text.split()
        count = len(words)

        if decision == 'approved':
            limit = 650  # Formal structured approval letters with loan summary tables are longer
        else:
            limit = 500  # Denial letters with empathetic tone, improvement steps, and credit report info

        passed = count <= limit
        details = (
            f"Body is {count} words (limit: {limit})"
            if not passed
            else f"Word count OK ({count}/{limit})"
        )

        return {
            'check_name': 'Word Count',
            'passed': passed,
            'details': details,
        }

    def check_sentence_rhythm(self, text):
        """Flag suspiciously uniform sentence lengths (AI tends to produce ~15-word sentences).

        Returns severity 'warning' — used as retry feedback but does NOT block sending.
        """
        # Split into sentences on ., !, ? followed by whitespace or end-of-string
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        # Filter out very short fragments (sign-offs, greetings)
        sentences = [s for s in sentences if len(s.split()) >= 3]

        if len(sentences) < 4:
            return {
                'check_name': 'Sentence Rhythm',
                'passed': True,
                'severity': 'warning',
                'details': 'Too few sentences to assess rhythm',
            }

        word_counts = [len(s.split()) for s in sentences]
        avg = sum(word_counts) / len(word_counts)
        variance = sum((c - avg) ** 2 for c in word_counts) / len(word_counts)
        std_dev = variance ** 0.5

        passed = not (std_dev < 3.0 and avg > 10)
        details = (
            f"Sentence lengths are suspiciously uniform (std_dev={std_dev:.1f}, avg={avg:.1f} words). "
            "Vary sentence length: mix short (5-8 words) with medium (12-18 words)."
            if not passed
            else f"Sentence rhythm OK (std_dev={std_dev:.1f}, avg={avg:.1f})"
        )

        return {
            'check_name': 'Sentence Rhythm',
            'passed': passed,
            'severity': 'warning',
            'details': details,
        }

    def check_contextual_dignity(self, text):
        """Check for language that is factually correct but demeaning in context."""
        text_lower = text.lower()
        found_issues = []
        for pattern, alternative, note in self.DIGNITY_VIOLATIONS:
            matches = re.findall(pattern, text_lower)
            if matches:
                found_issues.append(f'"{matches[0]}" \u2192 use "{alternative}" ({note})')
        passed = len(found_issues) == 0
        details = f"Dignity issues found: {'; '.join(found_issues)}" if not passed else "Language respects customer dignity"
        return {'check_name': 'Contextual Dignity', 'passed': passed, 'details': details}

    def check_psychological_framing(self, text, decision='denied'):
        """Check for psychologically harmful language patterns (framing, coldness, finality, cognitive load, weak closings)."""
        text_lower = text.lower()
        found_issues = []
        for category, patterns in self.PSYCHOLOGY_REFRAMES.items():
            if category == 'weak_closings' and decision == 'approved':
                continue
            for pattern, suggestion, research in patterns:
                matches = re.findall(pattern, text_lower)
                if matches:
                    found_issues.append({'category': category, 'phrase': matches[0], 'suggestion': suggestion})
        # Cognitive load: sentences over 40 words (exclude regulatory footer)
        separator = '\u2500' * 5
        body_text = text.split(separator)[0] if separator in text else text
        for sentence in re.split(r'[.!?]\s+|\n\s*\n', body_text):
            wc = len(sentence.split())
            if wc > 40:
                found_issues.append({'category': 'cognitive_load', 'phrase': f'Sentence with {wc} words (max 40)', 'suggestion': 'Break into shorter sentences'})
        passed = len(found_issues) == 0
        if not passed:
            parts = [f'[{i["category"]}] "{i["phrase"]}" \u2192 {i["suggestion"]}' for i in found_issues]
            details = f"Psychology framing issues: {'; '.join(parts)}"
        else:
            details = "Email uses psychologically sound framing"
        return {'check_name': 'Psychological Framing', 'passed': passed, 'details': details}

    def check_grammar_formality(self, text):
        """Check for casual contractions inappropriate for formal banking letters."""
        found_issues = []
        for pattern, formal_form in self.GRAMMAR_ISSUES:
            matches = re.findall(pattern, text)
            if matches:
                found_issues.append(f'"{matches[0]}" \u2192 use "{formal_form}"')
        passed = len(found_issues) == 0
        details = f"Grammar formality issues: {'; '.join(found_issues)}" if not passed else "Grammar meets formal banking standards"
        return {'check_name': 'Grammar Formality', 'passed': passed, 'details': details}

    def check_comparison_rate_warning(self, text, decision):
        """Verify comparison rate warning is present when a comparison rate is quoted (National Credit Code Reg 99)."""
        if decision != 'approved':
            return {'check_name': 'Comparison Rate Warning', 'passed': True, 'details': 'Not applicable for denial emails'}
        has_comparison_rate = bool(re.search(r'comparison rate', text.lower()))
        if not has_comparison_rate:
            return {'check_name': 'Comparison Rate Warning', 'passed': True, 'details': 'No comparison rate quoted'}
        has_warning = bool(self.COMPARISON_RATE_WARNING_REQUIRED.search(text))
        details = "Comparison rate warning present (National Credit Code Reg 99)" if has_warning else "Comparison rate quoted WITHOUT mandatory Reg 99 warning"
        return {'check_name': 'Comparison Rate Warning', 'passed': has_warning, 'details': details}

    def check_sign_off_structure(self, text):
        """Ensure a single, professional sign-off is present (no double closings)."""
        # Match sign-off lines: a line whose stripped, comma-stripped content is a sign-off phrase.
        # This avoids double-counting "Kind regards" as both "kind regards" AND "regards".
        sign_off_phrases = {
            'regards', 'kind regards', 'sincerely', 'yours faithfully',
            'best regards', 'warm regards',
        }
        lines = text.split('\n')
        sign_off_count = sum(
            1 for line in lines
            if line.strip().lower().rstrip(',') in sign_off_phrases
        )

        passed = sign_off_count <= 1
        details = (
            f"Multiple sign-offs detected ({sign_off_count})"
            if not passed
            else "Single sign-off structure verified"
        )

        return {
            'check_name': 'Sign-Off Structure',
            'passed': passed,
            'details': details,
        }

    # ── Marketing-specific checks ──────────────────────────────────────
    # These live here so both decision and marketing emails can be checked
    # by a single run_all_checks() call with email_type='decision' or 'marketing'.

    # Marketing-specific AI-giveaway terms — more permissive than the decision
    # email list because product descriptions legitimately use "comprehensive"
    # and "tailored", and customer follow-ups use "don't hesitate".
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
        r'\badditionally\b',
        r'\bfurthermore\b',
        r'\bmoreover\b',
        r'\bin addition\b',
        r'\bconsequently\b',
        r'\bas such\b',
        r'\baccordingly\b',
        r'\bmay potentially\b',
        r'\bcould potentially\b',
        r'\bit is possible that\b',
        r'\bmight be able to\b',
        r'\bwe understand that\b',
        r'\bwe recognise that\b',
        r'\bwe would like to\b',
        r'\bwe would like you to\b',
        r'\bshould you wish to\b',
        r'\bshould you require\b',
        r'\bshould you have any\b',
        r'\bwe wish you\b',
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

    def check_marketing_ai_giveaway_language(self, text):
        """Detect AI-generated phrasing, with marketing-appropriate exceptions."""
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
        return {'check_name': 'AI Giveaway Language', 'passed': passed, 'details': details}

    def check_marketing_format(self, text):
        """Marketing email format — plain text with Unicode bullets and en dashes allowed."""
        formatting_issues = []
        if re.search(r'\*\*[^*]+\*\*', text):
            formatting_issues.append('bold markdown (**text**)')
        if re.search(r'(?<!\w)#{1,6}\s+', text):
            formatting_issues.append('markdown headers (#)')
        if re.search(r'<[a-zA-Z][^>]*>', text):
            formatting_issues.append('HTML tags')
        if re.search(r'\u2014', text):
            formatting_issues.append('em dashes')
        passed = len(formatting_issues) == 0
        details = (
            f"Formatting issues: {', '.join(formatting_issues)}"
            if not passed
            else "Marketing format verified"
        )
        return {'check_name': 'Plain Text Format', 'passed': passed, 'details': details}

    def check_no_decline_language(self, text):
        """Marketing emails must not restate the decline decision."""
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
        return {'check_name': 'No Decline Language', 'passed': passed, 'details': details}

    def check_patronising_language(self, text):
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
        return {'check_name': 'Patronising Language', 'passed': passed, 'details': details}

    def check_no_false_urgency(self, text):
        """Marketing emails must not create false urgency (Banking Code 2025 para 89-91)."""
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
        return {'check_name': 'False Urgency', 'passed': passed, 'details': details}

    def check_no_guaranteed_approval(self, text):
        """Marketing emails must not imply guaranteed approval (ASIC RG 234).

        Exception: "guaranteed returns" is allowed for term deposits (government-backed
        under the Financial Claims Scheme).
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
        return {'check_name': 'No Guaranteed Approval', 'passed': passed, 'details': details}

    def check_has_call_to_action(self, text):
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

    # ── Unified check runner ───────────────────────────────────────────

    def run_all_checks(self, email_text, context, email_type='decision'):
        """Run ALL guardrail checks on any email and return results with a quality score.

        Every check runs on every email type. The only differences:
        - AI Giveaway Language: decision emails use the stricter list,
          marketing emails use the more permissive list (allows "comprehensive", "tailored").
        - Plain Text Format: decision emails block markdown bullets,
          marketing emails allow Unicode dividers and emoji.

        All other checks run identically regardless of email_type.

        Args:
            email_text: The email body text to check.
            context: Dict with 'decision', 'loan_amount', 'pricing', etc.
            email_type: 'decision' or 'marketing' — only affects which variant
                        of AI giveaway and format checks to use.
        """
        decision = context.get('decision', 'approved')

        # Pick the correct variant for checks that differ by email type
        ai_giveaway_fn = (
            self.check_ai_giveaway_language if email_type == 'decision'
            else self.check_marketing_ai_giveaway_language
        )
        format_fn = (
            self.check_plain_text_format if email_type == 'decision'
            else self.check_marketing_format
        )

        checks = [
            # ── Core compliance (critical) ──
            (self.check_prohibited_language, (email_text,), 15),
            (self.check_hallucinated_numbers, (email_text, context), 12),
            (self.check_tone, (email_text,), 8),
            (self.check_professional_financial_language, (email_text,), 6),
            (self.check_required_elements, (email_text, decision, email_type), 10),
            (self.check_comparison_rate_warning, (email_text, decision), 6),
            # ── Customer protection ──
            (self.check_contextual_dignity, (email_text,), 8),
            (self.check_psychological_framing, (email_text, decision), 5),
            # No-decline-language only applies to marketing emails — decision emails
            # SHOULD contain "unable to approve" per Banking Code para 81
            *( [(self.check_no_decline_language, (email_text,), 8)] if email_type == 'marketing' else [] ),
            (self.check_patronising_language, (email_text,), 6),
            (self.check_no_false_urgency, (email_text,), 6),
            (self.check_no_guaranteed_approval, (email_text,), 8),
            # ── Quality & authenticity ──
            (ai_giveaway_fn, (email_text,), 5),
            (self.check_grammar_formality, (email_text,), 3),
            (format_fn, (email_text,), 3),
            (self.check_word_count, (email_text, decision), 3),
            (self.check_sign_off_structure, (email_text,), 2),
            (self.check_has_call_to_action, (email_text,), 5),
            (self.check_sentence_rhythm, (email_text,), 2),
        ]

        results = []
        total_weight = 0
        passed_weight = 0

        for check_fn, args, weight in checks:
            result = check_fn(*args)
            result['weight'] = weight
            results.append(result)
            total_weight += weight
            if result['passed']:
                passed_weight += weight

        quality_score = round((passed_weight / total_weight) * 100) if total_weight > 0 else 0

        for r in results:
            r['quality_score'] = quality_score

        return results

    def compute_quality_score(self, results):
        """Extract the quality score from check results.

        Quality score interpretation:
          100: Perfect — all checks passed
          90-99: Minor issues (formatting, rhythm) — safe to send
          70-89: Moderate issues (AI language, word count) — review recommended
          50-69: Significant issues (missing elements, tone) — retry needed
          0-49: Critical issues (prohibited language, hallucinated numbers) — block
        """
        if not results:
            return 0
        return results[0].get('quality_score', 0)
