"""
Production settings.
"""

import os

from .base import *  # noqa: F401, F403

DEBUG = False

# Must match the env var name used in base.py (DJANGO_ALLOWED_HOSTS).
# production.py previously read "ALLOWED_HOSTS" which silently returned an
# empty list when only DJANGO_ALLOWED_HOSTS was set (H29).
_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]
if not ALLOWED_HOSTS:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must be set to a non-empty comma-separated list in production. "
        "Example: DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com"
    )

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() in ("true", "1", "yes")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

DATABASES["default"]["CONN_MAX_AGE"] = 600
DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "require"

# CSRF cookie must be readable by JS for cookie-based auth
CSRF_COOKIE_HTTPONLY = False

# Celery task limits
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
# worker_max_tasks_per_child is set canonically in celery.py with env-var override;
# remove duplicate here to avoid the Django CELERY_* setting shadowing it.
CELERY_RESULT_EXPIRES = 3600

# Enforce Content Security Policy in production (base.py has REPORT_ONLY=True for dev)
CONTENT_SECURITY_POLICY = {
    "REPORT_ONLY": False,
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
    },
}

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(correlation_id)s %(message)s",
        },
    },
    "filters": {
        "mask_pii": {
            "()": "config.logging_filters.PiiMaskingFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["mask_pii"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "WARNING"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "agents": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "email_engine": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "ml_engine": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
