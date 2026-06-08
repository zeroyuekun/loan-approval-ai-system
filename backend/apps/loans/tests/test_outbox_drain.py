"""L23 — outbox row deleted only after the application leaves PENDING.

`.delay()` not raising does NOT prove the broker durably enqueued the task
(many transports silently drop). The drain loop must only delete the durable
outbox row once the application has demonstrably transitioned QUEUE_FAILED ->
PENDING; otherwise it keeps the row (and increments attempts) so the exhausted
alert can still fire. We also assert the fail-fast broker transport options.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _make_application(django_user_model, *, status, suffix=""):
    customer = django_user_model.objects.create_user(
        username=f"l23_customer{suffix}",
        email=f"l23_customer{suffix}@test.com",
        password="testpass123",
        role="customer",
        first_name="L23",
        last_name="Customer",
    )
    from apps.loans.models import LoanApplication

    return LoanApplication.objects.create(
        applicant=customer,
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
        status=status,
    )


@pytest.mark.django_db
def test_row_kept_when_app_did_not_leave_pending(monkeypatch, django_user_model):
    from apps.agents import tasks as agent_tasks
    from apps.loans.models import LoanApplication, PipelineDispatchOutbox
    from apps.loans.tasks import retry_failed_dispatches

    # App is NOT in QUEUE_FAILED (already PENDING), so the guarded conditional
    # update will match 0 rows even though .delay() "succeeds".
    app = _make_application(django_user_model, status=LoanApplication.Status.PENDING, suffix="_kept")
    outbox = PipelineDispatchOutbox.objects.create(application=app, attempts=0)

    monkeypatch.setattr(agent_tasks.orchestrate_pipeline_task, "delay", MagicMock())

    result = retry_failed_dispatches()

    assert PipelineDispatchOutbox.objects.filter(pk=outbox.pk).exists()  # row survives
    outbox.refresh_from_db()
    assert outbox.attempts == 1  # incremented so exhausted alert can fire
    assert result["recovered"] == 0
    assert result["failed"] == 1


@pytest.mark.django_db
def test_row_deleted_on_successful_transition(monkeypatch, django_user_model):
    from apps.agents import tasks as agent_tasks
    from apps.loans.models import LoanApplication, PipelineDispatchOutbox
    from apps.loans.tasks import retry_failed_dispatches

    app = _make_application(django_user_model, status=LoanApplication.Status.QUEUE_FAILED, suffix="_recovered")
    outbox = PipelineDispatchOutbox.objects.create(application=app, attempts=0)

    monkeypatch.setattr(agent_tasks.orchestrate_pipeline_task, "delay", MagicMock())

    result = retry_failed_dispatches()

    app.refresh_from_db()
    assert app.status == LoanApplication.Status.PENDING
    assert not PipelineDispatchOutbox.objects.filter(pk=outbox.pk).exists()  # row gone
    assert result["recovered"] == 1


def test_broker_transport_options_fail_fast():
    from config.celery import app

    opts = app.conf.broker_transport_options
    assert opts.get("socket_connect_timeout") == 5
    assert opts.get("retry_on_timeout") is False
