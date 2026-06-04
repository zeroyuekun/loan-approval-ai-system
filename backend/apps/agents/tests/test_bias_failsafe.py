"""Fail-safe bias-check behaviour (M7 / M10 / L21)."""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.accounts.models import CustomUser
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import LoanApplication

TEST_MV_UUID = uuid.uuid4()


def test_bias_check_unavailable_counter_exists():
    from apps.agents.metrics import bias_check_unavailable_total

    # prometheus_client Counter exposes a _name and labelnames.
    assert bias_check_unavailable_total._name == "bias_check_unavailable"
    assert "mode" in bias_check_unavailable_total._labelnames


def _app(user, **over):
    d = dict(
        applicant=user,
        annual_income=Decimal("85000.00"),
        credit_score=750,
        loan_amount=Decimal("350000.00"),
        loan_term_months=360,
        debt_to_income=Decimal("4.12"),
        employment_length=5,
        purpose="home",
        home_ownership="mortgage",
        has_cosigner=False,
        has_hecs=False,
        has_bankruptcy=False,
        state="NSW",
    )
    d.update(over)
    return LoanApplication.objects.create(**d)


def _pred(prediction="approved", probability=0.85):
    return {
        "prediction": prediction,
        "probability": probability,
        "feature_importances": {"credit_score": 0.25},
        "shap_values": {},
        "model_version": str(TEST_MV_UUID),
        "processing_time_ms": 42,
        "requires_human_review": False,
    }


def _email(passed=True):
    return {
        "subject": "Your Loan Application Decision",
        "body": "Dear Customer, your loan has been processed.",
        "passed_guardrails": passed,
        "guardrail_results": [],
        "template_fallback": False,
        "attempt_number": 1,
    }


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    FIELD_ENCRYPTION_KEY="Q1bXXPr1cYO3Cjd7uP5J8nWRxzdBjQrTAosMayGV3CA=",
)
class BiasFailSafeTestCase(TestCase):
    def setUp(self):
        from django.conf import settings as dj

        from apps.accounts.utils.encryption import clear_fernet_cache
        from apps.ml_engine.models import ModelVersion

        clear_fernet_cache()
        self.user = CustomUser.objects.create_user(
            username="failsafe",
            password="TestPass123!",
            email="fs@test.com",
            role="customer",
        )
        ModelVersion.objects.create(
            id=TEST_MV_UUID,
            algorithm="rf",
            version="failsafe-v1",
            file_path=str(dj.ML_MODELS_DIR / "test_model.joblib"),
            is_active=True,
        )
        self.orch = PipelineOrchestrator()

    def _run(self, app, pred, email):
        from apps.email_engine.models import GeneratedEmail

        mock_pred = MagicMock()
        mock_pred.predict.return_value = pred
        mock_gen = MagicMock()
        mock_gen.generate.return_value = email
        # Bias detector RAISES — genuine infra failure (detector unreachable).
        mock_bias = MagicMock()
        mock_bias.analyze.side_effect = RuntimeError("detector down")
        mock_fraud = MagicMock()
        mock_fraud.run_checks.return_value = {
            "passed": True,
            "risk_score": 0.1,
            "checks": [],
            "flagged_reasons": [],
        }

        ge = GeneratedEmail.objects.create(
            application=app,
            decision="approved",
            subject="T",
            body="B",
            prompt_used="p",
            passed_guardrails=True,
        )
        with (
            patch("apps.agents.services.orchestrator.ModelPredictor", return_value=mock_pred),
            patch("apps.agents.services.email_pipeline.EmailGenerator", return_value=mock_gen),
            patch("apps.agents.services.email_pipeline.EmailPersistenceService") as mp,
            patch("apps.agents.services.email_pipeline.BiasDetector", return_value=mock_bias),
            patch("apps.agents.services.orchestrator.FraudDetectionService", return_value=mock_fraud),
            patch("apps.agents.services.orchestrator.FraudCheck"),
            patch("apps.agents.services.orchestrator.PredictionLog"),
            patch("apps.email_engine.services.sender.send_decision_email", return_value={"sent": True}) as send,
            patch.object(
                PipelineOrchestrator,
                "_run_nbo_and_marketing_pipeline",
                side_effect=lambda a, ar, s, dr, pc: s,
            ),
        ):
            mp.save_generated_email.return_value = ge
            mp.save_guardrail_logs.return_value = None
            run = self.orch.orchestrate(app.pk)
            return run, send

    @override_settings(BIAS_FAILURE_MODE="block")
    def test_block_mode_withholds_email_and_marks_run_failed(self):
        app = _app(self.user)
        run, send = self._run(app, _pred("approved", 0.85), _email(passed=True))

        app.refresh_from_db()
        run.refresh_from_db()
        # Email must NOT be sent — bias detection did not run.
        send.assert_not_called()
        # Decision must NOT be auto-applied; rolled back to PENDING for retry.
        assert app.status == "pending"
        # Run marked for attention.
        assert run.status == "failed"
        assert "bias" in run.error.lower()

    @override_settings(BIAS_FAILURE_MODE="off")
    def test_off_mode_preserves_legacy_failopen(self):
        app = _app(self.user)
        run, send = self._run(app, _pred("approved", 0.85), _email(passed=True))

        app.refresh_from_db()
        run.refresh_from_db()
        # Legacy behaviour: pipeline proceeds and ships the decision email.
        send.assert_called_once()
        assert app.status == "approved"
        assert run.status == "completed"
