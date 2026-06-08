"""H1: the orchestrator must honour the predictor's ``requires_human_review``
flag.

When the ML predictor flags an application for human review (borderline
probability / severe drift / policy "refer"), the orchestrator must escalate to
the human-review queue BEFORE the email pipeline runs — so no automated
decision email is ever generated or sent for these cases.

This test deliberately uses ``prediction="approved"`` so it also proves the
escalation fires for an *approve* (not just a denial) and short-circuits before
the email pipeline / Claude are reached.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

ORCH = "apps.agents.services.orchestrator"

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


def _prediction_requires_review():
    """Prediction dict flagged for human review.

    Includes every key the orchestrator reads BEFORE the escalation point
    (model_version is intentionally None — the FK is nullable).
    """
    return {
        "prediction": "approved",
        "probability": 0.51,
        "model_version": None,
        "feature_importances": {"credit_score": 0.35, "annual_income": 0.25},
        "shap_values": {},
        "processing_time_ms": 42,
        "requires_human_review": True,
    }


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_requires_human_review_escalates_before_emailing(django_user_model):
    from apps.email_engine.models import GeneratedEmail
    from apps.loans.models import LoanApplication

    customer = django_user_model.objects.create_user(
        username="h1_customer",
        email="h1_customer@test.com",
        password="testpass123",
        role="customer",
        first_name="H1",
        last_name="Customer",
    )

    application = LoanApplication.objects.create(
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
        status="pending",
    )

    mock_predictor = MagicMock()
    mock_predictor.predict.return_value = _prediction_requires_review()

    with patch(f"{ORCH}.ModelPredictor") as MockPredictor:
        # The orchestrator constructs ModelPredictor(segment=...) directly, but
        # cover the for_application classmethod path too for robustness.
        MockPredictor.return_value = mock_predictor
        MockPredictor.for_application.return_value = mock_predictor

        from apps.agents.services.orchestrator import PipelineOrchestrator

        run = PipelineOrchestrator().orchestrate(application.pk)

    application.refresh_from_db()

    # Escalated to the human-review queue ...
    assert application.status == "review"
    assert run.status == "escalated"
    # ... and NO automated decision email was generated for this application.
    assert not GeneratedEmail.objects.filter(application=application).exists()
