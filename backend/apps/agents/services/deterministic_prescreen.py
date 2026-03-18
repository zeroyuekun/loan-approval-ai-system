import re

from apps.email_engine.services.guardrails import GuardrailChecker


class DeterministicBiasPreScreen:
    """Pure-Python pre-screening that runs regex guardrails before LLM analysis.

    Produces a deterministic score component and a ceiling for the LLM score.
    When all regex checks pass, the LLM cannot push the composite score above
    the BIAS_THRESHOLD_PASS, eliminating false-positive escalations.
    """

    def __init__(self):
        self.checker = GuardrailChecker()

    def prescreen_decision_email(self, email_text, context):
        """Pre-screen a loan decision email using deterministic regex checks.

        Returns:
            dict with deterministic_score, findings, all_clean, max_llm_score
        """
        findings = []
        score = 0

        result = self.checker.check_prohibited_language(email_text)
        if not result['passed']:
            score += 50
            findings.append(result)

        result = self.checker.check_tone(email_text)
        if not result['passed']:
            score += 20
            findings.append(result)

        result = self.checker.check_professional_financial_language(email_text)
        if not result['passed']:
            score += 15
            findings.append(result)

        result = self.checker.check_ai_giveaway_language(email_text)
        if not result['passed']:
            score += 5
            findings.append(result)

        return {
            'deterministic_score': min(score, 100),
            'findings': findings,
            'all_clean': len(findings) == 0,
            'max_llm_score': 40 if len(findings) == 0 else 100,
        }

    def prescreen_marketing_email(self, email_text, context):
        """Pre-screen a marketing email using deterministic regex checks.

        Uses the same base checks plus marketing-specific patterns for
        decline language, patronising language, false urgency, and
        guaranteed approval claims.
        """
        findings = []
        score = 0

        # Base checks
        result = self.checker.check_prohibited_language(email_text)
        if not result['passed']:
            score += 50
            findings.append(result)

        result = self.checker.check_tone(email_text)
        if not result['passed']:
            score += 15
            findings.append(result)

        result = self.checker.check_professional_financial_language(email_text)
        if not result['passed']:
            score += 15
            findings.append(result)

        # Marketing-specific checks using regex patterns from MarketingAgent
        text_lower = email_text.lower()

        # Decline language in marketing emails
        decline_patterns = [
            r'\b(declined|denied|rejected|unsuccessful|turned down)\b',
            r'\b(unable to approve|cannot approve|could not approve)\b',
        ]
        decline_found = []
        for pattern in decline_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                decline_found.extend(matches)
        if decline_found:
            score += 20
            findings.append({
                'check_name': 'decline_language',
                'passed': False,
                'details': f"Decline references found: {', '.join(str(d) for d in decline_found)}",
            })

        # Patronising language
        patronising_patterns = [
            r'\bwe know this is hard\b',
            r"\bdon't worry\b",
            r'\bkeep your chin up\b',
            r"\bthis isn't the end\b",
            r'\bwe understand how you feel\b',
        ]
        patronising_found = []
        for pattern in patronising_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                patronising_found.extend(matches)
        if patronising_found:
            score += 10
            findings.append({
                'check_name': 'patronising_language',
                'passed': False,
                'details': f"Patronising language found: {', '.join(patronising_found)}",
            })

        # False urgency
        urgency_patterns = [
            r'\blimited time\b',
            r'\bact now\b',
            r'\boffer expires\b',
            r'\block in now\b',
            r'\blast chance\b',
        ]
        urgency_found = []
        for pattern in urgency_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                urgency_found.extend(matches)
        if urgency_found:
            score += 15
            findings.append({
                'check_name': 'false_urgency',
                'passed': False,
                'details': f"False urgency found: {', '.join(urgency_found)}",
            })

        # Guaranteed approval
        guarantee_patterns = [
            r'\bguaranteed\s+(?:approval|to\s+be\s+approved)\b',
            r'\b100%\s+(?:approval|chance|certain)\b',
            r'\bpre[- ]?approved\b',
            r'\binstant\s+approval\b',
        ]
        guarantee_found = []
        for pattern in guarantee_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                guarantee_found.extend(matches)
        if guarantee_found:
            score += 20
            findings.append({
                'check_name': 'guaranteed_approval',
                'passed': False,
                'details': f"Guaranteed approval language found: {', '.join(guarantee_found)}",
            })

        return {
            'deterministic_score': min(score, 100),
            'findings': findings,
            'all_clean': len(findings) == 0,
            'max_llm_score': 40 if len(findings) == 0 else 100,
        }
