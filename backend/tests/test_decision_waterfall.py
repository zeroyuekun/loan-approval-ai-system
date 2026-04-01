"""Tests for the decision waterfall / ASIC RG 209 audit trail.

Verifies that the orchestrator populates LoanDecision.decision_waterfall
with the correct ordered entries at each decision gate.
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.accounts.models import CustomUser
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import LoanApplication, LoanDecision

TEST_MODEL_VERSION_UUID = uuid.uuid4()
TEST_MODEL_VERSION_ID = str(TEST_MODEL_VERSION_UUID)


def _make_application(user, **overrides):
    """Create a LoanApplication with sensible Australian defaults."""
    defaults = {
        "applicant": user,
        "annual_income": Decimal("85000.00"),
        "credit_score": 750,
        "loan_amount": Decimal("350000.00"),
        "loan_term_months": 360,
        "debt_to_income": Decimal("4.12"),
        "employment_length": 5,
        "purpose": "home",
        "home_ownership": "mortgage",
        "has_cosigner": False,
        "has_hecs": False,
        "has_bankruptcy": False,
        "state": "NSW",
    }
    defaults.update(overrides)
    return LoanApplication.objects.create(**defaults)


def _mock_prediction(prediction="approved", probability=0.85):
    """Return a realistic prediction result dict."""
    return {
        "prediction": prediction,
        "probability": probability,
        "feature_importances": {"credit_score": 0.25, "debt_to_income": 0.20, "annual_income": 0.15},
        "shap_values": {},
        "model_version": TEST_MODEL_VERSION_ID,
        "processing_time_ms": 42,
        "requires_human_review": False,
    }


def _mock_email_result(passed=True):
    """Return a realistic email generation result dict."""
    return {
        "subject": "Your Loan Application Decision",
        "body": "Dear Customer, your loan has been processed.",
        "passed_guardrails": passed,
        "guardrail_results": [],
        "template_fallback": False,
        "attempt_number": 1,
    }


def _mock_bias_result(score=20, flagged=False):
    """Return a realistic bias check result dict."""
    return {
        "score": score,
        "flagged": flagged,
        "requires_human_review": False,
        "categories": [],
        "analysis": "No bias detected.",
        "deterministic_score": score,
        "llm_raw_score": score,
        "score_source": "composite",
    }


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    FIELD_ENCRYPTION_KEY="Q1bXXPr1cYO3Cjd7uP5J8nWRxzdBjQrTAosMayGV3CA=",
)
class DecisionWaterfallTestCase(TestCase):
    """Verify LoanDecision.decision_waterfall is populated by the orchestrator."""

    def setUp(self):
        from apps.accounts.models import _get_fernet
        from apps.ml_engine.models import ModelVersion

        _get_fernet.cache_clear()
        self.user = CustomUser.objects.create_user(
            username="waterfall_test",
            password="TestPass123!",
            email="waterfall@test.com",
            role="customer",
        )
        # Create a ModelVersion record so the FK constraint is satisfied
        from django.conf import settings as django_settings

        ModelVersion.objects.create(
            id=TEST_MODEL_VERSION_UUID,
            algorithm="rf",
            version="test-waterfall-v1",
            file_path=str(django_settings.ML_MODELS_DIR / "test_model.joblib"),
            is_active=True,
        )
        self.orchestrator = PipelineOrchestrator()

    def _run_pipeline_with_mocks(self, application, prediction_result, email_result, bias_result):
        """Run the orchestrator with all external services mocked."""
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = prediction_result

        mock_generator = MagicMock()
        mock_generator.generate.return_value = email_result

        mock_bias = MagicMock()
        mock_bias.analyze.return_value = bias_result

        mock_fraud = MagicMock()
        mock_fraud.run_checks.return_value = {
            "passed": True,
            "risk_score": 0.1,
            "checks": [],
            "flagged_reasons": [],
        }

        # Create a real GeneratedEmail-like mock that satisfies FK constraints
        from apps.email_engine.models import GeneratedEmail

        generated_email = GeneratedEmail.objects.create(
            application=application,
            decision="approved",
            subject="Test",
            body="Test body",
            prompt_used="test prompt",
            passed_guardrails=True,
        )

        with (
            patch("apps.agents.services.orchestrator.ModelPredictor", return_value=mock_predictor),
            patch("apps.agents.services.orchestrator.EmailGenerator", return_value=mock_generator),
            patch("apps.agents.services.orchestrator.EmailPersistenceService") as mock_persist,
            patch("apps.agents.services.orchestrator.BiasDetector", return_value=mock_bias),
            patch("apps.agents.services.orchestrator.FraudDetectionService", return_value=mock_fraud),
            patch("apps.agents.services.orchestrator.FraudCheck"),
            patch("apps.agents.services.orchestrator.PredictionLog"),
            patch("apps.email_engine.services.sender.send_decision_email", return_value={"sent": True}),
            patch.object(
                PipelineOrchestrator,
                "_run_nbo_and_marketing_pipeline",
                side_effect=lambda app, ar, steps, dr, pc: steps,
            ),
        ):
            mock_persist.save_generated_email.return_value = generated_email
            mock_persist.save_guardrail_logs.return_value = None
            return self.orchestrator.orchestrate(application.pk)

    def test_approved_waterfall_has_required_steps(self):
        """An approved pipeline should produce policy_rules, ml_prediction, and final_decision entries."""
        app = _make_application(self.user)
        pred = _mock_prediction("approved", 0.85)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        waterfall = decision.decision_waterfall

        self.assertIsInstance(waterfall, list)
        self.assertGreater(len(waterfall), 0, "Waterfall should not be empty")

        step_names = [entry["step"] for entry in waterfall]
        self.assertIn("policy_rules", step_names)
        self.assertIn("ml_prediction", step_names)
        self.assertIn("final_decision", step_names)

    def test_approved_waterfall_entry_structure(self):
        """Each waterfall entry must have the required keys."""
        app = _make_application(self.user)
        pred = _mock_prediction("approved", 0.85)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        required_keys = {"step", "result", "reason_code", "detail", "timestamp"}

        for entry in decision.decision_waterfall:
            self.assertTrue(
                required_keys.issubset(entry.keys()),
                f"Entry missing keys: {required_keys - entry.keys()} in {entry}",
            )

    def test_approved_pipeline_final_decision_is_pass(self):
        """Final decision entry should have result='pass' for approved/conditional loans."""
        app = _make_application(self.user)
        pred = _mock_prediction("approved", 0.85)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        final_entries = [e for e in decision.decision_waterfall if e["step"] == "final_decision"]
        self.assertEqual(len(final_entries), 1)
        self.assertEqual(final_entries[0]["result"], "pass")
        self.assertIn(final_entries[0]["reason_code"], ("APPROVED", "CONDITIONAL_APPROVED"))

    def test_denied_pipeline_final_decision_is_fail(self):
        """Final decision entry should have result='fail' for denied loans."""
        app = _make_application(self.user)
        pred = _mock_prediction("denied", 0.25)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        final_entries = [e for e in decision.decision_waterfall if e["step"] == "final_decision"]
        self.assertEqual(len(final_entries), 1)
        self.assertEqual(final_entries[0]["result"], "fail")
        self.assertEqual(final_entries[0]["reason_code"], "DENIED")

    def test_bankruptcy_flag_produces_policy_fail(self):
        """Applicant with bankruptcy should have a BANKRUPTCY_FLAG policy_rules fail entry."""
        app = _make_application(self.user, has_bankruptcy=True)
        pred = _mock_prediction("denied", 0.15)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        bankruptcy_entries = [
            e
            for e in decision.decision_waterfall
            if e["step"] == "policy_rules" and e["reason_code"] == "BANKRUPTCY_FLAG"
        ]
        self.assertEqual(len(bankruptcy_entries), 1)
        self.assertEqual(bankruptcy_entries[0]["result"], "fail")

    def test_high_dti_produces_policy_fail(self):
        """DTI above 6.0 should produce a DTI_EXCEEDED policy_rules fail entry."""
        app = _make_application(self.user, debt_to_income=Decimal("7.50"))
        pred = _mock_prediction("denied", 0.20)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        dti_entries = [
            e for e in decision.decision_waterfall if e["step"] == "policy_rules" and e["reason_code"] == "DTI_EXCEEDED"
        ]
        self.assertEqual(len(dti_entries), 1)
        self.assertEqual(dti_entries[0]["result"], "fail")

    def test_clean_application_has_all_policy_passes(self):
        """Clean application (no bankruptcy, DTI within limit) should have passing policy entries."""
        app = _make_application(self.user, has_bankruptcy=False, debt_to_income=Decimal("3.50"))
        pred = _mock_prediction("approved", 0.90)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=10, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        policy_entries = [e for e in decision.decision_waterfall if e["step"] == "policy_rules"]
        for entry in policy_entries:
            self.assertEqual(entry["result"], "pass", f"Expected pass but got {entry}")

    def test_email_generation_recorded_in_waterfall(self):
        """Email generation step should be recorded in the waterfall."""
        app = _make_application(self.user)
        pred = _mock_prediction("approved", 0.85)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        email_entries = [e for e in decision.decision_waterfall if e["step"] == "email_generation"]
        self.assertEqual(len(email_entries), 1)
        self.assertEqual(email_entries[0]["result"], "pass")

    def test_bias_check_recorded_in_waterfall(self):
        """Bias check step should be recorded in the waterfall."""
        app = _make_application(self.user)
        pred = _mock_prediction("approved", 0.85)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        bias_entries = [e for e in decision.decision_waterfall if e["step"] == "bias_check"]
        self.assertEqual(len(bias_entries), 1)
        self.assertEqual(bias_entries[0]["result"], "pass")
        self.assertEqual(bias_entries[0]["reason_code"], "BIAS_CLEAR")

    def test_waterfall_ordering_is_chronological(self):
        """Waterfall entries should be in chronological order."""
        app = _make_application(self.user)
        pred = _mock_prediction("approved", 0.85)
        email = _mock_email_result(passed=True)
        bias = _mock_bias_result(score=20, flagged=False)

        self._run_pipeline_with_mocks(app, pred, email, bias)

        decision = LoanDecision.objects.get(application=app)
        timestamps = [e["timestamp"] for e in decision.decision_waterfall]
        self.assertEqual(timestamps, sorted(timestamps), "Waterfall entries should be in chronological order")


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    FIELD_ENCRYPTION_KEY="Q1bXXPr1cYO3Cjd7uP5J8nWRxzdBjQrTAosMayGV3CA=",
)
class WaterfallEntryHelperTestCase(TestCase):
    """Unit tests for the _waterfall_entry static method."""

    def test_entry_has_correct_keys(self):
        entry = PipelineOrchestrator._waterfall_entry(
            "fraud_check",
            "pass",
            "FRAUD_CLEAR",
            "No fraud indicators detected",
        )
        self.assertEqual(entry["step"], "fraud_check")
        self.assertEqual(entry["result"], "pass")
        self.assertEqual(entry["reason_code"], "FRAUD_CLEAR")
        self.assertEqual(entry["detail"], "No fraud indicators detected")
        self.assertIn("timestamp", entry)

    def test_timestamp_is_iso_format(self):
        entry = PipelineOrchestrator._waterfall_entry(
            "policy_rules",
            "fail",
            "DTI_EXCEEDED",
            "DTI too high",
        )
        from datetime import datetime

        # Should not raise — validates ISO format
        datetime.fromisoformat(entry["timestamp"])
