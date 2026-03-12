import re


class GuardrailChecker:
    """Checks generated emails for compliance and quality issues."""

    PROHIBITED_TERMS = [
        # Discriminatory language patterns
        r'\b(race|racial|ethnicity|ethnic)\b',
        r'\b(religion|religious|church|mosque|synagogue|temple)\b',
        r'\b(gender|sex|male|female|transgender)\b',
        r'\b(pregnant|pregnancy|maternity)\b',
        r'\b(disability|disabled|handicap)\b',
        r'\b(national origin|nationality|immigrant|alien)\b',
        r'\b(marital status|married|divorced|single|widowed)\b',
        r'\bage\b(?!\s*(of|action|notice))',  # "age" but not "age of" or "age action notice"
    ]

    AGGRESSIVE_TERMS = [
        r'\b(stupid|idiot|foolish|incompetent)\b',
        r'\b(demand|insist|must immediately)\b',
        r'\b(threat|threaten|consequences)\b',
        r'\b(never|always)\s+(will|should|can)\b',
    ]

    def check_prohibited_language(self, text):
        """Check for discriminatory terms in the email."""
        text_lower = text.lower()
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
        issues = []

        # Extract dollar amounts from the email
        dollar_pattern = r'\$[\d,]+(?:\.\d{2})?'
        found_amounts = re.findall(dollar_pattern, text)

        # Convert context amounts for comparison
        valid_amounts = set()
        if 'loan_amount' in context:
            amount = float(context['loan_amount'])
            valid_amounts.add(f"${amount:,.2f}")
            valid_amounts.add(f"${amount:,.0f}")
            valid_amounts.add(f"${int(amount):,}")

        for amount in found_amounts:
            cleaned = amount.replace(',', '').replace('$', '')
            try:
                val = float(cleaned)
                # Check if this amount is close to any known valid amount
                is_valid = any(
                    abs(val - float(str(va).replace(',', '').replace('$', ''))) < 1.0
                    for va in valid_amounts
                ) if valid_amounts else True

                if not is_valid:
                    issues.append(f"Unrecognized amount: {amount}")
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

    def check_required_elements(self, text, decision):
        """Check that required elements are present based on decision type."""
        text_lower = text.lower()
        missing = []

        if decision == 'approved':
            if 'next step' not in text_lower and 'next steps' not in text_lower:
                missing.append('next steps')
            if 'approved' not in text_lower and 'approval' not in text_lower:
                missing.append('approval confirmation')
        elif decision == 'denied':
            if 'adverse action' not in text_lower and 'reason' not in text_lower:
                missing.append('adverse action notice or reasons')
            if 'right' not in text_lower and 'credit report' not in text_lower:
                missing.append('credit report rights notice')

        passed = len(missing) == 0
        details = f"Missing required elements: {', '.join(missing)}" if not passed else "All required elements present"

        return {
            'check_name': 'required_elements',
            'passed': passed,
            'details': details,
        }

    def run_all_checks(self, email_text, context):
        """Run all guardrail checks and return results."""
        decision = context.get('decision', 'approved')

        results = [
            self.check_prohibited_language(email_text),
            self.check_hallucinated_numbers(email_text, context),
            self.check_tone(email_text),
            self.check_required_elements(email_text, decision),
        ]

        return results
