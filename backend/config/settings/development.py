"""
Development settings.
"""

import os

from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# base.py derived these from the DJANGO_DEBUG env var before DEBUG was forced
# on here; development is plain HTTP whatever that var says.
JWT_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Use PostgreSQL if POSTGRES_HOST is set (Docker), otherwise SQLite
if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "loan_approval"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            # Tag connections so the watchdog idle-in-transaction reaper
            # can scope its kill to this app. Keep in sync with DB_APPLICATION_NAME.
            "OPTIONS": {
                "application_name": DB_APPLICATION_NAME,  # noqa: F405 — from base via star-import
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
