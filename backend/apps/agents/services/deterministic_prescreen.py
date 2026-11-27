import re

from apps.email_engine.services.guardrails import GuardrailChecker

# Marketing-specific regex checks: (check_name, score weight, details label, patterns).
# Patterns run against the lower-cased email text.
_MARKETING_CHECKS = (
    (
        "decline_language",
        20,
        "Decline references found",
        (
            r"\b(declined|denied|rejected|unsuccessful|turned down)\b",
            r"\b(unable to approve|cannot approve|could not approve)\b",
        ),
    ),
    (
        "patronising_language",
        10,
        "Patronising language found",
        (
            r"\bwe know this is hard\b",
            r"\bdon't worry\b",
            r"\bkeep your chin up\b",
            r"\bthis isn't the end\b",
            r"\bwe understand how you feel\b",
        ),
    ),
    (
        "false_urgency",
        15,
        "False urgency found",
        (
            r"\blimited time\b",
            r"\bact now\b",
            r"\boffer expires\b",
            r"\block in now\b",
            r"\blast chance\b",
        ),
    ),
    (
        "guaranteed_approval",
        20,
        "Guaranteed approval language found",
        (
            r"\bguaranteed\s+(?:approval|to\s+be\s+approved)\b",
            r"\b100%\s+(?:approval|chance|certain)\b",
            r"\bpre[- ]?approved\b",
            r"\binstant\s+approval\b",
        ),
    ),
)


# Age wording and labels that describe the person instead of the application.
# The shared PROHIBITED_TERMS list misses these ("As a young applicant you lack
# the maturity..." scored 0). Kept bias-only, so the email guardrails are unchanged.
_AGE_OR_LABELLING_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\btoo\s+(?:young|old)\b",
        r"\b(?:young|old|older|elderly)\s+(?:applicant|borrower|customer|person)s?\b",
        r"\black(?:s|ing)?\s+(?:the\s+)?maturity\b",
        r"\black\s+of\s+maturity\b",
        r"\byou(?:\s+are|['’]re)\s+(?:unemployed|jobless|(?:a\s+)?high[- ]risk|not\s+creditworthy|irresponsible|unreliable)\b",
        r"\byou\s+(?:cannot|can\s+not|can['’]t)\s+afford\b",
        r"\byour\s+poor\s+credit\b",
    )
)


def _check_age_or_labelling(email_text):
    found = [match.group(0) for pattern in _AGE_OR_LABELLING_PATTERNS for match in pattern.finditer(email_text)]
    return {
        "check_name": "Age Or Labelling Language",
        "passed": not found,
        "details": f"Age wording or a label on the person: {', '.join(found)}" if found else "None found",
    }


class DeterministicBiasPreScreen:
    """Pure-Python pre-screening that runs regex guardrails before LLM analysis.

    Produces a deterministic score component and a ceiling for the LLM score.
    When all regex checks pass, the LLM cannot push the composite score above
    the BIAS_THRESHOLD_PASS, eliminating false-positive escalations.
    """

    def __init__(self):
        self.checker = GuardrailChecker()

    @staticmethod
    def _run_guardrail_checks(email_text, weighted_checks, score, findings):
        """Run (GuardrailChecker method, weight) pairs; add the weight per failed check."""
        for check, weight in weighted_checks:
            result = check(email_text)
            if not result["passed"]:
                score += weight
                findings.append(result)
        return score

    @staticmethod
    def _result(score, findings):
        return {
            "deterministic_score": min(score, 100),
            "findings": findings,
            "all_clean": len(findings) == 0,
            "max_llm_score": 40 if len(findings) == 0 else 100,
        }

    def prescreen_decision_email(self, email_text, context):
        """Pre-screen a loan decision email using deterministic regex checks.

        Returns:
            dict with deterministic_score, findings, all_clean, max_llm_score
        """
        findings = []
        score = self._run_guardrail_checks(
            email_text,
            (
                (self.checker.check_prohibited_language, 50),
                (self.checker.check_tone, 20),
                (self.checker.check_professional_financial_language, 15),
                (self.checker.check_ai_giveaway_language, 5),
                # Moderate weight: the LLM judges these in context.
                (_check_age_or_labelling, 40),
            ),
            0,
            findings,
        )
        return self._result(score, findings)

    def prescreen_marketing_email(self, email_text, context):
        """Pre-screen a marketing email using deterministic regex checks.

        Uses the same base checks plus marketing-specific patterns for
        decline language, patronising language, false urgency, and
        guaranteed approval claims.
        """
        findings = []
        score = self._run_guardrail_checks(
            email_text,
            (
                (self.checker.check_prohibited_language, 50),
                (self.checker.check_tone, 15),
                (self.checker.check_professional_financial_language, 15),
            ),
            0,
            findings,
        )

        text_lower = email_text.lower()
        for check_name, weight, label, patterns in _MARKETING_CHECKS:
            found = [match for pattern in patterns for match in re.findall(pattern, text_lower)]
            if found:
                score += weight
                findings.append(
                    {
                        "check_name": check_name,
                        "passed": False,
                        "details": f"{label}: {', '.join(found)}",
                    }
                )

        return self._result(score, findings)
