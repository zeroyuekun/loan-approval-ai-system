"""L16: idempotent status-restore via the audited state machine.

The completed-run branch of orchestrate_pipeline_task previously wrote
app.status directly with save(update_fields=["status"]), bypassing
ALLOWED_TRANSITIONS and producing no status_transition AuditLog. This moves
that logic into PipelineOrchestrator.restore_status_from_decision and routes
it through transition_to so it is validated and audited.
"""

import pytest

from apps.agents.models import AgentRun
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import AuditLog, LoanApplication, LoanDecision

pytestmark = pytest.mark.django_db


def _make_app(customer, status="pending"):
    return LoanApplication.objects.create(
        applicant=customer,
        annual_income=90000,
        loan_amount=300000,
        loan_term_months=360,
        credit_score=720,
        employment_length=5,
        debt_to_income=0.25,
        purpose="home",
        home_ownership="rent",
        has_cosigner=False,
        status=status,
    )


@pytest.fixture
def customer(django_user_model):
    return django_user_model.objects.create_user(
        username="restore_customer",
        email="restore@example.com",
        password="x",
        role="customer",
    )


def _completed_run(app):
    return AgentRun.objects.create(application=app, status=AgentRun.Status.COMPLETED, steps=[])


def test_restore_sets_status_from_decision_when_pending(customer):
    app = _make_app(customer, status="pending")
    _completed_run(app)
    LoanDecision.objects.create(application=app, decision="approved", confidence=0.9)

    PipelineOrchestrator().restore_status_from_decision(app.id)

    app.refresh_from_db()
    assert app.status == "approved"


def test_restore_writes_status_transition_audit(customer):
    app = _make_app(customer, status="pending")
    _completed_run(app)
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.4)

    PipelineOrchestrator().restore_status_from_decision(app.id)

    app.refresh_from_db()
    assert app.status == "denied"
    audits = AuditLog.objects.filter(
        action="status_transition",
        resource_type="LoanApplication",
        resource_id=str(app.id),
    )
    # State machine wrote at least one audited transition ending at the decision.
    assert audits.exists()
    assert any(a.details.get("to_status") == "denied" for a in audits)


def test_restore_noops_when_not_pending(customer):
    app = _make_app(customer, status="approved")
    _completed_run(app)
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.4)

    PipelineOrchestrator().restore_status_from_decision(app.id)

    app.refresh_from_db()
    assert app.status == "approved"  # unchanged
    assert not AuditLog.objects.filter(action="status_transition", resource_id=str(app.id)).exists()


def test_restore_noops_when_no_decision(customer):
    app = _make_app(customer, status="pending")
    _completed_run(app)
    # no LoanDecision created

    # Must not raise.
    PipelineOrchestrator().restore_status_from_decision(app.id)

    app.refresh_from_db()
    assert app.status == "pending"  # unchanged


def test_non_force_rerun_ignores_a_completed_run_a_later_failed_run_superseded(customer):
    """An older completed run (approved) and a newer failed run that had already
    overwritten the decision (denied) before the fail-safe bias hold returned
    the application to PENDING. A non-force re-run must run the pipeline, not
    replay the failed run's decision."""
    from datetime import timedelta
    from unittest.mock import patch

    from django.test import override_settings
    from django.utils import timezone

    from apps.agents.tasks import orchestrate_pipeline_task

    app = _make_app(customer, status="pending")
    older = _completed_run(app)
    AgentRun.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(hours=1))
    failed = AgentRun.objects.create(application=app, status=AgentRun.Status.FAILED, steps=[])
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.4)

    with (
        override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}),
        patch.object(PipelineOrchestrator, "orchestrate", return_value=failed) as orchestrate,
    ):
        orchestrate_pipeline_task.apply(args=(str(app.id),))

    app.refresh_from_db()
    assert app.status != "denied", "the failed run's decision was applied without a pipeline run"
    orchestrate.assert_called_once()
