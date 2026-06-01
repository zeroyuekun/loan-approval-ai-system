from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

HUMAN_REVIEW = "apps.agents.services.human_review_handler"
SENDER = "apps.email_engine.services.sender.send_decision_email"

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


def test_human_involvement_field_defaults_to_none():
    from apps.loans.models import LoanDecision

    field = LoanDecision._meta.get_field("human_involvement")
    assert field.default == "none"
    assert {c[0] for c in field.choices} == {"none", "assisted", "overridden"}


def _email():
    return {
        "subject": "Your Loan Decision",
        "body": "Dear Customer, ...",
        "passed_guardrails": True,
        "template_fallback": False,
        "prompt_used": "test prompt",
        "guardrail_results": [],
        "generation_time_ms": 100,
        "attempt_number": 1,
        "input_tokens": 500,
        "output_tokens": 200,
        "estimated_cost_usd": 0.002,
    }


def _noop_select_for_update(self, **kwargs):
    """Replace select_for_update with a no-op to avoid the PostgreSQL
    "FOR UPDATE cannot be applied to the nullable side of an outer join"
    limitation that the real resume path otherwise hits in tests."""
    return self


@pytest.fixture
def _resume_setup(db):
    """Build a customer, a LoanApplication in 'review', an approved
    LoanDecision (human_involvement defaults to 'none'), and an escalated
    AgentRun — the exact preconditions resume_after_review expects."""
    from apps.accounts.models import CustomUser
    from apps.agents.models import AgentRun
    from apps.loans.models import LoanApplication, LoanDecision

    user = CustomUser.objects.create_user(
        username="h2_customer",
        email="h2_customer@test.com",
        password="testpass123",
        role="customer",
        first_name="H2",
        last_name="Customer",
    )

    application = LoanApplication.objects.create(
        applicant=user,
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
        status="review",
    )

    decision = LoanDecision.objects.create(
        application=application,
        decision="approved",
        confidence=0.85,
    )
    assert decision.human_involvement == LoanDecision.HumanInvolvement.NONE

    run = AgentRun.objects.create(
        application=application,
        status="escalated",
        steps=[{"step_name": "bias_check", "status": "completed"}],
    )

    return run, application


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_resume_stamps_human_involvement_assisted(_resume_setup):
    """When a reviewer resolves an escalation, the persisted LoanDecision is
    stamped human_involvement='assisted' (H2) so the ADM disclosure can
    truthfully report human involvement after status leaves 'review'."""
    run, application = _resume_setup

    with (
        patch(f"{HUMAN_REVIEW}.EmailGenerator") as eg,
        patch(f"{HUMAN_REVIEW}.EmailPersistenceService") as eps,
        patch(SENDER, return_value={"sent": True}),
        patch("django.db.models.QuerySet.select_for_update", _noop_select_for_update),
    ):
        eg.return_value.generate.return_value = _email()
        eps.save_generated_email.return_value = MagicMock(id="e1")
        eps.save_guardrail_logs.return_value = []

        from apps.agents.services.orchestrator import PipelineOrchestrator

        result = PipelineOrchestrator().resume_after_review(run.id, reviewer="officer1", note="ok")

    assert result.status == "completed"

    application.refresh_from_db()
    assert application.status == "approved"
    assert application.decision.human_involvement == "assisted"


@pytest.mark.django_db
def test_overturn_stamps_human_involvement_overridden(django_user_model):
    """When a lending officer OVERTURNS a denial (officer override -> approved),
    the persisted LoanDecision is stamped human_involvement='overridden' (H3) so
    the ADM disclosure truthfully reports mode 'human' ('Reviewed and decided by
    a lending officer.') rather than 'solely automated'."""
    from apps.loans.models import DecisionReview, LoanApplication, LoanDecision
    from apps.loans.services.decision_review import apply_review_outcome
    from apps.ml_engine.services.decision_explanation import build_explanation_from_decision

    customer = django_user_model.objects.create_user(
        username="h3_customer",
        email="h3_customer@test.com",
        password="testpass123",
        role="customer",
        first_name="H3",
        last_name="Customer",
    )
    officer = django_user_model.objects.create_user(
        username="h3_officer",
        email="h3_officer@test.com",
        password="testpass123",
        role="officer",
        first_name="H3",
        last_name="Officer",
    )

    app = LoanApplication.objects.create(
        applicant=customer,
        annual_income=Decimal("50000.00"),
        credit_score=500,
        loan_amount=Decimal("30000.00"),
        loan_term_months=36,
        debt_to_income=Decimal("5.00"),
        employment_length=1,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        status="denied",
    )

    decision = LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    assert decision.human_involvement == LoanDecision.HumanInvolvement.NONE

    review = DecisionReview.objects.create(
        application=app,
        requested_by=customer,
        reason="disagree with the automated denial",
        status=DecisionReview.Status.UNDER_REVIEW,
    )

    # The overturn path generates + sends an approval email after the transaction
    # (best-effort, external). Mock it — the behaviour under test is the stamp +
    # disclosure, not email delivery.
    with patch("apps.loans.services.decision_review._send_approval_email"):
        apply_review_outcome(review, officer=officer, outcome="overturned", note="approved on appeal")

    app.refresh_from_db()
    assert app.status == "approved"
    assert app.decision.decision == "approved"
    assert app.decision.human_involvement == "overridden"

    # End-to-end: the persisted stamp flows through to the ADM disclosure mode.
    explanation = build_explanation_from_decision(app.decision)
    assert explanation["adm_disclosure"]["mode"] == "human"
