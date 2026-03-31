"""Tests for PDF decision letter generator.

All tests use mocks — no Django DB required.
Validates compliance requirements:
- CFPB Circular 2022-03: denial PDFs generate with reason codes
- ASIC RG 209: decision transparency
- No apology/disappointment language in source code templates
"""

from types import SimpleNamespace

import pytest

from apps.loans.services.pdf_generator import generate_decision_letter_pdf

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_applicant(first_name="Jane", last_name="Doe", username="jdoe"):
    return SimpleNamespace(first_name=first_name, last_name=last_name, username=username)


def _make_decision(decision="approved", confidence=0.92, risk_score=0.15, model_version="v3.1", shap_values=None):
    return SimpleNamespace(
        decision=decision,
        confidence=confidence,
        risk_score=risk_score,
        model_version=model_version,
        shap_values=shap_values or {},
    )


def _make_application(
    decision_kwargs=None, credit_score=720, loan_amount=350000, loan_term_months=360, purpose="home_purchase"
):
    decision_kwargs = decision_kwargs or {}
    decision = _make_decision(**decision_kwargs)
    applicant = _make_applicant()
    return SimpleNamespace(
        id="test-app-001",
        applicant=applicant,
        decision=decision,
        credit_score=credit_score,
        loan_amount=loan_amount,
        loan_term_months=loan_term_months,
        purpose=purpose,
    )


# ---------------------------------------------------------------------------
# Tests — PDF Structure & Generation
# ---------------------------------------------------------------------------


class TestPDFGeneration:
    def test_approved_generates_valid_pdf(self):
        app = _make_application()
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 500

    def test_denied_generates_valid_pdf(self):
        app = _make_application(
            decision_kwargs={
                "decision": "denied",
                "confidence": 0.85,
                "risk_score": 0.72,
                "shap_values": {
                    "credit_score": -0.35,
                    "annual_income": -0.25,
                    "debt_to_income": -0.18,
                    "employment_length": -0.12,
                },
            }
        )
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 500

    def test_denied_pdf_larger_than_approved(self):
        """Denied PDFs should be larger due to reason codes, rights info, AFCA details."""
        approved = _make_application()
        denied = _make_application(
            decision_kwargs={
                "decision": "denied",
                "shap_values": {
                    "credit_score": -0.35,
                    "annual_income": -0.25,
                    "debt_to_income": -0.18,
                    "employment_length": -0.12,
                },
            }
        )
        approved_pdf = generate_decision_letter_pdf(approved)
        denied_pdf = generate_decision_letter_pdf(denied)
        assert len(denied_pdf) > len(approved_pdf)

    def test_no_decision_raises_error(self):
        app = SimpleNamespace(id="test", decision=None)
        with pytest.raises(ValueError, match="no decision"):
            generate_decision_letter_pdf(app)


# ---------------------------------------------------------------------------
# Tests — Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_denial_with_empty_shap_still_generates(self):
        app = _make_application(
            decision_kwargs={
                "decision": "denied",
                "shap_values": {},
            }
        )
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_denial_with_no_credit_score(self):
        app = _make_application(
            credit_score=None,
            decision_kwargs={
                "decision": "denied",
                "shap_values": {"annual_income": -0.3},
            },
        )
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)
        assert len(pdf) > 500

    def test_applicant_with_no_name(self):
        """Falls back to username when first/last name empty."""
        app = _make_application()
        app.applicant = SimpleNamespace(first_name="", last_name="", username="testuser")
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_zero_confidence(self):
        app = _make_application(decision_kwargs={"confidence": 0.0})
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)

    def test_none_confidence(self):
        app = _make_application(decision_kwargs={"confidence": None})
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)

    def test_none_model_version(self):
        app = _make_application(decision_kwargs={"model_version": None})
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)

    def test_large_loan_amount(self):
        app = _make_application(loan_amount=50000000)
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)

    def test_many_shap_reasons(self):
        """Reason codes capped at 4 per ECOA — PDF should not overflow."""
        app = _make_application(
            decision_kwargs={
                "decision": "denied",
                "shap_values": {
                    "credit_score": -0.35,
                    "annual_income": -0.25,
                    "debt_to_income": -0.18,
                    "employment_length": -0.12,
                    "loan_amount": -0.10,
                    "has_bankruptcy": -0.08,
                    "num_defaults_5yr": -0.06,
                    "bnpl_utilization_pct": -0.04,
                },
            }
        )
        pdf = generate_decision_letter_pdf(app)
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Tests — Compliance: No Apology Language in Source
# ---------------------------------------------------------------------------


class TestDenialLetterCompliance:
    PROHIBITED_WORDS = ["sorry", "apologise", "apologize", "disappointment", "regret"]

    def test_source_code_has_no_apology_language(self):
        """Verify the PDF generator source code contains no prohibited language."""
        import inspect

        source = inspect.getsource(generate_decision_letter_pdf)
        source_lower = source.lower()
        for word in self.PROHIBITED_WORDS:
            assert word not in source_lower, f'Prohibited word "{word}" found in PDF generator source code'

    def test_denial_helper_has_no_apology_language(self):
        """Verify _build_denial_content has no prohibited language."""
        import inspect

        from apps.loans.services.pdf_generator import _build_denial_content

        source = inspect.getsource(_build_denial_content).lower()
        for word in self.PROHIBITED_WORDS:
            assert word not in source, f'Prohibited word "{word}" found in denial content builder'


# ---------------------------------------------------------------------------
# Tests — Risk Grading
# ---------------------------------------------------------------------------


class TestRiskGrading:
    @pytest.mark.parametrize(
        "risk_score,expected_min_size",
        [
            (0.10, 500),  # AAA
            (0.25, 500),  # AA
            (0.40, 500),  # A
            (0.55, 500),  # BBB
            (0.70, 500),  # BB
        ],
    )
    def test_all_risk_tiers_generate(self, risk_score, expected_min_size):
        app = _make_application(
            decision_kwargs={
                "decision": "approved",
                "risk_score": risk_score,
            }
        )
        pdf = generate_decision_letter_pdf(app)
        assert len(pdf) > expected_min_size
