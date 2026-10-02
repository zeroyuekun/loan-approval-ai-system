"""Helpers shared by Celery tasks across apps."""

from contextlib import contextmanager

from django.core.cache import cache


@contextmanager
def task_dedup_lock(key, task_id, ttl, *, keep_on=()):
    """Hold a cache dedup lock for one task run and its own retries.

    Yields True when this run holds the lock, False when another task holds
    it and the caller should skip. A Celery retry runs the body again with the
    same task id, so a lock already held under ``task_id`` is our own retry
    re-entering: it proceeds and the TTL is refreshed.

    The lock is released when the body returns or raises, except on the
    ``keep_on`` exceptions after which Celery retries the task: releasing it
    before the retry runs would let a duplicate start in between (M22). The
    TTL must cover one run plus the longest countdown before its retry.
    """
    if not cache.add(key, task_id, ttl):
        if cache.get(key) != task_id:
            yield False
            return
        cache.set(key, task_id, ttl)
    try:
        yield True
    except keep_on:
        raise
    except BaseException:
        cache.delete(key)
        raise
    cache.delete(key)
