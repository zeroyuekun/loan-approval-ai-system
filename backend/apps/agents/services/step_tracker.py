import contextvars
import logging
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings

from apps.agents.metrics import pipeline_e2e_seconds
from apps.loans.models import LoanDecision

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
        "bias_regeneration": 60_000,
        # Rewrite + bias check + senior review: one generation, one detector
        # call and one review call, each budgeted like its own step.
        "bias_agent2_regeneration": 180_000,
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
        "human_escalation_moderate_bias": 5_000,
        "human_escalation_low_confidence": 5_000,
        "human_review_approved": 5_000,
        "human_review_denied": 5_000,
        "human_review_required": 5_000,
        "marketing_email_blocked": 5_000,
    },
)


# ---------------------------------------------------------------------------
# Time-limit propagation (I9)
#
# Celery's SoftTimeLimitExceeded subclasses Exception, so the broad
# ``except Exception`` arm in every pipeline step (and in the bias, NBO and
# marketing helpers) would swallow it and the run would carry on until the
# hard kill, which skips all cleanup. Rather than patch every handler, the
# step lifecycle is the choke point every step passes through:
#   * fail_step re-raises a SoftTimeLimitExceeded that is being handled, and
#   * start_step refuses to begin a step once the task's soft deadline has
#     passed (catches a limit swallowed by a helper that never calls fail_step).
# The orchestrate/resume tasks open the deadline scope with their soft limit.
# ---------------------------------------------------------------------------

_PIPELINE_DEADLINE = contextvars.ContextVar("pipeline_deadline", default=None)


@contextmanager
def pipeline_deadline(seconds):
    """Steps may not start after ``seconds`` from now (monotonic clock)."""
    token = _PIPELINE_DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _PIPELINE_DEADLINE.reset(token)


def seconds_until_deadline():
    """Seconds left before the pipeline's soft deadline, or None outside a deadline scope."""
    deadline = _PIPELINE_DEADLINE.get()
    if deadline is None:
        return None
    return deadline - time.monotonic()


def raise_if_past_deadline():
    deadline = _PIPELINE_DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise SoftTimeLimitExceeded("pipeline soft time limit reached")


class StepTracker:
    """Pure utility class for tracking pipeline step lifecycle."""

    def start_step(self, step_name):
        raise_if_past_deadline()
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
        # Step handlers call this from inside their broad except arm; a soft
        # time limit being handled there must reach the task, not be recorded.
        handled = sys.exc_info()[1]
        if isinstance(handled, SoftTimeLimitExceeded):
            raise handled
        now = datetime.now(UTC)
        step["status"] = "failed"
        step["completed_at"] = now.isoformat()
        started = datetime.fromisoformat(step["started_at"])
        step["duration_ms"] = int((now - started).total_seconds() * 1000)
        step["error"] = error
        step["failure_category"] = failure_category or self.categorize_error(error)
        return step

    def record_delivery(self, step, outcome):
        """Close an ``email_delivery`` step from a ``deliver_decision_email`` outcome."""
        if outcome["sent"] or outcome["already_sent"]:
            return self.complete_step(step, result_summary={"sent": True, "recipient": outcome["recipient"]})
        if outcome["recipient"] is None:
            return self.complete_step(step, result_summary={"sent": False, "reason": "No recipient email"})
        return self.fail_step(step, outcome["error"] or "Send failed")

    @staticmethod
    def post_decision_failure_step(step_name, error):
        """A failed-step record for best-effort work after the decision is applied.

        Built directly rather than through ``fail_step``, which re-raises a
        soft time limit being handled: after the decision there is nothing
        left for the limit to stop but finalizing the run.
        """
        now = datetime.now(UTC).isoformat()
        return {
            "step_name": step_name,
            "status": "failed",
            "started_at": now,
            "completed_at": now,
            "duration_ms": 0,
            "timeout_ms": STEP_TIMEOUT_BUDGETS_MS.get(step_name, 120_000),
            "result_summary": None,
            "error": str(error) or type(error).__name__,
            "failure_category": "transient",
        }

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
        # Preserve a status (and error) the caller deliberately set before
        # finalizing: "escalated" (bias human-review) and "failed" (e.g. the
        # bias-check fail-safe hold, which withholds the email and records its
        # own descriptive error). Only auto-derive status when the caller left
        # it unset/in-progress.
        if agent_run.status not in ("escalated", "failed"):
            agent_run.status = "failed" if error else "completed"
        if error:
            agent_run.error = error
        elif agent_run.status != "failed":
            agent_run.error = ""
        agent_run.save()

        # Emit Prometheus e2e-latency histogram. Metric emission must never
        # break the pipeline, so any Prometheus client failure is swallowed.
        try:
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
        LoanDecision.objects.filter(application=application).update(
            decision_waterfall=waterfall,
        )
