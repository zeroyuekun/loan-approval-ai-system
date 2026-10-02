"""Django admin write paths that bypassed the audited services (2026-10-02 review).

- ModelVersion: the admin could switch the live model or edit its threshold,
  file path or hash, skipping the activation service's gates, lock and audit.
- PredictionLog, APICallLog (the APP 8 cross-border record) and NextBestOffer
  are evidence of what the pipeline did, like the other view-only records.
- DecisionReview: the bulk "delete selected" action hard-deleted review records.
- LoanApplication deletes and CustomUser changes (role, superuser status,
  password) wrote no AuditLog row into the hash chain.
"""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.agents.models import APICallLog, NextBestOffer
from apps.loans.models import AuditLog, DecisionReview, LoanApplication
from apps.ml_engine.models import ModelVersion, PredictionLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser():
    return CustomUser.objects.create_superuser(username="root_admin", email="root@x.com", password="x", role="admin")


@pytest.fixture
def superuser_request(superuser):
    request = RequestFactory().get("/admin/")
    request.user = superuser
    return request


@pytest.mark.parametrize("model", [ModelVersion, PredictionLog, APICallLog, NextBestOffer])
def test_serving_and_evidence_records_are_view_only(model, superuser_request):
    model_admin = admin.site._registry[model]
    assert model_admin.has_view_permission(superuser_request)
    assert not model_admin.has_add_permission(superuser_request)
    assert not model_admin.has_change_permission(superuser_request)
    assert not model_admin.has_delete_permission(superuser_request)


def test_decision_reviews_cannot_be_deleted_in_the_admin(superuser_request):
    model_admin = admin.site._registry[DecisionReview]
    assert not model_admin.has_delete_permission(superuser_request)
    assert "delete_selected" not in model_admin.get_actions(superuser_request)


def _application(owner):
    return LoanApplication.objects.create(
        applicant=owner,
        annual_income=Decimal("75000.00"),
        credit_score=720,
        loan_amount=Decimal("25000.00"),
        loan_term_months=36,
        debt_to_income=Decimal("1.50"),
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        monthly_expenses=Decimal("2200.00"),
        existing_credit_card_limit=Decimal("8000.00"),
        number_of_dependants=0,
        employment_type="payg_permanent",
        applicant_type="single",
        has_hecs=False,
        has_bankruptcy=False,
        state="NSW",
    )


def test_deleting_an_application_in_the_admin_is_audited(client, superuser):
    customer = CustomUser.objects.create_user(username="cust_del", email="c@x.com", password="x", role="customer")
    application = _application(customer)
    client.force_login(superuser)

    resp = client.post(
        reverse("admin:loans_loanapplication_delete", args=[application.pk]), {"post": "yes"}, follow=False
    )

    assert resp.status_code == 302
    assert not LoanApplication.objects.filter(pk=application.pk).exists()  # soft-deleted
    row = AuditLog.objects.get(action="loan_deleted", resource_id=str(application.pk))
    assert row.user == superuser
    assert row.details["source"] == "django_admin"


def test_bulk_deleting_applications_in_the_admin_audits_each_one(client, superuser):
    customer = CustomUser.objects.create_user(username="cust_bulk", email="b@x.com", password="x", role="customer")
    apps = [_application(customer), _application(customer)]
    client.force_login(superuser)

    resp = client.post(
        reverse("admin:loans_loanapplication_changelist"),
        {"action": "delete_selected", "_selected_action": [str(a.pk) for a in apps], "post": "yes"},
    )

    assert resp.status_code == 302
    audited = set(AuditLog.objects.filter(action="loan_deleted").values_list("resource_id", flat=True))
    assert audited == {str(a.pk) for a in apps}


def test_changing_a_users_role_and_superuser_status_in_the_admin_is_audited(client, superuser):
    officer = CustomUser.objects.create_user(username="off1", email="o@x.com", password="x", role="officer")
    client.force_login(superuser)

    resp = client.post(
        reverse("admin:accounts_customuser_change", args=[officer.pk]),
        {
            "username": "off1",
            "first_name": "",
            "last_name": "",
            "email": "o@x.com",
            "is_active": "on",
            "is_staff": "on",
            "is_superuser": "on",
            "role": "admin",
            "phone": "",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            "initial-date_joined_0": "2026-01-01",
            "initial-date_joined_1": "00:00:00",
        },
    )

    assert resp.status_code == 302, getattr(resp, "context", None) and resp.context["adminform"].form.errors
    row = AuditLog.objects.get(action="user_changed", resource_id=str(officer.pk))
    assert row.user == superuser
    assert row.details["source"] == "django_admin"
    changed = " ".join(row.details["changed"]).lower()
    assert "role" in changed
    assert "superuser" in changed


def test_setting_a_users_password_in_the_admin_is_audited_without_the_hash(client, superuser):
    officer = CustomUser.objects.create_user(username="off2", email="o2@x.com", password="x", role="officer")
    client.force_login(superuser)

    resp = client.post(
        reverse("admin:auth_user_password_change", args=[officer.pk]),
        {"password1": "N3w-Long-Passphrase!", "password2": "N3w-Long-Passphrase!", "usable_password": "true"},
    )

    assert resp.status_code == 302
    row = AuditLog.objects.get(action="user_changed", resource_id=str(officer.pk))
    officer.refresh_from_db()
    assert officer.password not in str(row.details)
    assert "password" in " ".join(row.details["changed"]).lower()
