import logging
import time
from datetime import UTC, datetime

from django.conf import settings

logger = logging.getLogger("agents.orchestrator")

# Step timeout budgets — configurable via settings for environment-specific tuning.
STEP_TIMEOUT_BUDGETS_MS = getattr(
    settings,
    "ORCHESTRATOR_STEP_TIMEOUTS",
    {
        "fraud_check": 10_000,
        "ml_prediction": 30_000,
        "email_generation": 60_000,
        "bias_check": 60_000,
        "ai_email_review": 60_000,
        "email_delivery": 30_000,
        "next_best_offers": 60_000,
        "marketing_message_generation": 60_000,
        "marketing_email_generation": 60_000,
        "marketing_bias_check": 60_000,
        "marketing_ai_review": 60_000,
        "marketing_email_delivery": 30_000,
        "human_escalation": 5_000,
        "human_escalation_severe_bias": 5_000,
        "human_escalation_low_confidence": 5_000,
        "human_review_approved": 5_000,
        "human_review_required": 5_000,
        "marketing_email_blocked": 5_000,
    },
)


class StepTracker:
    """Pure utility class for tracking pipeline step lifecycle."""

    def start_step(self, step_name):
        return {
            "step_name": step_name,
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
            "duration_ms": None,
            "timeout_ms": STEP_TIMEOUT_BUDGETS_MS.get(step_name, 120_000),
            "result_summary": None,
            "error": None,
            "failure_category": None,
        }

    def complete_step(self, step, result_summary=None):
        now = datetime.now(UTC)
        step["status"] = "completed"
        step["completed_at"] = now.isoformat()
        started = datetime.fromisoformat(step["started_at"])
        step["duration_ms"] = int((now - started).total_seconds() * 1000)
        step["result_summary"] = result_summary
        timeout_ms = step.get("timeout_ms", 120_000)
        if step["duration_ms"] > timeout_ms:
            logger.warning(
                "Step %s exceeded timeout budget: %dms > %dms",
                step["step_name"],
                step["duration_ms"],
                timeout_ms,
            )
        return step

    def fail_step(self, step, error, failure_category=None):
        now = datetime.now(UTC)
        step["status"] = "failed"
        step["completed_at"] = now.isoformat()
        started = datetime.fromisoformat(step["started_at"])
        step["duration_ms"] = int((now - started).total_seconds() * 1000)
        step["error"] = error
        step["failure_category"] = failure_category or self.categorize_error(error)
        return step

    def categorize_error(self, error):
        error_lower = str(error).lower()
        if any(term in error_lower for term in ["timeout", "rate limit", "429", "timed out"]):
            return "transient"
        if any(term in error_lower for term in ["auth", "401", "403", "not found", "model not found", "invalid"]):
            return "permanent"
        if any(
            term in error_lower
            for term in ["redis", "database", "connection refused", "connection reset", "broken pipe"]
        ):
            return "infrastructure"
        return "unknown"

    def finalize_run(self, agent_run, steps, start_time, error=None):
        total_time = int((time.time() - start_time) * 1000)
        agent_run.steps = steps
        agent_run.total_time_ms = total_time
        if agent_run.status != "escalated":
            agent_run.status = "failed" if error else "completed"
        agent_run.error = error or ""
        agent_run.save()

        # Emit Prometheus e2e-latency histogram. Metric emission must never
        # break the pipeline, so any Prometheus client failure is swallowed.
        try:
            from apps.agents.metrics import pipeline_e2e_seconds
            from apps.loans.models import LoanDecision

            decision_label = "unknown"
            try:
                decision_label = agent_run.application.decision.decision or "unknown"
            except (LoanDecision.DoesNotExist, AttributeError):
                pass
            pipeline_e2e_seconds.labels(
                status=agent_run.status,
                decision=decision_label,
            ).observe(total_time / 1000.0)
        except Exception as exc:  # noqa: BLE001 — metric emission is best-effort
            logger.debug("pipeline_e2e_seconds emission failed: %s", exc)

    @staticmethod
    def waterfall_entry(step: str, result: str, reason_code: str, detail: str) -> dict:
        return {
            "step": step,
            "result": result,
            "reason_code": reason_code,
            "detail": detail,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def save_waterfall(application, waterfall: list) -> None:
        from apps.loans.models import LoanDecision

        LoanDecision.objects.filter(application=application).update(
            decision_waterfall=waterfall,
        )
