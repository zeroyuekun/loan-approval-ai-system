"""Non-bias referrals apply the model decision and are recorded, not queued.

The human review queue is only for bias flags (owner rule; the review page
filters bias_reports__flagged=True). The predictor still reports *why* a
decision deserves a second look — a borderline probability, severe feature
drift, a credit-policy "refer" rule, a pricing gap on a denial — as
``refer_reasons``. Those used to send the application to REVIEW, where nothing
showed it. Now the model decision is applied, the decision email goes out
through the normal bias-checked pipeline, and each reason is written to the
decision waterfall and the AuditLog so the decision stays explainable.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

ORCH = "apps.agents.services.orchestrator"

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)

REFER_REASONS = [
    {"code": "BORDERLINE", "detail": "Probability 0.5100 is within 0.05 of the 0.5000 threshold"},
    {"code": "POLICY_REFER_P08", "detail": "LTI above 7x"},
]


def _prediction_with_referrals():
    return {
        "prediction": "approved",
        "probability": 0.51,
        "model_version": None,
        "feature_importances": {"credit_score": 0.35, "annual_income": 0.25},
        "shap_values": {},
        "processing_time_ms": 42,
        "refer_reasons": REFER_REASONS,
    }


@pytest.fixture
def application(django_user_model):
    from apps.loans.models import LoanApplication

    customer = django_user_model.objects.create_user(
        username="refer_customer",
        email="refer_customer@test.com",
        password="testpass123",
        role="customer",
        first_name="Refer",
        last_name="Customer",
    )
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
        status="pending",
    )


@CACHE_OVERRIDE
@pytest.mark.django_db
def test_refer_reasons_apply_the_model_decision_and_are_recorded(application):
    from apps.loans.models import AuditLog, LoanDecision

    mock_predictor = MagicMock()
    mock_predictor.predict.return_value = _prediction_with_referrals()

    with (
        patch(f"{ORCH}.ModelPredictor", return_value=mock_predictor),
        patch(f"{ORCH}.EmailPipelineService") as email_pipeline_cls,
    ):
        email_pipeline = email_pipeline_cls.return_value
        email_pipeline.run.side_effect = lambda app, run, ctx, pred, decision, steps, waterfall: (
            steps,
            {"sent": True},
            MagicMock(),
            {"flagged": False, "score": 10},
            False,
        )

        from apps.agents.services.orchestrator import PipelineOrchestrator

        run = PipelineOrchestrator().orchestrate(application.pk)

    application.refresh_from_db()
    assert application.status == "approved"
    assert run.status == "completed"
    # The decision email went through the normal (bias-checked) pipeline.
    email_pipeline.run.assert_called_once()
    assert email_pipeline.run.call_args.args[4] == "approved"

    waterfall = LoanDecision.objects.get(application=application).decision_waterfall
    referral_entries = [e for e in waterfall if e["step"] == "referral"]
    assert [e["reason_code"] for e in referral_entries] == ["BORDERLINE", "POLICY_REFER_P08"]
    assert referral_entries[0]["detail"] == REFER_REASONS[0]["detail"]

    log = AuditLog.objects.get(resource_id=str(application.pk), action="decision_referral_recorded")
    assert log.details["refer_reasons"] == REFER_REASONS
    assert log.details["decision"] == "approved"

    assert not AuditLog.objects.filter(
        resource_id=str(application.pk), action="status_transition", details__to_status="review"
    ).exists()
