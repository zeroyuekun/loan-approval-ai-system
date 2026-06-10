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
    is a hypothetical product-name case.  # noqa: lifecycle.py:46 uses this path.
    """
    assert _loan_label("Personal Loan") == "Personal Loan"
    assert _loan_label("green_loan") == "Green Loan"
    assert _loan_label("Auto Loan") == "Auto Loan"


def test_approval_subject_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    subject = result["subject"]
    assert subject == "Congratulations! Your Personal Loan is Approved"


def test_approval_body_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    assert "Loan Loan" not in result["body"]


def test_denial_body_has_single_loan_word():
    result = generate_denial_template("Alex Chen", 20000.0, "Personal Loan")
    assert "Loan Loan" not in result["body"]


def test_loan_label_lifecycle_body_greeting():
    """_loan_label used in lifecycle.py:46 body greeting must not double "Loan".

    "Auto Loan" is the real get_purpose_display() value; "Personal Loan" is
    a hypothetical display-form value.  Both must produce exactly one "Loan".
    """
    # lifecycle.py:46: f"Thank you for your {_loan_label(purpose)} application …"
    assert _loan_label("Personal Loan") == "Personal Loan"  # → "Personal Loan application"
    assert _loan_label("Auto Loan") == "Auto Loan"  # → "Auto Loan application"
