"""
Production settings.
"""

import os

from .base import *  # noqa: F401, F403

DEBUG = False

# Everything base.py derived from the DJANGO_DEBUG env var is re-derived here,
# now that DEBUG is final: a stray DJANGO_DEBUG=true in a production env must
# not ship insecure cookies or skip the secret checks.
JWT_COOKIE_SECURE = True

from config.env_validation import validate_production_secrets  # noqa: E402

validate_production_secrets(
    secret_key=SECRET_KEY,  # noqa: F405
    field_encryption_key=FIELD_ENCRYPTION_KEY,  # noqa: F405
    kms_backend=KMS_BACKEND,  # noqa: F405
)

# Must match the env var name used in base.py (DJANGO_ALLOWED_HOSTS).
_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]
if not ALLOWED_HOSTS:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must be set to a non-empty comma-separated list in production. "
        "Example: DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com"
    )

# Client IP for throttling: the k8s nginx ingress is the one hop in front of
# the backend and appends the TCP peer to X-Forwarded-For. Override with
# TRUSTED_PROXY_COUNT when the topology differs (0 = no proxy in front).
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "NUM_PROXIES": int(os.environ.get("TRUSTED_PROXY_COUNT") or 1),
}

# Security settings
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# An empty value (compose passes SECURE_SSL_REDIRECT= when unset) means the
# default, not "off".
SECURE_SSL_REDIRECT = (os.environ.get("SECURE_SSL_REDIRECT") or "True").lower() in ("true", "1", "yes")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


# Governance gates fail closed in production. base.py defaults them to their
# advisory modes so local training and the demo never get stuck; here each
# defaults to its blocking mode. An env var may still override a gate (e.g.
# ML_FAIRNESS_GATE_MODE=warn for a reviewed exception); an empty value means
# the default, and an unknown value is a start-up error rather than a silent
# fall back to the advisory mode.
def _gate_mode(name, default, valid):
    value = (os.environ.get(name) or default).strip().lower()
    if value not in valid:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(f"{name}={value!r} is not one of {', '.join(valid)}")
    return value


ML_FAIRNESS_GATE_MODE = _gate_mode("ML_FAIRNESS_GATE_MODE", "block", ("warn", "block", "off"))
ML_PROMOTION_GATE_MODE = _gate_mode("ML_PROMOTION_GATE_MODE", "block", ("warn", "block", "off"))
ML_VALIDATION_SIGNOFF_GATE_MODE = _gate_mode("ML_VALIDATION_SIGNOFF_GATE_MODE", "block", ("warn", "block", "off"))
CREDIT_POLICY_OVERLAY_MODE = _gate_mode("CREDIT_POLICY_OVERLAY_MODE", "enforce", ("off", "shadow", "enforce"))
# "second_approver" refuses high-value overturns at the API (dual approval is
# out of band). The legacy "2fa" value maps to it: two-factor authentication
# was removed, and an old env file must not turn the gate off.
_overturn_mode = _gate_mode("DECISION_OVERTURN_GATE_MODE", "second_approver", ("off", "2fa", "second_approver"))
DECISION_OVERTURN_GATE_MODE = "second_approver" if _overturn_mode == "2fa" else _overturn_mode
BIAS_FAILURE_MODE = _gate_mode("BIAS_FAILURE_MODE", "block", ("warn", "block", "off"))
# Never load a model artefact without a stored SHA-256, whatever DJANGO_DEBUG says.
ML_ALLOW_UNHASHED_MODELS = False

DATABASES["default"]["CONN_MAX_AGE"] = 600
DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "require"

# CSRF cookie must be readable by JS for cookie-based auth
CSRF_COOKIE_HTTPONLY = False

# Celery task limits
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
# worker_max_tasks_per_child is set in celery.py (env-var override there).
CELERY_RESULT_EXPIRES = 3600

# Enforce Content Security Policy in production (base.py has REPORT_ONLY=True for dev)
CONTENT_SECURITY_POLICY = {**CONTENT_SECURITY_POLICY, "REPORT_ONLY": False}  # noqa: F405

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
