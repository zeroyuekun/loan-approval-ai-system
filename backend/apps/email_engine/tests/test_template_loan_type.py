"""Subjects must contain exactly one "Loan": purposes arrive both as enum keys
("personal") and as display-form values ("Auto Loan"), plus product names."""

import pytest

from apps.email_engine.services.template_fallback import (
    _loan_label,
    generate_approval_template,
    generate_denial_template,
)


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        # Bare enum keys get " Loan" appended.
        ("personal", "Personal Loan"),
        ("auto", "Vehicle Loan"),
        ("home", "Home Purchase Loan"),
        # Display-form values and product names already ending in "Loan" are unchanged.
        ("Business Loan", "Business Loan"),
        ("Home Loan", "Home Loan"),
        ("Personal Loan", "Personal Loan"),
        ("green_loan", "Green Loan"),
        ("Auto Loan", "Auto Loan"),
    ],
)
def test_loan_label_ends_in_single_loan(purpose, expected):
    assert _loan_label(purpose) == expected


def test_approval_template_has_single_loan_word():
    result = generate_approval_template("Alex Chen", 20000.0, "Personal Loan")
    assert result["subject"] == "Congratulations! Your Personal Loan is Approved"
    assert "Loan Loan" not in result["body"]


def test_denial_body_has_single_loan_word():
    result = generate_denial_template("Alex Chen", 20000.0, "Personal Loan")
    assert "Loan Loan" not in result["body"]
