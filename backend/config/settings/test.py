"""Test settings — extends base with SQLite in-memory + eager Celery + fast hashers.

Used by pytest via DJANGO_SETTINGS_MODULE in pytest.ini. Never ships to production.
"""
from .base import *  # noqa: F401, F403
import os

os.environ.setdefault("DJANGO_DEBUG", "False")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

SECRET_KEY = "django-test-only-not-for-prod-" + "x" * 40
FIELD_ENCRYPTION_KEY = "24t2o3YTKc9XxOzY-1HI0FOpTmXNaiDvWbmuLxuN9Xw="

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class _DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
