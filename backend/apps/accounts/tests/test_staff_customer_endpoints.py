"""Regression tests for the StaffCustomer* endpoints.

Codex adversarial review (2026-05-07) flagged that the three "staff customer"
endpoints accepted any CustomUser regardless of role, allowing officers to
enumerate admin/officer accounts and even auto-create CustomerProfile rows
attached to staff users. These tests pin the role-scoped behaviour:

    - StaffCustomerListView returns only role='customer' rows
    - StaffCustomerProfileView 404s for non-customer targets and never
      auto-creates a CustomerProfile attached to staff
    - StaffCustomerActivityView 404s for non-customer targets

See docs/superpowers/specs/2026-05-07-codex-adversarial-response-v1-10-7-design.md
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile, CustomUser

# Fixtures are inlined here because backend/tests/conftest.py is not on the
# auto-discovery path for tests under backend/apps/accounts/tests/. Mirroring
# the existing fixtures in backend/tests/conftest.py keeps behaviour aligned
# without forcing a rootdir conftest move.


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return CustomUser.objects.create_user(
        username="admin_test",
        email="admin@test.com",
        password="testpass123",
        role="admin",
        first_name="Admin",
        last_name="User",
        is_staff=True,
    )


@pytest.fixture
def officer_user(db):
    return CustomUser.objects.create_user(
        username="officer_test",
        email="officer@test.com",
        password="testpass123",
        role="officer",
        first_name="Officer",
        last_name="User",
    )


@pytest.fixture
def customer_user(db):
    return CustomUser.objects.create_user(
        username="customer_test",
        email="customer@test.com",
        password="testpass123",
        role="customer",
        first_name="Customer",
        last_name="User",
    )


@pytest.fixture
def authed_officer_client(api_client, officer_user):
    api_client.force_authenticate(user=officer_user)
    return api_client


@pytest.fixture
def second_officer(db):
    return CustomUser.objects.create_user(
        username="second_officer",
        email="other.officer@test.com",
        password="testpass123",
        role="officer",
        first_name="Second",
        last_name="Officer",
    )


@pytest.mark.django_db
class TestStaffCustomerListView:
    def test_list_excludes_admin_and_officer_rows(self, authed_officer_client, admin_user, officer_user, customer_user):
        # Plus a second customer so the response is non-trivial.
        CustomUser.objects.create_user(
            username="customer_two",
            email="customer2@test.com",
            password="testpass123",
            role="customer",
        )

        response = authed_officer_client.get(reverse("staff-customer-list"))

        assert response.status_code == 200
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        usernames = {row["username"] for row in rows}
        assert "admin_test" not in usernames
        assert "officer_test" not in usernames
        assert "customer_test" in usernames
        assert "customer_two" in usernames

    def test_list_search_does_not_leak_admin_email(self, authed_officer_client, admin_user, customer_user):
        # Admin's email contains "admin"; an officer searching "admin" must NOT see it.
        response = authed_officer_client.get(reverse("staff-customer-list") + "?search=admin")

        assert response.status_code == 200
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        emails = {row["email"] for row in rows}
        assert "admin@test.com" not in emails


@pytest.mark.django_db
class TestStaffCustomerProfileView:
    def test_profile_404_for_admin_target(self, authed_officer_client, admin_user):
        url = reverse("staff-customer-profile", kwargs={"user_id": admin_user.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 404

    def test_profile_404_for_officer_target(self, authed_officer_client, second_officer):
        url = reverse("staff-customer-profile", kwargs={"user_id": second_officer.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 404

    def test_profile_does_not_create_phantom_row_for_admin(self, authed_officer_client, admin_user):
        # Pre-condition: no CustomerProfile attached to the admin.
        assert not CustomerProfile.objects.filter(user_id=admin_user.id).exists()

        url = reverse("staff-customer-profile", kwargs={"user_id": admin_user.id})
        response = authed_officer_client.get(url)

        assert response.status_code == 404
        # Post-condition: still no CustomerProfile attached to the admin.
        assert not CustomerProfile.objects.filter(user_id=admin_user.id).exists()

    def test_customer_target_still_works(self, authed_officer_client, customer_user):
        url = reverse("staff-customer-profile", kwargs={"user_id": customer_user.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestStaffCustomerActivityView:
    def test_activity_404_for_admin_target(self, authed_officer_client, admin_user):
        url = reverse("staff-customer-activity", kwargs={"user_id": admin_user.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 404

    def test_activity_404_for_officer_target(self, authed_officer_client, second_officer):
        url = reverse("staff-customer-activity", kwargs={"user_id": second_officer.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 404

    def test_activity_customer_target_returns_200(self, authed_officer_client, customer_user):
        url = reverse("staff-customer-activity", kwargs={"user_id": customer_user.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
def test_activity_returns_raw_text_and_the_full_bias_report(authed_officer_client, customer_user):
    """React escapes text itself: an HTML-escaped subject showed up on screen
    as &#x27; and &amp;. The bias report carries the same fields as the
    agent-run endpoints."""
    from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
    from apps.email_engine.models import GeneratedEmail
    from apps.loans.models import LoanApplication

    application = LoanApplication.objects.create(
        applicant=customer_user,
        annual_income=50000,
        credit_score=700,
        loan_amount=20000,
        debt_to_income=2,
        employment_length=3,
        purpose="personal",
        home_ownership="rent",
    )
    GeneratedEmail.objects.create(
        application=application, decision="approved", subject="Tom's loan & you", body="Hi Tom & co", prompt_used="p"
    )
    run = AgentRun.objects.create(application=application, status="completed", steps=[])
    BiasReport.objects.create(
        agent_run=run, report_type="decision", bias_score=12, deterministic_score=10, score_source="llm", analysis="ok"
    )
    NextBestOffer.objects.create(agent_run=run, application=application, analysis="a")
    MarketingEmail.objects.create(
        agent_run=run, application=application, subject="Rates & offers for O'Brien", body="b", prompt_used="p"
    )

    url = reverse("staff-customer-activity", kwargs={"user_id": customer_user.id})
    data = authed_officer_client.get(url).json()

    assert data["emails"][0]["subject"] == "Tom's loan & you"
    assert data["emails"][0]["body"] == "Hi Tom & co"
    run_data = data["agent_runs"][0]
    assert run_data["marketing_emails"][0]["subject"] == "Rates & offers for O'Brien"
    assert run_data["marketing_emails"][0]["html_body"]
    report = run_data["bias_reports"][0]
    assert {"report_type", "deterministic_score", "score_source"} <= set(report)
    assert report["deterministic_score"] == 10
    assert report["score_source"] == "llm"
    assert run_data["next_best_offers"][0]["analysis"] == "a"


def _activity_queries(customer, count):
    """Queries customer_activity runs for ``count`` emails and runs."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.accounts.services.customer_activity import customer_activity
    from apps.agents.models import AgentRun, BiasReport
    from apps.email_engine.models import GeneratedEmail, GuardrailLog
    from apps.loans.models import LoanApplication

    for _ in range(count):
        application = LoanApplication.objects.create(
            applicant=customer,
            annual_income=50000,
            credit_score=700,
            loan_amount=20000,
            debt_to_income=2,
            employment_length=3,
            purpose="personal",
            home_ownership="rent",
        )
        email = GeneratedEmail.objects.create(
            application=application, decision="approved", subject="s", body="b", prompt_used="p"
        )
        GuardrailLog.objects.create(email=email, check_name="c", passed=True, details="")
        run = AgentRun.objects.create(application=application, status="completed", steps=[])
        BiasReport.objects.create(agent_run=run, report_type="decision", bias_score=1, analysis="ok")
    with CaptureQueriesContext(connection) as queries:
        result = customer_activity(customer)
    assert len(result["emails"]) == len(result["agent_runs"]) == count
    return len(queries)


@pytest.mark.django_db
def test_activity_query_count_does_not_grow_with_the_rows(django_user_model):
    """The sliced querysets keep their prefetches: no query per email or run."""
    one = django_user_model.objects.create_user(username="act_one", password="x", role="customer")
    three = django_user_model.objects.create_user(username="act_three", password="x", role="customer")

    assert _activity_queries(three, 3) == _activity_queries(one, 1)
