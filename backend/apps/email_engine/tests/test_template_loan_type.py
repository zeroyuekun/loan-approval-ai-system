"""Subjects must contain exactly one "Loan": purposes arrive both as enum keys
("personal") and as display-form values ("Personal Loan", "Auto Loan"), and
product names like "Green Loan" carry an integral "Loan"."""

from apps.email_engine.services.template_fallback import (
    _loan_label,
    generate_approval_template,
    generate_denial_template,
)


def test_loan_label_appends_loan_to_bare_types():
    assert _loan_label("personal") == "Personal Loan"
    assert _loan_label("auto") == "Vehicle Loan"


def test_loan_label_keeps_single_loan_for_display_form_and_products():
    assert _loan_label("Personal Loan") == "Personal Loan"
    assert _loan_label("green_loan") == "Green Loan"
    assert _loan_label("Auto Loan") == "Auto Loan"


def test_approval_subject_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    subject = result["subject"]
    assert "Loan Loan" not in subject
    assert subject == "Congratulations! Your Personal Loan is Approved"


def test_approval_body_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    assert "Loan Loan" not in result["body"]


def test_denial_body_has_single_loan_word():
    result = generate_denial_template("Alex Chen", 20000.0, "Personal Loan")
    assert "Loan Loan" not in result["body"]


def test_loan_label_lifecycle_display_form_no_double_loan():
    """_loan_label handles get_purpose_display() output ("Auto Loan", "Personal Loan")
    without producing "Loan Loan".

    Note: send_application_received() in lifecycle.py creates DB records and
    sends email — it cannot be unit-tested without full Django DB + mocking.
    We verify the helper _loan_label directly for lifecycle's consumption pattern.
    """
    # Display-form purposes that get_purpose_display() returns
    assert _loan_label("Auto Loan") == "Auto Loan"
    assert _loan_label("Personal Loan") == "Personal Loan"
    assert _loan_label("Business Loan") == "Business Loan"
    assert _loan_label("Home Loan") == "Home Loan"
    # Bare enum keys still get " Loan" appended
    assert _loan_label("auto") == "Vehicle Loan"
    assert _loan_label("home") == "Home Purchase Loan"
