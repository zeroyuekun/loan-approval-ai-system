"""I7 — the Django admin is not a second write path around the state machine,
the audit chain and the overturn gate.

- LoanApplication.status and the LoanDecision record were editable in the
  admin, skipping transition_to / AuditLog.
- DecisionReview's mark_overturned action called apply_review_outcome
  directly; DECISION_OVERTURN_GATE_MODE was evaluated only in the API view.
- The admin actions caught only ValueError, so the four-eyes PermissionDenied
  aborted the batch mid-way.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.loans.models import AuditLog, DecisionReview, LoanApplication, LoanDecision

pytestmark = pytest.mark.django_db

EMAIL = "apps.loans.services.decision_review._send_approval_email"


@pytest.fixture
def admin_user(django_user_model):
    """A superuser: Django admin permission checks pass for it, so a
    view-only assertion is not satisfied vacuously by missing model perms."""
    return django_user_model.objects.create_superuser(
        username="admin_site_root", password="x", email="root@x.com", role="admin"
    )


def _admin_request(user):
    request = RequestFactory().post("/admin/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _denied_with_review(django_user_model, suffix, amount):
    cust = django_user_model.objects.create_user(
        username=f"adm_cust_{suffix}", password="x", role="customer", email=f"adm_cust_{suffix}@x.com"
    )
    app = LoanApplication.objects.create(
        applicant=cust,
        annual_income=Decimal("80000"),
        credit_score=500,
        loan_amount=Decimal(amount),
        debt_to_income=Decimal("5"),
        employment_length=2,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        status="denied",
    )
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    return DecisionReview.objects.create(application=app, requested_by=cust, reason="disagree")


def test_overturn_gate_is_enforced_in_the_service(django_user_model, settings, admin_user):
    from apps.loans.services.decision_review import OverturnGateBlocked, apply_review_outcome

    settings.DECISION_OVERTURN_GATE_MODE = "second_approver"
    settings.DECISION_OVERTURN_THRESHOLD = 100000.0
    review = _denied_with_review(django_user_model, "svc", 1_000_000)

    with patch(EMAIL) as email, pytest.raises(OverturnGateBlocked):
        apply_review_outcome(review, officer=admin_user, outcome="overturned", note="")

    email.assert_not_called()
    review.refresh_from_db()
    assert review.status == DecisionReview.Status.REQUESTED
    assert LoanDecision.objects.get(application_id=review.application_id).decision == "denied"


def test_admin_bulk_overturn_respects_the_gate_and_finishes_the_batch(django_user_model, settings, admin_user):
    settings.DECISION_OVERTURN_GATE_MODE = "second_approver"
    settings.DECISION_OVERTURN_THRESHOLD = 100000.0
    big = _denied_with_review(django_user_model, "big", 1_000_000)
    small = _denied_with_review(django_user_model, "small", 20_000)
    model_admin = site._registry[DecisionReview]

    with patch(EMAIL):
        model_admin.mark_overturned(
            _admin_request(admin_user), DecisionReview.objects.filter(pk__in=[big.pk, small.pk])
        )

    big.refresh_from_db()
    small.refresh_from_db()
    assert big.status == DecisionReview.Status.REQUESTED  # blocked by the gate
    assert small.status == DecisionReview.Status.OVERTURNED  # batch carried on


def test_admin_action_four_eyes_refusal_does_not_abort_the_batch(django_user_model, admin_user):
    first = _denied_with_review(django_user_model, "4e1", 20_000)
    second = _denied_with_review(django_user_model, "4e2", 20_000)
    model_admin = site._registry[DecisionReview]
    from apps.loans.services import decision_review as svc

    real = svc.apply_review_outcome

    def _four_eyes_on_first(review, **kwargs):
        if review.pk == first.pk:
            raise PermissionDenied("four-eyes")
        return real(review, **kwargs)

    with patch("apps.loans.admin.apply_review_outcome", side_effect=_four_eyes_on_first), patch(EMAIL):
        model_admin.mark_upheld(_admin_request(admin_user), DecisionReview.objects.filter(pk__in=[first.pk, second.pk]))

    second.refresh_from_db()
    assert second.status == DecisionReview.Status.UPHELD


def test_application_status_and_decision_inputs_are_read_only_in_admin(sample_application, admin_user):
    model_admin = site._registry[LoanApplication]
    request = _admin_request(admin_user)
    pending_ro = set(model_admin.get_readonly_fields(request, sample_application))
    assert "status" in pending_ro
    assert "loan_amount" not in pending_ro  # inputs editable before assessment

    LoanApplication.objects.filter(pk=sample_application.pk).update(status="approved")
    sample_application.refresh_from_db()
    decided_ro = set(model_admin.get_readonly_fields(request, sample_application))
    assert {"status", "loan_amount", "annual_income", "credit_score"} <= decided_ro


def test_loan_decision_is_view_only_in_admin(sample_application, admin_user):
    decision = LoanDecision.objects.create(application=sample_application, decision="denied", confidence=0.3)
    model_admin = site._registry[LoanDecision]
    request = _admin_request(admin_user)
    assert not model_admin.has_change_permission(request, decision)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_delete_permission(request, decision)


def test_decision_review_outcome_fields_are_read_only_in_admin(django_user_model, admin_user):
    review = _denied_with_review(django_user_model, "ro", 20_000)
    ro = set(site._registry[DecisionReview].get_readonly_fields(_admin_request(admin_user), review))
    assert {"status", "outcome_decision", "assigned_officer", "resolution_note", "resolved_at"} <= ro


def test_admin_edit_of_an_application_is_audited(sample_application, admin_user):
    model_admin = site._registry[LoanApplication]
    sample_application.notes = "edited in admin"
    form = type("F", (), {"changed_data": ["notes"]})()
    model_admin.save_model(_admin_request(admin_user), sample_application, form, change=True)
    entry = AuditLog.objects.get(action="loan_updated", resource_id=str(sample_application.pk))
    assert entry.details["changed_fields"] == ["notes"]
    assert entry.details["source"] == "django_admin"
