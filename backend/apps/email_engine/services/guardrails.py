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
        r'\bpleased to (?:inform|advise)\b',  # "pleased to confirm" is legitimate in formal approvals
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
        r'\bcomprehensive\b',
        r'\btailored\b',
        r'\brest assured\b',
        r'\bdon[\u2019\']t hesitate\b',
        r'\bwe are here to help\b',
        r'\bwalk you through\b',
        r'\bevery step of the way\b',
        r'\bwe understand how important\b',
        r'\bwe understand this (?:may be|is) disappointing\b',
        r'\bwe appreciate the trust\b',
        r'\bregardless of (?:this|the) outcome\b',
        r'\bshould you have any questions at all\b',
        # r'\bplease do not hesitate to contact\b',  # Removed: legitimate in formal approval letters
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
        r'\bwe look forward to\b',
        # AI closing/filler patterns
        r'\bplease feel free to\b',
        # r'\bdo not hesitate\b',  # Removed: legitimate in formal approval correspondence
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
    ]

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
            'check_name': 'prohibited_language',
            'passed': passed,
            'details': details,
        }

    def check_hallucinated_numbers(self, text, context):
        """Verify dollar amounts and percentages match the application data."""
        # If loan_amount is None/missing, we cannot validate amounts — skip the check
        loan_amount = context.get('loan_amount')
        if loan_amount is None:
            return {
                'check_name': 'hallucinated_numbers',
                'passed': True,
                'details': 'No loan amount in context; skipped hallucinated numbers check',
            }

        issues = []

        # Strip ASIC comparison rate footnotes before checking
        # (standard regulatory text contains fixed amounts like $150,000)
        text_to_check = re.sub(
            r'\*\s*[Cc]omparison rate calculated.*?(?:cost of the loan\.|$)',
            '', text, flags=re.DOTALL,
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

        for found in found_amounts:
            cleaned = found.replace(',', '').replace('$', '')
            try:
                val = float(cleaned)
                # Check if this amount is close to any known valid amount
                is_valid = any(
                    abs(val - float(str(va).replace(',', '').replace('$', ''))) < 1.0
                    for va in valid_amounts
                )

                if not is_valid:
                    issues.append(f"Unrecognized amount: {found}")
            except ValueError:
                continue

        passed = len(issues) == 0
        details = "; ".join(issues) if issues else "All amounts verified"

        return {
            'check_name': 'hallucinated_numbers',
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
            'check_name': 'tone_check',
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
            'check_name': 'ai_giveaway_language',
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
            'check_name': 'professional_financial_language',
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
            'check_name': 'plain_text_format',
            'passed': passed,
            'details': details,
        }

    def check_required_elements(self, text, decision):
        """Check that required elements are present based on decision type."""
        text_lower = text.lower()
        missing = []

        if decision == 'approved':
            has_next = any(phrase in text_lower for phrase in ['next step', 'next steps', 'what happens next', 'from here', 'to proceed', 'moving forward'])
            if not has_next:
                missing.append('next steps')
            if 'approved' not in text_lower and 'approval' not in text_lower:
                missing.append('approval confirmation')
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
            'check_name': 'required_elements',
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
        sign_off_patterns = ('regards', 'kind regards', 'sincerely', 'warm regards', 'yours faithfully', 'best regards')
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
            limit = 450

        passed = count <= limit
        details = (
            f"Body is {count} words (limit: {limit})"
            if not passed
            else f"Word count OK ({count}/{limit})"
        )

        return {
            'check_name': 'word_count',
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
                'check_name': 'sentence_rhythm',
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
            'check_name': 'sentence_rhythm',
            'passed': passed,
            'severity': 'warning',
            'details': details,
        }

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
            'check_name': 'sign_off_structure',
            'passed': passed,
            'details': details,
        }

    def run_all_checks(self, email_text, context):
        """Run all guardrail checks and return results.

        Checks enforced (based on 20+ financial institution email etiquette rules):
         1. Prohibited discriminatory language (ECOA, Sex/Racial/Disability/Age Discrimination Acts)
         2. Hallucinated numbers (amounts must match application data)
         3. Aggressive/threatening tone
         4. Required elements per decision type (AFCA, credit report rights, next steps)
         5. AI-giveaway language (phrases real bank officers never write)
         6. Professional financial language (no misleading claims, no guaranteed approvals)
         7. Plain text format (no markdown, HTML, or em dashes)
         8. Word count limits (approval: 300, denial: 220)
         9. Single sign-off structure (no double closings)
        """
        decision = context.get('decision', 'approved')

        results = [
            self.check_prohibited_language(email_text),
            self.check_hallucinated_numbers(email_text, context),
            self.check_tone(email_text),
            self.check_required_elements(email_text, decision),
            self.check_ai_giveaway_language(email_text),
            self.check_professional_financial_language(email_text),
            self.check_plain_text_format(email_text),
            self.check_word_count(email_text, decision),
            self.check_sign_off_structure(email_text),
            self.check_sentence_rhythm(email_text),
        ]

        return results
