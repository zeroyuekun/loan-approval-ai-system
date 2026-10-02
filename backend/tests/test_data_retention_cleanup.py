"""I8 — the 7-year PII de-identification runs, is complete, keys on loan
closure, and is idempotent.

- Not scheduled: the weekly beat task ran only enforce_retention.
- Incomplete: DOB, incomes, suburb/postcode, previous address and employer,
  username, loan-application free text and decision-email bodies survived.
- Over-broad: eligibility keyed on account/application creation, so a
  customer 8 years into a 25-year home loan was scrubbed while it was live.
- Not idempotent: de-identified users were re-selected and re-audited.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.fields import EncryptedCharField
from apps.accounts.models import CustomerProfile, CustomUser
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import AuditLog, LoanApplication

YEARS = 365


def _customer(username, years_ago):
    user = CustomUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="x",
        role="customer",
        first_name="Jane",
        last_name="Citizen",
        phone="0400000001",
    )
    CustomUser.objects.filter(pk=user.pk).update(created_at=timezone.now() - timedelta(days=years_ago * YEARS))
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    for name, value in {
        "date_of_birth": "1980-02-03",
        "phone": "0400111222",
        "address_line_1": "1 Example St",
        "address_line_2": "Unit 2",
        "suburb": "Parramatta",
        "postcode": "2150",
        "state": "NSW",
        "primary_id_number": "DL123456",
        "secondary_id_number": "MC987654",
        "employer_name": "Acme Pty Ltd",
        "occupation": "Engineer",
        "previous_employer": "Old Co",
        "previous_suburb": "Penrith",
        "previous_state": "NSW",
        "previous_postcode": "2750",
        "gross_annual_income": "85000",
        "other_income": "1200",
        "partner_annual_income": "60000",
        "other_income_source": "Tutoring",
    }.items():
        setattr(profile, name, value)
    profile.save()
    return user


def _application(user, *, status, years_ago, term_months=36):
    app = LoanApplication.objects.create(
        applicant=user,
        annual_income=Decimal("85000"),
        credit_score=700,
        loan_amount=Decimal("400000"),
        loan_term_months=term_months,
        debt_to_income=Decimal("3"),
        employment_length=5,
        purpose="home",
        home_ownership="mortgage",
        has_cosigner=False,
        status=status,
        notes="Customer mentioned her daughter's school in Parramatta",
    )
    when = timezone.now() - timedelta(days=years_ago * YEARS)
    LoanApplication.objects.filter(pk=app.pk).update(created_at=when, updated_at=when)
    GeneratedEmail.objects.create(
        application=app,
        decision="denied" if status == "denied" else "approved",
        subject="Your loan decision, Jane",
        body="Dear Jane Citizen, ...",
        prompt_used="p",
        passed_guardrails=True,
    )
    return app


@pytest.mark.django_db
def test_eligible_customer_is_fully_deidentified():
    user = _customer("closed_denied", years_ago=9)
    app = _application(user, status="denied", years_ago=8)

    call_command("data_retention_cleanup", stdout=StringIO())

    user.refresh_from_db()
    assert not user.is_active
    assert "closed_denied" not in user.username
    assert user.first_name in ("", "REDACTED") and user.last_name == "" and user.phone == ""
    assert user.email.endswith("@deidentified.local")

    profile = CustomerProfile.objects.get(user=user)
    encrypted = [f.name for f in CustomerProfile._meta.concrete_fields if isinstance(f, EncryptedCharField)]
    for name in encrypted:
        assert getattr(profile, name) in ("", "REDACTED", "0"), name
    for name in (
        "suburb",
        "postcode",
        "occupation",
        "previous_employer",
        "previous_suburb",
        "previous_state",
        "previous_postcode",
        "other_income_source",
    ):
        assert getattr(profile, name) == "", name

    app.refresh_from_db()
    assert app.notes == ""
    email = GeneratedEmail.objects.get(application=app)
    assert "Jane" not in email.body and "Jane" not in email.subject


@pytest.mark.django_db
def test_customer_with_a_live_long_loan_is_not_touched():
    """Approved 8 years ago on a 25-year term: the loan runs until year 25."""
    user = _customer("live_mortgage", years_ago=9)
    _application(user, status="approved", years_ago=8, term_months=300)

    call_command("data_retention_cleanup", stdout=StringIO())

    user.refresh_from_db()
    assert user.is_active
    assert user.first_name == "Jane"
    assert CustomerProfile.objects.get(user=user).suburb == "Parramatta"


@pytest.mark.django_db
def test_closure_of_an_approved_loan_counts_from_its_term_end():
    """Approved 12 years ago on a 3-year term: closed 9 years ago -> eligible."""
    user = _customer("repaid_loan", years_ago=13)
    _application(user, status="approved", years_ago=12, term_months=36)
    call_command("data_retention_cleanup", stdout=StringIO())
    user.refresh_from_db()
    assert not user.is_active


@pytest.mark.django_db
def test_cleanup_is_idempotent():
    user = _customer("twice", years_ago=9)
    _application(user, status="denied", years_ago=8)
    call_command("data_retention_cleanup", stdout=StringIO())
    call_command("data_retention_cleanup", stdout=StringIO())
    assert AuditLog.objects.filter(action="data_retention_cleanup", resource_id=str(user.pk)).count() == 1


@pytest.mark.django_db
def test_weekly_retention_task_runs_the_deidentification():
    from apps.loans.tasks import enforce_data_retention
    from config.celery import app

    scheduled = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert "apps.loans.tasks.enforce_data_retention" in scheduled

    with patch("django.core.management.call_command") as cmd:
        enforce_data_retention()
    called = [c.args[0] for c in cmd.call_args_list]
    assert "enforce_retention" in called
    assert "data_retention_cleanup" in called


# --- 2026-10-02 review: gaps left after I8 ---------------------------------


@pytest.mark.django_db
def test_free_text_tied_to_the_customer_is_scrubbed():
    """Complaints, review requests, offers, pipeline steps, bias analysis and
    guardrail details all carried the customer's own words or name."""
    from apps.agents.models import AgentRun, BiasReport, NextBestOffer
    from apps.email_engine.models import GuardrailLog
    from apps.loans.models import Complaint, DecisionReview

    user = _customer("free_text", years_ago=9)
    app = _application(user, status="denied", years_ago=8)
    email = GeneratedEmail.objects.get(application=app)
    complaint = Complaint.objects.create(
        complainant=user,
        loan_application=app,
        category="decision",
        subject="Jane disputes the decision",
        description="My daughter's school is in Parramatta",
        resolution="Called Jane on 0400111222",
    )
    review = DecisionReview.objects.create(
        application=app, requested_by=user, reason="Jane's income was wrong", resolution_note="Spoke to Jane"
    )
    run = AgentRun.objects.create(
        application=app,
        status="completed",
        steps=[{"step_name": "email_generation", "status": "completed", "result_summary": {"subject": "Hi Jane"}}],
    )
    offer = NextBestOffer.objects.create(
        agent_run=run,
        application=app,
        analysis="Jane Citizen is a teacher",
        personalized_message="Dear Jane",
        marketing_message="Jane, here are your options",
    )
    bias = BiasReport.objects.create(agent_run=run, email=email, bias_score=10, analysis="Mentions Jane", flagged=False)
    guardrail = GuardrailLog.objects.create(email=email, check_name="tone", passed=True, details="Dear Jane Citizen")

    call_command("data_retention_cleanup", stdout=StringIO())

    complaint.refresh_from_db()
    review.refresh_from_db()
    run.refresh_from_db()
    offer.refresh_from_db()
    bias.refresh_from_db()
    guardrail.refresh_from_db()
    texts = [
        complaint.subject,
        complaint.description,
        complaint.resolution,
        review.reason,
        review.resolution_note,
        str(run.steps),
        offer.analysis,
        offer.personalized_message,
        offer.marketing_message,
        bias.analysis,
        guardrail.details,
    ]
    assert not [t for t in texts if "Jane" in t or "Parramatta" in t or "0400111222" in t]
    # Operational facts stay for analytics.
    assert run.steps[0]["step_name"] == "email_generation"
    assert complaint.category == "decision"


