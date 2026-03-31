"""Tests verifying guardrail regex patterns are pre-compiled for performance."""

import re

from apps.email_engine.services.guardrails import GuardrailChecker

checker = GuardrailChecker()


class TestRegexCompilation:
    """Verify all patterns are compiled re.Pattern objects, not raw strings."""

    def test_prohibited_terms_are_compiled(self):
        for i, pattern in enumerate(checker.PROHIBITED_TERMS):
            assert isinstance(pattern, re.Pattern), f"PROHIBITED_TERMS[{i}] is {type(pattern).__name__}, not re.Pattern"

    def test_aggressive_terms_are_compiled(self):
        for i, pattern in enumerate(checker.AGGRESSIVE_TERMS):
            assert isinstance(pattern, re.Pattern), f"AGGRESSIVE_TERMS[{i}] is {type(pattern).__name__}, not re.Pattern"

    def test_ai_giveaway_terms_are_compiled(self):
        for i, pattern in enumerate(checker.AI_GIVEAWAY_TERMS):
            assert isinstance(pattern, re.Pattern), (
                f"AI_GIVEAWAY_TERMS[{i}] is {type(pattern).__name__}, not re.Pattern"
            )

    def test_unprofessional_financial_terms_are_compiled(self):
        for i, pattern in enumerate(checker.UNPROFESSIONAL_FINANCIAL_TERMS):
            assert isinstance(pattern, re.Pattern), (
                f"UNPROFESSIONAL_FINANCIAL_TERMS[{i}] is {type(pattern).__name__}, not re.Pattern"
            )

    def test_dignity_violations_are_compiled(self):
        for i, (pattern, _alt, _note) in enumerate(checker.DIGNITY_VIOLATIONS):
            assert isinstance(pattern, re.Pattern), (
                f"DIGNITY_VIOLATIONS[{i}] pattern is {type(pattern).__name__}, not re.Pattern"
            )

    def test_psychology_reframes_are_compiled(self):
        for category, patterns in checker.PSYCHOLOGY_REFRAMES.items():
            for i, (pattern, _suggestion, _research) in enumerate(patterns):
                assert isinstance(pattern, re.Pattern), (
                    f"PSYCHOLOGY_REFRAMES['{category}'][{i}] pattern is {type(pattern).__name__}, not re.Pattern"
                )

    def test_grammar_issues_are_compiled(self):
        for i, (pattern, _formal) in enumerate(checker.GRAMMAR_ISSUES):
            assert isinstance(pattern, re.Pattern), (
                f"GRAMMAR_ISSUES[{i}] pattern is {type(pattern).__name__}, not re.Pattern"
            )

    def test_marketing_ai_giveaway_terms_are_compiled(self):
        for i, pattern in enumerate(checker.MARKETING_AI_GIVEAWAY_TERMS):
            assert isinstance(pattern, re.Pattern), (
                f"MARKETING_AI_GIVEAWAY_TERMS[{i}] is {type(pattern).__name__}, not re.Pattern"
            )


class TestRegexFlags:
    """Verify patterns include IGNORECASE flag."""

    def test_prohibited_terms_have_ignorecase(self):
        for pattern in checker.PROHIBITED_TERMS:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"

    def test_aggressive_terms_have_ignorecase(self):
        for pattern in checker.AGGRESSIVE_TERMS:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"

    def test_ai_giveaway_terms_have_ignorecase(self):
        for pattern in checker.AI_GIVEAWAY_TERMS:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"

    def test_unprofessional_financial_terms_have_ignorecase(self):
        for pattern in checker.UNPROFESSIONAL_FINANCIAL_TERMS:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"

    def test_dignity_violations_have_ignorecase(self):
        for pattern, _alt, _note in checker.DIGNITY_VIOLATIONS:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"

    def test_psychology_reframes_have_ignorecase(self):
        for category, patterns in checker.PSYCHOLOGY_REFRAMES.items():
            for pattern, _suggestion, _research in patterns:
                assert pattern.flags & re.IGNORECASE, (
                    f"Pattern {pattern.pattern} in '{category}' missing IGNORECASE flag"
                )

    def test_grammar_issues_have_ignorecase(self):
        for pattern, _formal in checker.GRAMMAR_ISSUES:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"

    def test_marketing_ai_giveaway_terms_have_ignorecase(self):
        for pattern in checker.MARKETING_AI_GIVEAWAY_TERMS:
            assert pattern.flags & re.IGNORECASE, f"Pattern {pattern.pattern} missing IGNORECASE flag"


class TestRegexFunctionality:
    """Verify compiled patterns still match correctly (no behavior change)."""

    def test_prohibited_racial_term_detected(self):
        text = "We reject applicants based on race"
        matches = []
        for pattern in checker.PROHIBITED_TERMS:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_clean_text_passes(self):
        text = "Your loan application has been approved based on your financial profile."
        matches = []
        for pattern in checker.PROHIBITED_TERMS:
            matches.extend(pattern.findall(text))
        assert len(matches) == 0

    def test_aggressive_term_detected(self):
        text = "You are stupid for applying"
        matches = []
        for pattern in checker.AGGRESSIVE_TERMS:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_ai_giveaway_detected(self):
        text = "We are delighted to inform you additionally that we would like to empower you"
        matches = []
        for pattern in checker.AI_GIVEAWAY_TERMS:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_unprofessional_term_detected(self):
        text = "You have guaranteed approval with no questions asked"
        matches = []
        for pattern in checker.UNPROFESSIONAL_FINANCIAL_TERMS:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_dignity_violation_detected(self):
        text = "you have no job and you cannot afford this loan"
        matches = []
        for pattern, _alt, _note in checker.DIGNITY_VIOLATIONS:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_grammar_issue_detected(self):
        text = "You can't apply for this loan and we won't reconsider"
        matches = []
        for pattern, _formal in checker.GRAMMAR_ISSUES:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_marketing_ai_giveaway_detected(self):
        text = "We are delighted to share this journey with you additionally"
        matches = []
        for pattern in checker.MARKETING_AI_GIVEAWAY_TERMS:
            matches.extend(pattern.findall(text))
        assert len(matches) > 0

    def test_full_check_prohibited_language(self):
        """End-to-end: check_prohibited_language still works with compiled patterns."""
        result = checker.check_prohibited_language("We deny loans based on race and religion")
        assert not result["passed"]
        assert "race" in result["details"].lower() or "religion" in result["details"].lower()

    def test_full_check_clean_email(self):
        """End-to-end: clean email passes prohibited language check."""
        result = checker.check_prohibited_language(
            "Your loan application has been approved. Please review the terms and conditions."
        )
        assert result["passed"]

    def test_full_check_tone(self):
        """End-to-end: check_tone still works with compiled patterns."""
        result = checker.check_tone("You are stupid and incompetent")
        assert not result["passed"]

    def test_full_check_ai_giveaway(self):
        """End-to-end: check_ai_giveaway_language still works with compiled patterns."""
        result = checker.check_ai_giveaway_language("We are delighted to empower you")
        assert not result["passed"]

    def test_full_check_dignity(self):
        """End-to-end: check_contextual_dignity still works with compiled patterns."""
        result = checker.check_contextual_dignity("you have no job")
        assert not result["passed"]

    def test_full_check_grammar(self):
        """End-to-end: check_grammar_formality still works with compiled patterns."""
        result = checker.check_grammar_formality("You can't do that and we won't help")
        assert not result["passed"]
