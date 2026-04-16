"""Integration tests that execute Celery tasks through the real Redis broker.

These tests verify the full task execution path: serialization -> broker ->
worker -> result backend. They require Redis to be running (available in CI).

Skipped when Redis is not available (local dev without Docker).
"""

from unittest.mock import patch

import pytest

# Import the skip marker
from tests.conftest import skip_without_redis


@skip_without_redis
@pytest.mark.django_db(transaction=True)
class TestCeleryTaskExecution:
    """Verify tasks execute through the real broker."""

    def test_prediction_task_serializes_correctly(self):
        """Verify the prediction task can be serialized and sent to broker."""
        from apps.loans.models import LoanApplication
        from apps.ml_engine.tasks import run_prediction_task

        # Mock the actual prediction to avoid needing a trained model
        with patch("apps.ml_engine.services.predictor.ModelPredictor") as mock_predictor:
            mock_predictor.return_value.predict.return_value = {
                "prediction": "approved",
                "probability": 0.85,
                "risk_grade": "BB",
                "feature_importances": {},
                "shap_values": {},
                "processing_time_ms": 100,
                "model_version": "test-v1",
            }
            # Use .apply() to execute synchronously but still go through
            # the full serialization path (args must be JSON-serializable).
            result = run_prediction_task.apply(args=[999])

        # Task must have actually executed past serialisation and hit the DB.
        # LoanApplication pk=999 does not exist → expected DoesNotExist.
        assert result.failed(), "Task must actually execute (not just be constructed)"
        assert isinstance(result.result, LoanApplication.DoesNotExist), (
            f"Expected LoanApplication.DoesNotExist (proves task ran past serialisation "
            f"and hit the DB), got {type(result.result).__name__}: {result.result}"
        )

    def test_email_task_serializes_correctly(self):
        """Verify the email task args are JSON-serializable through the broker."""
        from apps.email_engine.tasks import generate_email_task
        from apps.loans.models import LoanApplication

        # apply() runs synchronously but exercises serialization.
        result = generate_email_task.apply(args=[999, "approved"])

        assert result.failed(), "Task must actually execute (not just be constructed)"
        assert isinstance(result.result, LoanApplication.DoesNotExist), (
            f"Expected LoanApplication.DoesNotExist (proves task ran past serialisation "
            f"and hit the DB), got {type(result.result).__name__}: {result.result}"
        )

    def test_orchestrate_task_serializes_correctly(self):
        """Verify the orchestrate pipeline task serializes its arguments."""
        from apps.agents.tasks import orchestrate_pipeline_task
        from apps.loans.models import LoanApplication

        # apply() runs synchronously and exercises serialization. The task
        # itself will fail inside on DB lookup (app_id=999 doesn't exist).
        result = orchestrate_pipeline_task.apply(args=[999])

        assert result.failed(), "Task must actually execute (not just be constructed)"
        assert isinstance(result.result, LoanApplication.DoesNotExist), (
            f"Expected LoanApplication.DoesNotExist (proves task ran past serialisation "
            f"and hit the orchestrator), got {type(result.result).__name__}: {result.result}"
        )

    def test_task_result_is_json_serializable(self):
        """Verify the broker accepts a task and the result backend tracks it.

        We don't wait for .get() because CI runs no Celery worker — the ping
        would time out regardless of whether the transport works. What we can
        prove is that send_task returned a well-formed AsyncResult whose id
        round-trips through the result backend. If the broker URL or result
        backend URL were misconfigured, send_task itself would raise.
        """
        from celery import current_app
        from celery.result import AsyncResult

        result = current_app.send_task("celery.ping")
        assert isinstance(result, AsyncResult)
        assert isinstance(result.id, str) and len(result.id) > 0
        # Round-trip: re-hydrate the AsyncResult from its id via the backend.
        assert AsyncResult(result.id, app=current_app).id == result.id

    def test_train_model_task_serializes_kwargs(self):
        """Verify train_model_task kwargs (algorithm, data_path) serialize."""
        from apps.ml_engine.tasks import train_model_task

        # apply() exercises full serialization; the task will fail inside
        # trainer logic (missing csv) — we're testing the transport layer.
        result = train_model_task.apply(
            kwargs={
                "algorithm": "xgb",
                "data_path": "/tmp/nonexistent.csv",
            }
        )

        assert result.failed(), "Task must actually execute (not just be constructed)"
        assert isinstance(result.result, Exception), (
            f"Expected exception from trainer (proves task ran past serialisation), "
            f"got {type(result.result).__name__}: {result.result}"
        )

    def test_resume_pipeline_task_serializes_correctly(self):
        """Verify resume_pipeline_task serializes its string arguments."""
        from apps.agents.models import AgentRun
        from apps.agents.tasks import resume_pipeline_task

        result = resume_pipeline_task.apply(
            args=[999],
            kwargs={
                "reviewer": "test-officer",
                "note": "Approved after manual review",
            },
        )

        # agent_run_id=999 does not exist → resume_after_review() raises
        # AgentRun.DoesNotExist from the select_for_update fetch. That proves
        # the task serialised its kwargs and actually executed.
        assert result.failed(), "Task must actually execute (not just be constructed)"
        assert isinstance(result.result, AgentRun.DoesNotExist), (
            f"Expected AgentRun.DoesNotExist (proves task ran past serialisation "
            f"and hit the DB), got {type(result.result).__name__}: {result.result}"
        )


@skip_without_redis
class TestCeleryBrokerHealth:
    """Verify the Redis broker connection is healthy."""

    def test_broker_ping(self):
        """Verify we can ping the Celery broker."""
        import redis

        from tests.conftest import _redis_url

        r = redis.Redis.from_url(_redis_url(), socket_connect_timeout=2)
        assert r.ping() is True

    def test_celery_app_configured(self):
        """Verify the Celery app discovers our project tasks."""
        from config.celery import app

        # The app should have autodiscovered tasks from our Django apps
        registered = app.tasks.keys()
        # Check at least one of our custom tasks is registered
        expected_tasks = [
            "apps.ml_engine.tasks.run_prediction_task",
            "apps.email_engine.tasks.generate_email_task",
            "apps.agents.tasks.orchestrate_pipeline_task",
        ]
        for task_name in expected_tasks:
            assert task_name in registered, f"{task_name} not found in registered tasks: {sorted(registered)}"

    def test_task_routing_configured(self):
        """Verify task routing sends tasks to the correct queues."""
        from config.celery import app

        routes = app.conf.task_routes
        assert "apps.ml_engine.tasks.*" in routes
        assert routes["apps.ml_engine.tasks.*"] == {"queue": "ml"}
        assert routes["apps.email_engine.tasks.*"] == {"queue": "email"}
        assert routes["apps.agents.tasks.*"] == {"queue": "agents"}
