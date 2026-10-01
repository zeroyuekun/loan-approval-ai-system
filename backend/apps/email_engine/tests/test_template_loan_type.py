"""Subjects must contain exactly one "Loan": purposes arrive both as enum keys
("personal") and as display-form values ("Auto Loan" — the primary real
get_purpose_display() value ending in Loan), plus hypothetical product names."""

from apps.email_engine.services.template_fallback import (
    _loan_label,
    generate_approval_template,
    generate_denial_template,
)


def test_loan_label_appends_loan_to_bare_types():
    """Bare enum keys get ' Loan' appended; "Business Loan" and "Home Loan" are preserved."""
    assert _loan_label("personal") == "Personal Loan"
    assert _loan_label("auto") == "Vehicle Loan"
    assert _loan_label("home") == "Home Purchase Loan"
    assert _loan_label("Business Loan") == "Business Loan"
    assert _loan_label("Home Loan") == "Home Loan"


def test_loan_label_keeps_single_loan_for_display_form_and_products():
    """Display-form values and product names already ending in 'Loan' are unchanged.

    "Auto Loan" is the primary real get_purpose_display() value; "green_loan"
    is a hypothetical product-name case.
    """
    assert _loan_label("Personal Loan") == "Personal Loan"
    assert _loan_label("green_loan") == "Green Loan"
    assert _loan_label("Auto Loan") == "Auto Loan"


def test_approval_template_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    assert result["subject"] == "Congratulations! Your Personal Loan is Approved"
    assert "Loan Loan" not in result["body"]


def test_denial_body_has_single_loan_word():
    result = generate_denial_template("Alex Chen", 20000.0, "Personal Loan")
    assert "Loan Loan" not in result["body"]
