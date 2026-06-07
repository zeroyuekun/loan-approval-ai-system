"""FIX-1 — TaskStatusView IDOR / task-existence information-leak tests.

A non-staff (customer) user must receive IDENTICAL responses regardless of
whether the task_id:
  (a) does not exist at all,
  (b) exists but belongs to a different user, or
  (c) exists but has no result yet (PENDING).

All three cases must return HTTP 200 with the same PENDING envelope so an
attacker cannot enumerate task IDs by comparing response codes/bodies.

A customer querying their OWN completed task receives the real result.

Staff (admin/officer) retain full visibility.
"""

import json

import pytest
from django_celery_results.models import TaskResult
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication

pytestmark = pytest.mark.django_db

TASK_STATUS_URL = "/api/v1/tasks/{}/status/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(username, role, is_staff=False):
    return CustomUser.objects.create_user(
        username=username,
        email=f"{username}@test.example",
        password="TestPass123!",
        role=role,
        is_staff=is_staff,
    )


def _make_application(user):
    return LoanApplication.objects.create(
        applicant=user,
        annual_income=60000,
        credit_score=700,
        loan_amount=20000,
        loan_term_months=36,
        purpose="personal",
        employment_type="payg_permanent",
        employment_length=3,
        debt_to_income=0.3,
        existing_credit_card_limit=5000,
        home_ownership="rent",
        applicant_type="single",
        number_of_dependants=0,
    )


def _authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _pending_envelope_shape(data, task_id):
    """Assert the response body looks like the safe PENDING envelope."""
    assert data["task_id"] == task_id
    assert data["status"] == "PENDING"
    assert data["result"] is None
    assert data["date_done"] is None
    # No error key leaked
    assert "error" not in data


# ---------------------------------------------------------------------------
# FIX-1 core: indistinguishable PENDING for non-staff
# ---------------------------------------------------------------------------


def test_nonexistent_task_returns_200_pending_for_customer():
    """Non-existent task_id → 200 PENDING (not 404)."""
    customer = _make_user("c_nonexist", "customer")
    client = _authed_client(customer)
    task_id = "00000000-0000-0000-0000-does-not-exist"
    resp = client.get(TASK_STATUS_URL.format(task_id))
    assert resp.status_code == 200
    _pending_envelope_shape(resp.data, task_id)


def test_other_user_task_returns_200_pending_for_customer():
    """Task belonging to another user → 200 PENDING (same as nonexistent)."""
    owner = _make_user("c_owner", "customer")
    spy = _make_user("c_spy", "customer")
    app = _make_application(owner)

    task_id = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    TaskResult.objects.create(
        task_id=task_id,
        status="SUCCESS",
        result=json.dumps({"application_id": str(app.id), "decision": "approved"}),
        content_type="application/json",
        content_encoding="utf-8",
    )

    client = _authed_client(spy)
    resp = client.get(TASK_STATUS_URL.format(task_id))
    assert resp.status_code == 200
    _pending_envelope_shape(resp.data, task_id)


def test_pending_task_returns_200_pending_for_customer():
    """Task that exists but has no result yet → 200 PENDING."""
    customer = _make_user("c_pending", "customer")
    task_id = "bbbb2222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    TaskResult.objects.create(
        task_id=task_id,
        status="PENDING",
        result="",  # empty / no result
        content_type="application/json",
        content_encoding="utf-8",
    )
    client = _authed_client(customer)
    resp = client.get(TASK_STATUS_URL.format(task_id))
    assert resp.status_code == 200
    _pending_envelope_shape(resp.data, task_id)


def test_nonexistent_and_other_user_tasks_are_indistinguishable():
    """The response for a nonexistent task must be IDENTICAL to the response for
    another user's task — same status code, same body, no 403 distinguisher."""
    customer = _make_user("c_probe", "customer")
    other = _make_user("c_other_probe", "customer")
    other_app = _make_application(other)

    task_id_missing = "cccc3333-cccc-cccc-cccc-cccccccccccc"
    task_id_other = "dddd4444-dddd-dddd-dddd-dddddddddddd"
    TaskResult.objects.create(
        task_id=task_id_other,
        status="SUCCESS",
        result=json.dumps({"application_id": str(other_app.id)}),
        content_type="application/json",
        content_encoding="utf-8",
    )

    client = _authed_client(customer)
    resp_missing = client.get(TASK_STATUS_URL.format(task_id_missing))
    resp_other = client.get(TASK_STATUS_URL.format(task_id_other))

    assert resp_missing.status_code == resp_other.status_code == 200
    # Both must return exactly the same envelope shape (status=PENDING)
    assert resp_missing.data["status"] == resp_other.data["status"] == "PENDING"
    assert resp_missing.data["result"] == resp_other.data["result"] is None
    assert resp_missing.data["date_done"] == resp_other.data["date_done"] is None
    # Neither returns 403
    assert "error" not in resp_missing.data
    assert "error" not in resp_other.data


# ---------------------------------------------------------------------------
# FIX-1: legitimate customer polling their OWN completed task → real result
# ---------------------------------------------------------------------------


def test_customer_can_read_own_completed_task():
    """Non-staff gets the real result when the task's application_id belongs to them."""
    customer = _make_user("c_owner2", "customer")
    app = _make_application(customer)

    task_id = "eeee5555-eeee-eeee-eeee-eeeeeeeeeeee"
    result_payload = json.dumps({"application_id": str(app.id), "decision": "approved"})
    TaskResult.objects.create(
        task_id=task_id,
        status="SUCCESS",
        result=result_payload,
        content_type="application/json",
        content_encoding="utf-8",
    )

    client = _authed_client(customer)
    resp = client.get(TASK_STATUS_URL.format(task_id))
    assert resp.status_code == 200
    assert resp.data["status"] == "SUCCESS"
    assert resp.data["result"] is not None
    assert "error" not in resp.data


# ---------------------------------------------------------------------------
# FIX-1: staff always sees real status
# ---------------------------------------------------------------------------


def test_staff_sees_real_status_for_any_task():
    """Staff (admin/officer) always gets the real task status."""
    customer = _make_user("c_for_staff", "customer")
    admin = _make_user("admin_staff", "admin", is_staff=True)
    app = _make_application(customer)

    task_id = "ffff6666-ffff-ffff-ffff-ffffffffffff"
    result_payload = json.dumps({"application_id": str(app.id), "decision": "denied"})
    TaskResult.objects.create(
        task_id=task_id,
        status="SUCCESS",
        result=result_payload,
        content_type="application/json",
        content_encoding="utf-8",
    )

    client = _authed_client(admin)
    resp = client.get(TASK_STATUS_URL.format(task_id))
    assert resp.status_code == 200
    assert resp.data["status"] == "SUCCESS"
    assert resp.data["result"] is not None


def test_staff_nonexistent_task_returns_pending():
    """Staff GET on a non-existent task returns PENDING (not 404)."""
    admin = _make_user("admin_staff2", "admin", is_staff=True)
    task_id = "9999aaaa-9999-9999-9999-999999999999"
    client = _authed_client(admin)
    resp = client.get(TASK_STATUS_URL.format(task_id))
    assert resp.status_code == 200
    assert resp.data["status"] == "PENDING"
