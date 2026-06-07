"""Fix 3 + Fix 5 — email view API contract tests.

Fix 3: LIST endpoint must NOT include html_body or body (heavy payload).
Fix 5: RETRIEVE endpoint guardrail_checks must include quality_score (matching LIST shape).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.loans.models import LoanApplication


@pytest.fixture
def staff_user(db):
    return CustomUser.objects.create_user(
        username="contract_staff",
        email="contract_staff@test.com",
        password="testpass123",
        role="admin",
        first_name="Staff",
        last_name="User",
    )


@pytest.fixture
def contract_application(db, staff_user):
    return LoanApplication.objects.create(
        applicant=staff_user,
        annual_income=Decimal("80000.00"),
        credit_score=700,
        loan_amount=Decimal("30000.00"),
        loan_term_months=48,
        debt_to_income=Decimal("2.00"),
        employment_length=3,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        monthly_expenses=Decimal("2000.00"),
        existing_credit_card_limit=Decimal("5000.00"),
        number_of_dependants=0,
        employment_type="payg_permanent",
        applicant_type="single",
        has_hecs=False,
        has_bankruptcy=False,
        state="VIC",
    )


@pytest.fixture
def email_with_guardrails(db, contract_application):
    email = GeneratedEmail.objects.create(
        application=contract_application,
        decision="approved",
        subject="Your loan is approved",
        body="Dear Applicant, your loan has been approved.",
        prompt_used="prompt",
        passed_guardrails=True,
    )
    GuardrailLog.objects.create(
        email=email,
        check_name="no_apology_language",
        passed=True,
        details="No apology language found.",
        category="decision",
    )
    return email


@pytest.mark.django_db
def test_list_endpoint_excludes_html_body(email_with_guardrails, staff_user):
    """LIST endpoint must NOT include html_body in any result item (Fix 3)."""
    client = APIClient()
    client.force_authenticate(user=staff_user)

    response = client.get("/api/v1/emails/")
    assert response.status_code == 200

    results = response.data["results"]
    assert len(results) >= 1

    for item in results:
        assert "html_body" not in item, (
            "LIST endpoint must not include html_body — it is KB-scale and causes heavy payloads"
        )


@pytest.mark.django_db
def test_list_endpoint_excludes_body(email_with_guardrails, staff_user):
    """LIST endpoint must NOT include body in any result item (Fix 3)."""
    client = APIClient()
    client.force_authenticate(user=staff_user)

    response = client.get("/api/v1/emails/")
    assert response.status_code == 200

    results = response.data["results"]
    assert len(results) >= 1

    for item in results:
        assert "body" not in item, "LIST endpoint must not include body — it is large and unused by the list view"


@pytest.mark.django_db
def test_retrieve_endpoint_includes_body_and_html_body(email_with_guardrails, staff_user, contract_application):
    """RETRIEVE endpoint must still include body and html_body (Fix 3 — keep in detail view)."""
    client = APIClient()
    client.force_authenticate(user=staff_user)

    response = client.get(f"/api/v1/emails/{contract_application.id}/")
    assert response.status_code == 200
    assert "body" in response.data
    assert "html_body" in response.data
    assert response.data["body"] == "Dear Applicant, your loan has been approved."


@pytest.mark.django_db
def test_retrieve_guardrail_checks_include_quality_score(email_with_guardrails, staff_user, contract_application):
    """RETRIEVE guardrail_checks must include quality_score field (Fix 5)."""
    client = APIClient()
    client.force_authenticate(user=staff_user)

    response = client.get(f"/api/v1/emails/{contract_application.id}/")
    assert response.status_code == 200

    checks = response.data.get("guardrail_checks", [])
    assert len(checks) >= 1

    for check in checks:
        assert "quality_score" in check, (
            "RETRIEVE guardrail_checks must include quality_score to match LIST endpoint shape"
        )


@pytest.mark.django_db
def test_list_guardrail_checks_include_quality_score(email_with_guardrails, staff_user):
    """LIST guardrail_checks must include quality_score field (Fix 5 — parity)."""
    client = APIClient()
    client.force_authenticate(user=staff_user)

    response = client.get("/api/v1/emails/")
    assert response.status_code == 200

    results = response.data["results"]
    assert len(results) >= 1

    for item in results:
        for check in item.get("guardrail_checks", []):
            assert "quality_score" in check, "LIST guardrail_checks must include quality_score"


@pytest.mark.django_db
def test_list_and_retrieve_guardrail_checks_same_keys(email_with_guardrails, staff_user, contract_application):
    """LIST and RETRIEVE guardrail_checks must have the same set of keys."""
    client = APIClient()
    client.force_authenticate(user=staff_user)

    list_resp = client.get("/api/v1/emails/")
    retrieve_resp = client.get(f"/api/v1/emails/{contract_application.id}/")

    assert list_resp.status_code == 200
    assert retrieve_resp.status_code == 200

    list_checks = list_resp.data["results"][0].get("guardrail_checks", [])
    retrieve_checks = retrieve_resp.data.get("guardrail_checks", [])

    assert len(list_checks) >= 1
    assert len(retrieve_checks) >= 1

    list_keys = set(list_checks[0].keys())
    retrieve_keys = set(retrieve_checks[0].keys())

    assert list_keys == retrieve_keys, (
        f"LIST and RETRIEVE guardrail_checks key sets differ. "
        f"LIST-only: {list_keys - retrieve_keys}, RETRIEVE-only: {retrieve_keys - list_keys}"
    )
