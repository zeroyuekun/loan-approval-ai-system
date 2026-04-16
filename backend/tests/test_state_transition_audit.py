"""Regression test — every AI-pipeline status transition must produce
an AuditLog(action="status_transition") entry. Protects against the
F-01/F-02/F-03 pattern where raw ORM `.update(status=...)` bypasses
`LoanApplication.transition_to()` and the audit trail it writes.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.models import CustomUser
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import AuditLog, LoanApplication


@pytest.fixture
def audit_user(db):
    return CustomUser.objects.create_user(
        username="audit_test",
        email="audit-test@example.com",
        password="testpass123",
        role="customer",
        first_name="Audit",
        last_name="Test",
    )


@pytest.fixture
def pending_application(db, audit_user):
    return LoanApplication.objects.create(
        applicant=audit_user,
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


@pytest.mark.django_db
def test_orchestrator_ml_failure_writes_transition_auditlog(pending_application):
    """Forcing ML prediction to fail routes the app to REVIEW — that
    processing→review transition must produce an AuditLog row."""
    baseline_transitions = AuditLog.objects.filter(
        resource_type="LoanApplication",
        resource_id=str(pending_application.id),
        action="status_transition",
    ).count()

    with patch(
        "apps.agents.services.orchestrator.ModelPredictor",
    ) as mock_predictor_cls:
        mock_predictor = mock_predictor_cls.return_value
        mock_predictor.predict.side_effect = ConnectionError("forced ML failure")
        PipelineOrchestrator().orchestrate(pending_application.id)

    pending_application.refresh_from_db()
    assert pending_application.status == LoanApplication.Status.REVIEW

    new_transitions = AuditLog.objects.filter(
        resource_type="LoanApplication",
        resource_id=str(pending_application.id),
        action="status_transition",
    ).order_by("timestamp")
    # Expected: pending→processing (line 141) + processing→review (ML fail handler) = 2
    new_count = new_transitions.count() - baseline_transitions
    assert new_count == 2, (
        f"Expected 2 new status_transition AuditLog rows (pending→processing, processing→review); got {new_count}"
    )
    last = new_transitions.last()
    assert last.details.get("from_status") == "processing"
    assert last.details.get("to_status") == "review"
    assert last.details.get("source") == "orchestrator_ml_prediction_failure"


@pytest.mark.django_db
def test_raw_update_pattern_absent_from_agents_services():
    """Static guard — no agents/services file may use raw `.update(status=...)`
    on LoanApplication. Every final-decision transition must go through
    `LoanApplication.transition_to()` so the AuditLog row is written."""
    from pathlib import Path

    services_dir = Path(__file__).resolve().parents[1] / "apps" / "agents" / "services"
    offenders = []
    for py in services_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        # Only flag updates against LoanApplication; AgentRun status updates
        # are unrelated and valid (see orchestrator.py:139 stale-pipeline reset).
        if "LoanApplication.objects.filter(pk=" in text and ".update(status=" in text:
            offenders.append(py.name)
    assert not offenders, (
        f"Raw .update(status=...) pattern found in {offenders}. "
        f"Use application.transition_to(...) instead to preserve the AuditLog trail."
    )
