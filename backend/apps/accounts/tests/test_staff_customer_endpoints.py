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
    def test_list_excludes_admin_and_officer_rows(
        self, authed_officer_client, admin_user, officer_user, customer_user
    ):
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

    def test_list_search_does_not_leak_admin_email(
        self, authed_officer_client, admin_user, customer_user
    ):
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

    def test_profile_does_not_create_phantom_row_for_admin(
        self, authed_officer_client, admin_user
    ):
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

    def test_activity_customer_target_returns_200(
        self, authed_officer_client, customer_user
    ):
        url = reverse("staff-customer-activity", kwargs={"user_id": customer_user.id})
        response = authed_officer_client.get(url)
        assert response.status_code == 200
