"""Unit tests for email_engine.lifecycle.send_application_received."""

from decimal import Decimal

import pytest
from django.core import mail

from apps.accounts.models import CustomUser
from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services.lifecycle import send_application_received
from apps.loans.models import LoanApplication


@pytest.fixture
def application(db, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST_USER = "tests@example.test"
    settings.EMAIL_HOST_PASSWORD = "test-password"
    settings.DEFAULT_FROM_EMAIL = "noreply@example.test"
    mail.outbox.clear()

    user = CustomUser.objects.create_user(
        username="lifecycle_test",
        email="lifecycle@example.test",
        password="x",
        first_name="Alex",
    )
    return LoanApplication.objects.create(
        applicant=user,
        annual_income=Decimal("80000.00"),
        credit_score=720,
        loan_amount=Decimal("75000.00"),
        debt_to_income=Decimal("3.50"),
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
    )


def test_creates_generated_email_record(application):
    email = send_application_received(application)
    assert isinstance(email, GeneratedEmail)
    assert email.application_id == application.id
    assert email.decision == "pending"
    assert email.prompt_used == "lifecycle_template:received"
    assert email.passed_guardrails is True
    assert email.model_used == "template"


def test_subject_includes_purpose_and_ref_code(application):
    email = send_application_received(application)
    assert "Personal" in email.subject
    assert "Ref #" in email.subject


def test_body_includes_loan_amount(application):
    email = send_application_received(application)
    assert "$75,000.00" in email.body


def test_body_addresses_applicant_by_first_name(application):
    email = send_application_received(application)
    assert "Dear Alex" in email.body


def test_falls_back_to_username_when_no_first_name(db, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST_USER = "tests@example.test"
    settings.EMAIL_HOST_PASSWORD = "test-password"
    mail.outbox.clear()

    user = CustomUser.objects.create_user(
        username="no_name_user",
        email="noname@example.test",
        password="x",
    )
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=Decimal("60000.00"),
        credit_score=700,
        loan_amount=Decimal("10000.00"),
        debt_to_income=Decimal("2.00"),
        employment_length=3,
        purpose="personal",
        home_ownership="rent",
    )
    email = send_application_received(app)
    assert "Dear no_name_user" in email.body


def test_sends_email_when_applicant_has_email(application):
    send_application_received(application)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [application.applicant.email]


def test_skips_send_when_applicant_email_blank(db, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.EMAIL_HOST_USER = "tests@example.test"
    settings.EMAIL_HOST_PASSWORD = "test-password"
    mail.outbox.clear()

    user = CustomUser.objects.create_user(username="no_email", password="x")
    user.email = ""
    user.save()
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=Decimal("50000.00"),
        credit_score=680,
        loan_amount=Decimal("5000.00"),
        debt_to_income=Decimal("2.00"),
        employment_length=2,
        purpose="personal",
        home_ownership="rent",
    )

    email = send_application_received(app)
    assert isinstance(email, GeneratedEmail)
    assert len(mail.outbox) == 0
