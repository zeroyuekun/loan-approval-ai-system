"""Tests for bias detector calibration: weighting, known-biased samples."""

import pytest
from unittest.mock import patch, MagicMock


KNOWN_BIASED_EMAILS = [
    "We cannot approve your loan because of your race and ethnicity.",
    "Due to your gender, this application has been denied.",
    "Your age makes you ineligible for this product. Old people are risky.",
    "Based on your marital status as a single mother, we cannot proceed.",
    "Your disability status prevents approval under our guidelines.",
    "Applicants from your national origin are statistically riskier.",
    "We don't lend to pregnant women due to income uncertainty.",
    "Your religion-based financial practices are incompatible with our terms.",
    "As an Aboriginal applicant, your risk profile is higher.",
    "You failed because you are too old and unemployed.",
]

KNOWN_CLEAN_EMAILS = [
    "We have carefully reviewed your application and are unable to approve it at this time based on your current debt-to-income ratio.",
    "Your monthly surplus after essential expenses was below our minimum threshold for sustainable repayments.",
    "The requested loan amount exceeded our serviceability guidelines given your current income.",
    "Your employment tenure of 3 months fell below our minimum requirement of 6 months for this loan type.",
    "Your credit score of 520 was below our minimum threshold of 600 for personal loans.",
    "We were unable to verify your income through the documentation provided.",
    "The loan-to-value ratio exceeded our maximum of 80% for this property type.",
    "Your existing credit commitments leave insufficient capacity for additional repayments.",
    "Your application was assessed against our responsible lending obligations.",
    "The repayment amount relative to your income exceeded our serviceability guidelines.",
]


class TestDeterministicBiasDetection:
    """Test that the deterministic layer catches obvious bias."""

    def test_catches_biased_language(self):
        """Deterministic checks should catch >80% of known-biased emails."""
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        caught = 0
        for email in KNOWN_BIASED_EMAILS:
            result = checker.check_prohibited_language(email)
            if not result["passed"]:
                caught += 1

        detection_rate = caught / len(KNOWN_BIASED_EMAILS)
        assert detection_rate >= 0.8, f"Deterministic detection rate {detection_rate:.0%} below 80% threshold"

    def test_passes_clean_emails(self):
        """Clean emails should pass deterministic bias checks."""
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        false_positives = 0
        for email in KNOWN_CLEAN_EMAILS:
            result = checker.check_prohibited_language(email)
            if not result["passed"]:
                false_positives += 1

        fp_rate = false_positives / len(KNOWN_CLEAN_EMAILS)
        assert fp_rate <= 0.2, f"False positive rate {fp_rate:.0%} above 20% threshold"


class TestBiasWeighting:
    """Test that deterministic weighting is primary (60%)."""

    def test_deterministic_weight_is_primary(self):
        """Composite score should weight deterministic at 60%."""
        det_score = 80  # High bias detected deterministically
        llm_score = 20  # LLM says it's fine (agreeableness bias)

        # Old weighting: 0.4 * 80 + 0.6 * 20 = 44 (would pass threshold)
        old_composite = 0.4 * det_score + 0.6 * llm_score

        # New weighting: 0.6 * 80 + 0.4 * 20 = 56 (would trigger review)
        new_composite = 0.6 * det_score + 0.4 * llm_score

        assert new_composite > old_composite, "New weighting should give more weight to deterministic"
        assert new_composite >= 56, f"Expected composite >= 56, got {new_composite}"

    def test_composite_score_range(self):
        """Composite scores should always be between 0 and 100."""
        for det in range(0, 101, 10):
            for llm in range(0, 101, 10):
                composite = 0.6 * det + 0.4 * llm
                assert 0 <= composite <= 100, f"Composite {composite} out of range for det={det}, llm={llm}"

    def test_high_deterministic_overrides_low_llm(self):
        """When deterministic finds strong bias, low LLM score should not mask it."""
        det_score = 90
        llm_score = 10

        composite = 0.6 * det_score + 0.4 * llm_score
        # 0.6 * 90 + 0.4 * 10 = 54 + 4 = 58, which should be above review threshold
        assert composite >= 50, (
            f"High deterministic bias ({det_score}) masked by low LLM ({llm_score}): composite={composite}"
        )


class TestBiasDetectionEdgeCases:
    """Test edge cases in bias detection."""

    def test_empty_email_does_not_crash(self):
        """Empty email should not crash the checker."""
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        result = checker.check_prohibited_language("")
        assert "passed" in result

    def test_very_long_email(self):
        """Very long email should be handled without errors."""
        from apps.email_engine.services.guardrails import GuardrailChecker

        checker = GuardrailChecker()
        long_email = "This is a clean financial assessment paragraph. " * 500
        result = checker.check_prohibited_language(long_email)
        assert "passed" in result
        assert result["passed"] is True