@pytest.mark.django_db
def test_a_customer_cannot_opt_out_by_using_the_deidentified_email_domain():
    user = _customer("opt_out", years_ago=9)
    _application(user, status="denied", years_ago=8)
    CustomUser.objects.filter(pk=user.pk).update(email="me@deidentified.local")

    call_command("data_retention_cleanup", stdout=StringIO())

    user.refresh_from_db()
    assert not user.is_active
    assert AuditLog.objects.filter(action="data_retention_cleanup", resource_id=str(user.pk)).exists()


@pytest.mark.django_db
def test_signing_in_keeps_an_active_customer_out_of_deidentification():
    """Nothing set last_login, so a weekly user with an old closed loan was scrubbed."""
    from rest_framework.test import APIClient

    user = _customer("weekly_user", years_ago=9)
    _application(user, status="denied", years_ago=8)

    resp = APIClient().post("/api/v1/auth/login/", {"username": "weekly_user", "password": "x"}, format="json")
    assert resp.status_code == 200, resp.data

    call_command("data_retention_cleanup", stdout=StringIO())

    user.refresh_from_db()
    assert user.is_active
    assert user.first_name == "Jane"


@pytest.mark.django_db
def test_a_token_refresh_records_activity():
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    user = _customer("refresh_user", years_ago=9)
    stale = timezone.now() - timedelta(days=8 * YEARS)
    CustomUser.objects.filter(pk=user.pk).update(last_login=stale)

    resp = APIClient().post("/api/v1/auth/refresh/", {"refresh": str(RefreshToken.for_user(user))}, format="json")
    assert resp.status_code == 200, resp.data

    user.refresh_from_db()
    assert user.last_login > timezone.now() - timedelta(minutes=5)
