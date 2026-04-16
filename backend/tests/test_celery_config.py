"""B2: Celery worker tuning tests."""

from config.celery import app


def test_task_acks_late_enabled():
    """Tasks acknowledged after execution, not before.

    Gives at-least-once semantics: if a worker dies mid-task,
    the broker re-delivers it to another worker.
    """
    assert app.conf.task_acks_late is True


def test_worker_prefetch_multiplier_conservative():
    """Prefetch multiplier tuned down from default 4.

    For the agents orchestration + ml queues we prefer strict
    ordering + fair dispatch over throughput. 1 or 2 both acceptable
    as a global default.
    """
    assert app.conf.worker_prefetch_multiplier in (1, 2)


def test_task_reject_on_worker_lost_true():
    """If a worker is killed (OOM / SIGKILL), requeue the task."""
    assert app.conf.task_reject_on_worker_lost is True


def test_task_serializer_is_json():
    """JSON serialiser for tasks + results."""
    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert "json" in app.conf.accept_content


def test_worker_max_tasks_per_child_set():
    """Worker restart cap set to mitigate long-running memory growth."""
    assert app.conf.worker_max_tasks_per_child == 1000
