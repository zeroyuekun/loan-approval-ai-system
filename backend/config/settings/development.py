"""
Development settings.
"""

import os

from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# DATABASE_URL wins (already parsed in base.py). POSTGRES_HOST is the
# docker-compose path. Fall back to a local SQLite file for lightweight
# local runs with no services.
if not os.environ.get("DATABASE_URL") and not os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
