import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from apps.agents.exceptions import FailureCategory, PipelineStepError
from apps.agents.services.orchestrator import STEP_TIMEOUT_BUDGETS_MS, PipelineOrchestrator
from apps.agents.services.step_tracker import StepTracker


class TestStepHelpers:
    def setup_method(self):
        self.orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
        self.orchestrator._step_tracker = StepTracker()

    def test_start_step_includes_new_fields(self):
        step = self.orchestrator._start_step("ml_prediction")
        assert step["duration_ms"] is None
        assert step["timeout_ms"] == 30_000
        assert step["failure_category"] is None
        assert step["step_name"] == "ml_prediction"
        assert step["status"] == "running"

    def test_start_step_default_timeout(self):
        step = self.orchestrator._start_step("unknown_step")
        assert step["timeout_ms"] == 120_000

    def test_complete_step_computes_duration(self):
        step = self.orchestrator._start_step("ml_prediction")
        # Simulate time passing
        step["started_at"] = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
        step = self.orchestrator._complete_step(step, result_summary={"test": True})
        assert step["duration_ms"] >= 1900  # ~2 seconds
        assert step["status"] == "completed"
        assert step["result_summary"] == {"test": True}

    def test_complete_step_warns_on_timeout(self):
        step = self.orchestrator._start_step("ml_prediction")
        step["started_at"] = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        with patch("apps.agents.services.orchestrator.logger") as mock_logger:
            self.orchestrator._complete_step(step)
            mock_logger.warning.assert_called_once()

    def test_fail_step_includes_category(self):
        step = self.orchestrator._start_step("email_generation")
        step["started_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        step = self.orchestrator._fail_step(step, "Connection timeout", failure_category="transient")
        assert step["failure_category"] == "transient"
        assert step["duration_ms"] >= 900
        assert step["status"] == "failed"

    def test_fail_step_auto_categorizes(self):
        step = self.orchestrator._start_step("bias_check")
        step["started_at"] = datetime.now(UTC).isoformat()
        step = self.orchestrator._fail_step(step, "Redis connection refused")
        assert step["failure_category"] == "infrastructure"

    def test_categorize_error_transient(self):
        assert self.orchestrator._categorize_error("Connection timeout after 30s") == "transient"
        assert self.orchestrator._categorize_error("Rate limit exceeded (429)") == "transient"

    def test_categorize_error_permanent(self):
        assert self.orchestrator._categorize_error("Model not found: v3") == "permanent"
        assert self.orchestrator._categorize_error("Authentication failed (401)") == "permanent"

    def test_categorize_error_infrastructure(self):
        assert self.orchestrator._categorize_error("Redis connection refused") == "infrastructure"
        assert self.orchestrator._categorize_error("Database connection reset") == "infrastructure"

    def test_categorize_error_unknown(self):
        assert self.orchestrator._categorize_error("Something weird happened") == "unknown"

    def test_step_dict_json_serializable(self):
        step = self.orchestrator._start_step("ml_prediction")
        step["started_at"] = datetime.now(UTC).isoformat()
        step = self.orchestrator._complete_step(step, result_summary={"score": 0.85})
        json_str = json.dumps(step)
        assert json_str  # No TypeError

    def test_failed_step_json_serializable(self):
        step = self.orchestrator._start_step("email_generation")
        step["started_at"] = datetime.now(UTC).isoformat()
        step = self.orchestrator._fail_step(step, "timeout", failure_category="transient")
        json_str = json.dumps(step)
        assert json_str


class TestFailureCategory:
    def test_enum_values(self):
        assert FailureCategory.TRANSIENT == "transient"
        assert FailureCategory.PERMANENT == "permanent"
        assert FailureCategory.INFRASTRUCTURE == "infrastructure"
        assert FailureCategory.UNKNOWN == "unknown"

    def test_pipeline_step_error_category(self):
        err = PipelineStepError("test_step", "test error", retryable=True, category=FailureCategory.TRANSIENT)
        assert err.category == FailureCategory.TRANSIENT
        assert err.retryable is True

    def test_pipeline_step_error_default_category(self):
        err = PipelineStepError("test_step", "test error")
        assert err.category is None


class TestStepTimeoutBudgets:
    def test_all_known_steps_have_budgets(self):
        known_steps = [
            "ml_prediction",
            "email_generation",
            "bias_check",
            "ai_email_review",
            "email_delivery",
            "next_best_offers",
            "marketing_message_generation",
            "marketing_email_generation",
            "marketing_bias_check",
            "marketing_ai_review",
            "marketing_email_delivery",
        ]
        for step in known_steps:
            assert step in STEP_TIMEOUT_BUDGETS_MS

    def test_timeout_values_are_positive(self):
        for step, timeout in STEP_TIMEOUT_BUDGETS_MS.items():
            assert timeout > 0, f"{step} has non-positive timeout: {timeout}"
