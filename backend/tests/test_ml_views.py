"""Tests for ml_engine view layer — specifically the guards around training.

These tests cover the TrainModelView concurrency guard added to stop the
double-click/retry storm that the production race condition triggered.
They use real Redis (via settings.CELERY_BROKER_URL) rather than mocking so
the test exercises the same lock semantics the view relies on. Each test
plants and releases its own lock inside a try/finally so failures cannot
leak state between test runs.
"""

from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog


def _celery_redis_available():
    """True if the Celery broker Redis is reachable.

    Unlike ``tests.conftest._redis_available`` (which hardcodes localhost),
    this honours ``settings.CELERY_BROKER_URL`` so the test runs whether
    pytest is invoked from the host or inside the backend Docker container.
    """
    try:
        import redis
        from django.conf import settings

        client = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1)
        client.ping()
        return True
    except Exception:
        return False


skip_without_celery_redis = pytest.mark.skipif(
    not _celery_redis_available(),
    reason="Celery broker Redis not reachable (tests require Docker/CI)",
)


TRAIN_LOCK_KEY = "train_model_lock"
TRAIN_ENDPOINT = "/api/v1/ml/models/train/"


@pytest.fixture
def ml_admin_client(db):
    """Admin client for the ML training endpoint.

    Defined locally (rather than pulled from conftest) because
    ``test_api_contracts.auth_admin_client`` is a file-local fixture and
    importing across test modules would couple the two files.
    """
    user = CustomUser.objects.create_user(
        username="ml_admin_test",
        email="ml_admin@test.com",
        password="testpass123",
        role="admin",
        first_name="MLAdmin",
        last_name="Test",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _get_lock_client():
    """Return a raw redis client against the Celery broker DB."""
    import redis
    from django.conf import settings

    return redis.from_url(settings.CELERY_BROKER_URL)


@skip_without_celery_redis
@pytest.mark.django_db(transaction=True)
class TestTrainModelViewConcurrency:
    """Regression tests for the 409-on-duplicate training guard."""

    def setup_method(self):
        """Ensure each test starts with a clean lock key."""
        try:
            _get_lock_client().delete(TRAIN_LOCK_KEY)
        except Exception:
            pass

    def teardown_method(self):
        """Always release the lock so a failure doesn't block later tests."""
        try:
            _get_lock_client().delete(TRAIN_LOCK_KEY)
        except Exception:
            pass

    def test_returns_409_when_training_lock_held(self, ml_admin_client):
        """If another training is already running, reject with 409 and no audit row."""
        client, _admin = ml_admin_client
        lock_client = _get_lock_client()

        # Plant a lock exactly the way the Celery task does: set + expiry.
        lock_client.set(TRAIN_LOCK_KEY, "held-by-test", ex=300)

        audit_count_before = AuditLog.objects.filter(action="model_trained").count()

        # Give the mocked delay() a JSON-serializable task_id so that if the
        # guard is ever removed by mistake, the downstream audit-log creation
        # doesn't fail on MagicMock serialization — the test will fail with a
        # clean "expected 409, got 202" message instead of a TypeError.
        fake_task = MagicMock()
        fake_task.id = "should-never-be-enqueued"

        with patch("apps.ml_engine.views.train_model_task.delay", return_value=fake_task) as mock_delay:
            response = client.post(TRAIN_ENDPOINT, {"algorithm": "xgb"}, format="json")

        assert response.status_code == 409, response.content
        body = response.json()
        assert body.get("code") == "training_in_progress"
        assert "progress" in body.get("error", "").lower()

        # No task was enqueued and no audit row was written for the rejected request.
        mock_delay.assert_not_called()
        audit_count_after = AuditLog.objects.filter(action="model_trained").count()
        assert audit_count_after == audit_count_before, (
            "rejected duplicate training request should not create an audit row"
        )

    def test_returns_202_when_lock_free(self, ml_admin_client):
        """Happy path: no lock held, task enqueues, audit row written."""
        client, _admin = ml_admin_client
        # setup_method already cleared the lock. Double-check defensively.
        _get_lock_client().delete(TRAIN_LOCK_KEY)

        fake_task = MagicMock()
        fake_task.id = "fake-task-id-abc123"

        audit_count_before = AuditLog.objects.filter(action="model_trained").count()

        with patch("apps.ml_engine.views.train_model_task.delay", return_value=fake_task) as mock_delay:
            response = client.post(TRAIN_ENDPOINT, {"algorithm": "xgb"}, format="json")

        assert response.status_code == 202, response.content
        body = response.json()
        assert body.get("task_id") == "fake-task-id-abc123"
        assert body.get("status") == "training_queued"

        mock_delay.assert_called_once()
        # Celery task receives algorithm kwarg with value "xgb"
        _, kwargs = mock_delay.call_args
        assert kwargs.get("algorithm") == "xgb"

        audit_count_after = AuditLog.objects.filter(action="model_trained").count()
        assert audit_count_after == audit_count_before + 1

    def test_rejects_invalid_algorithm(self, ml_admin_client):
        """Bad input should 400 regardless of lock state — keeps validation above the lock check."""
        client, _admin = ml_admin_client
        # No lock held.
        _get_lock_client().delete(TRAIN_LOCK_KEY)

        with patch("apps.ml_engine.views.train_model_task.delay") as mock_delay:
            response = client.post(TRAIN_ENDPOINT, {"algorithm": "unsupported_algo"}, format="json")

        assert response.status_code == 400, response.content
        mock_delay.assert_not_called()
