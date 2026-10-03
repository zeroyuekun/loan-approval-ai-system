"""
Base settings for loan approval AI system.
"""

import os
from datetime import timedelta
from pathlib import Path

import sentry_sdk

from config.sentry import scrub_event

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Application version (synced with CHANGELOG.md)
APP_VERSION = "1.11.1"

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")


def _env_int(name: str, default: int) -> int:
    """Read an int env var, tolerant of a malformed value (warn + fall back)
    rather than crashing every process with a ValueError at import time."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        import warnings

        warnings.warn(f"Invalid integer for {name}={raw!r}; using default {default}.", stacklevel=2)
        return default


def _env_float(name: str, default: float) -> float:
    """float counterpart of _env_int — tolerant of malformed values."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        import warnings

        warnings.warn(f"Invalid float for {name}={raw!r}; using default {default}.", stacklevel=2)
        return default


_secret_key = os.environ.get("DJANGO_SECRET_KEY", "")
if not _secret_key and not DEBUG:
    raise ValueError(
        "DJANGO_SECRET_KEY environment variable must be set in production (DEBUG=False). "
        'Generate one with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
    )
SECRET_KEY = _secret_key or "django-insecure-dev-key-change-in-production"
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "django_celery_results",
    # Local apps
    "apps.accounts",
    "apps.loans",
    "apps.ml_engine",
    "apps.email_engine",
    "apps.agents",
    "django_prometheus",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "config.middleware.CorrelationIdMiddleware",
    "csp.middleware.CSPMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Tag this app's PostgreSQL connections so the watchdog's idle-in-transaction
# reaper can scope pg_terminate_backend to ONLY this app's wedged
# transactions and never touch a pooler's healthy idle connections. The
# watchdog reads the same DB_APPLICATION_NAME setting — keep them in sync.
DB_APPLICATION_NAME = os.environ.get("DB_APPLICATION_NAME", "loan_approval")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "loan_approval"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 600,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "application_name": DB_APPLICATION_NAME,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # 12, matching what registration asks of customers; staff passwords set
    # through the admin or createsuperuser go through this list alone.
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.CustomUser"

# Sign-in lockout. Failed sign-ins only add up while they keep coming: a failure
# more than LOGIN_FAILURE_WINDOW after the previous one starts the count again,
# so one wrong password now and then cannot keep an account locked.
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
# (failures in a row, minutes locked), highest first. The longest lock is no
# longer than the window, so once it ends the next failure starts a new count.
LOGIN_LOCKOUT_TIERS = ((10, 15), (8, 5), (5, 1))

LANGUAGE_CODE = "en-au"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("apps.accounts.authentication.CookieJWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
        "user": "60/min",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # APIClient posts JSON unless a test asks for another format, as the
    # frontend does (login and registration accept nothing else).
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    # Reverse-proxy hops in front of Django that append to X-Forwarded-For.
    # Throttles key on the client IP DRF derives from this: with None (the DRF
    # default) the whole client-supplied header is the key, so a spoofed
    # header got a fresh login/register/refresh bucket on every request.
    # 0 = ignore X-Forwarded-For and use REMOTE_ADDR (compose publishes the
    # backend directly). production.py defaults to 1 for the k8s ingress.
    "NUM_PROXIES": _env_int("TRUSTED_PROXY_COUNT", 0),
}

# Simple JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# JWT Cookie settings (HttpOnly cookies instead of localStorage)
JWT_COOKIE_SECURE = not DEBUG  # Secure flag in production
JWT_COOKIE_SAMESITE = "Lax"
JWT_ACCESS_COOKIE_NAME = "access_token"
JWT_REFRESH_COOKIE_NAME = "refresh_token"

# CORS
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True

# A missing CORS_ALLOWED_ORIGINS in production silently falls back to localhost,
# which blocks the real deployed frontend with no obvious error. Surface it loudly
# at startup rather than letting it manifest as opaque CORS failures in the browser.
if not DEBUG and not os.environ.get("CORS_ALLOWED_ORIGINS"):
    import warnings

    warnings.warn(
        "CORS_ALLOWED_ORIGINS is not set with DEBUG=False — defaulting to localhost; "
        "the deployed frontend's requests will be blocked until it is configured.",
        stacklevel=2,
    )

# Content Security Policy (django-csp 4.0+)
# Uses CONTENT_SECURITY_POLICY dict format.
# Start in report-only mode to avoid breaking existing functionality.
CONTENT_SECURITY_POLICY = {
    "REPORT_ONLY": True,
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],  # Required for DRF browsable API + shadcn
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
    },
}

# CSRF trusted origins (must match CORS origins for cookie-based auth)
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS[:]
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # Frontend JS needs to read CSRF token

# Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "django-db")
CELERY_RESULT_EXPIRES = 3600  # Expire task results after 1 hour to prevent DB bloat
CELERY_TIMEZONE = "UTC"
# Serializers, task routes, acks and worker tuning are set on app.conf in
# config/celery.py (app.conf assignments take precedence over CELERY_* here).

# Django Cache (Redis-backed)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get(
            "DJANGO_CACHE_URL",
            CELERY_BROKER_URL.rsplit("/", 1)[0] + "/1" if CELERY_BROKER_URL else "redis://localhost:6379/1",
        ),
        "TIMEOUT": 300,  # 5 minutes default TTL
    }
}

# ML Models
ML_MODELS_DIR = BASE_DIR / "ml_models"

# ML Training Configuration
ML_EARLY_STOPPING_ROUNDS = 30
ML_COST_FP_FN_RATIO = 5  # FP cost : FN cost ratio for threshold optimization
ML_FAIRNESS_TARGET_DI = 0.80  # Target disparate impact ratio (EEOC 80% rule)
# Minimum samples a protected group needs before it drives the disparate-impact
# verdict. Smaller groups (e.g. a state with ~10-20 test rows) are still reported
# but excluded from the min/max ratio, which is otherwise dominated by their
# sampling noise. Shared by MetricsService.compute_fairness_metrics and the gate.
FAIRNESS_MIN_GROUP_SIZE = 30
# XGBoost max_bin for histogram construction. 256 is the XGBoost default and
# is plenty for the 50k-row / 35-feature synthetic dataset; 512 doubled the
# histogram memory and training cost with no measurable accuracy gain.
ML_MAX_BIN = 256
# Optuna trials per tuning run. TPE with a fixed seed converges well before
# trial 30; trials 30-50 typically add <0.002 AUC.
ML_OPTUNA_TRIALS = 30
# Threads per XGBoost training. Matches the celery_worker_ml CPU quota.
ML_XGB_N_JOBS = 2
# Rows the training task auto-generates when .tmp/synthetic_loans.csv is missing
# (fresh clone / cleared .tmp). Smaller than the 50k canonical seed so the
# self-heal stays fast while still producing a usable model. Env-overridable.
ML_AUTO_SEED_ROWS = _env_int("ML_AUTO_SEED_ROWS", 20000)

# Hard credit policy overlay. Modes: "off" (not applied), "shadow"
# (evaluated + logged, model verdict stands), "enforce" (hard-fails override
# the model, refers are recorded on the decision; the human review queue is
# only for bias flags). Default here is "shadow" so the rule set can be
# calibrated in development; production.py defaults to "enforce". Unknown
# values collapse to "shadow" at read time, which is weaker than "enforce",
# so production.py rejects an unknown value at start-up.
CREDIT_POLICY_OVERLAY_MODE = os.environ.get("CREDIT_POLICY_OVERLAY_MODE", "shadow")

# Pre-activation fairness gate mode for `train_model_task`. Three values:
# "warn" (default — log + flag failures, leave model active; current
# behaviour byte-identical), "block" (refuse activation if fairness gate
# fails or no fairness data was recorded — old segment models keep serving),
# "off" (skip the check entirely; emergency escape hatch). Default here is
# "warn" so local training never gets stuck; production.py defaults to
# "block". See docs/superpowers/specs/2026-05-07-ml-fairness-gate-mode-design.md.
ML_FAIRNESS_GATE_MODE = os.environ.get("ML_FAIRNESS_GATE_MODE", "warn")

# Pre-activation champion-challenger promotion gate mode for `train_model_task`.
# Mirrors ML_FAIRNESS_GATE_MODE: "warn" (default — gates run, decision recorded
# on training_metadata, model activates regardless), "block" (refuse activation
# if model_selector.promote_if_eligible reports any of the 5 gates failed —
# KS regression, PSI stability, ECE calibration, AUC regression, overfitting
# (train-vs-validation AUC gap above ML_OVERFIT_MAX_GAP)), "off" (skip the
# check entirely). Default here "warn"; production.py defaults to "block".
# See docs/superpowers/specs/2026-05-07-ml-promotion-gate-mode-design.md.
ML_PROMOTION_GATE_MODE = os.environ.get("ML_PROMOTION_GATE_MODE", "warn")

# Pre-activation validation sign-off gate mode. Mirrors the
# fairness/promotion gate pattern: "warn" (default — gate runs, decision is
# recorded, activation proceeds even with no approved ModelValidationReport),
# "block" (without an approved sign-off a training-path candidate stays
# inactive while the champion keeps serving; manual ModelActivateView returns
# 409 unless ?force=true is provided), "off" (skip the check entirely).
# Default here "warn"; production.py defaults to "block".
# See docs/superpowers/specs/2026-05-07-codex-adversarial-response-v1-10-7-design.md.
ML_VALIDATION_SIGNOFF_GATE_MODE = os.environ.get("ML_VALIDATION_SIGNOFF_GATE_MODE", "warn")

# Promotion gate 5 ceiling for the train-vs-validation AUC gap
# (training_metadata["overfitting_gap_val"]). A challenger whose gap exceeds
# this is judged overfit to the training split before the test set is ever
# read. Mirrors model_selector.MAX_OVERFIT_GAP; env-overridable per deployment.
ML_OVERFIT_MAX_GAP = _env_float("ML_OVERFIT_MAX_GAP", 0.05)

# Load a model artefact that has no stored SHA-256 (integrity check skipped
# with a warning). Off here and forced off in production.py; development.py
# turns it on so engineers can iterate on hand-made bundles.
ML_ALLOW_UNHASHED_MODELS = False

# MRM dossier auto-generation on ModelVersion post_save.
# Enabled by default; disable in unit tests that create throwaway models.
MRM_DOSSIER_AUTO_GENERATE = os.environ.get("MRM_DOSSIER_AUTO_GENERATE", "true").lower() == "true"

# Decision review (human contestability of automated decisions).
# Set DECISION_REVIEW_ENABLED=false to disable the filing endpoint instantly
# without removing the API surface (returns 503).
DECISION_REVIEW_ENABLED = os.environ.get("DECISION_REVIEW_ENABLED", "true").lower() in ("true", "1", "yes")

# Maker/checker gate on high-value officer overturns. Default here "off";
# production.py defaults to "second_approver", which blocks overturning a
# denial >= DECISION_OVERTURN_THRESHOLD at the API pending dual approval. The
# legacy value "2fa" maps to "second_approver". Unknown values collapse to
# "off" (see overturn_policy.normalize_overturn_mode).
DECISION_OVERTURN_GATE_MODE = os.environ.get("DECISION_OVERTURN_GATE_MODE", "off")
DECISION_OVERTURN_THRESHOLD = _env_float("DECISION_OVERTURN_THRESHOLD", 100000)

# Standalone single-application prediction endpoint (/ml/predict/<id>/).
# The agent orchestrator is the production decision path; the standalone task
# does NOT create an escalated AgentRun, so a borderline/drift/policy-refer
# prediction would park the application in 'review' with no resumable run and a
# stale ADM disclosure. Default OFF; flip on only for ad-hoc scoring that does
# not rely on the human-review queue.
ML_STANDALONE_PREDICT_ENABLED = os.environ.get("ML_STANDALONE_PREDICT_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)

# Security headers (applied in all environments)
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SAMESITE = "Lax"

# HSTS (HTTP Strict Transport Security) — production only
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True

# Password hashing — prefer Argon2, fall back to PBKDF2
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Field-level encryption key for PII (Fernet)
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")

if not FIELD_ENCRYPTION_KEY and not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be set in production")

# KMS abstraction for field-level encryption.
#  - "env" (default): read FIELD_ENCRYPTION_KEY from settings (current behaviour)
#  - "aws": fetch a DEK from AWS KMS via boto3.generate_data_key
#
# When KMS_BACKEND='aws':
#   - AWS_KMS_KEY_ID is required (key ID, ARN, or alias e.g. alias/loanapp-fields)
#   - KMS_DEK_TTL controls how long the fetched DEK is cached in-process (default 1h)
#
# See docs/superpowers/specs/2026-05-25-security-gap-closure-design.md.
KMS_BACKEND = os.environ.get("KMS_BACKEND", "env").lower()
AWS_KMS_KEY_ID = os.environ.get("AWS_KMS_KEY_ID", "")
KMS_DEK_TTL = _env_int("KMS_DEK_TTL", 3600)

# Email — use Gmail SMTP when credentials are set, otherwise log to console
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = _env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "aussieloanai@gmail.com")

# AI Budget Controls
AI_DAILY_CALL_LIMIT = _env_int("AI_DAILY_CALL_LIMIT", 500)
AI_DAILY_BUDGET_LIMIT_USD = _env_float("AI_DAILY_BUDGET_LIMIT_USD", 5.0)
AI_CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures before circuit opens
AI_CIRCUIT_BREAKER_COOLDOWN = 600  # seconds to keep circuit open (10 min)

# AI Temperature Settings
AI_TEMPERATURE_ANALYSIS = 0.0  # Bias detection, reviews, structured analysis
AI_TEMPERATURE_DECISION_EMAIL = 0.0  # Approval/denial emails (regulatory documents)
AI_TEMPERATURE_MARKETING = 0.2  # Marketing/retention content (slight variance for anti-spam)

# Email LLM backend — which provider writes the decision emails.
#   "anthropic" (default): paid Claude API (claude-sonnet-4-6).
#   "groq": free, OpenAI-compatible Groq (llama-3.1-8b-instant) — chosen because
#           its free tier does NOT train on prompts. See ADR 010.
#   "ollama": free, LOCAL/on-prem Ollama — no per-minute token cap (so it fits
#           the ~9k-token compliance prompts that overran Groq's free tier) and
#           nothing leaves the host, so it is NOT an APP 8 cross-border
#           disclosure. Requires the `ollama` compose service. See ADR 010.
# Either way the lending DECISION stays deterministic ML, and a missing key /
# unreachable backend degrades cleanly to the deterministic template fallback.
# EmailGenerator reads these from the environment directly; declared here for
# documentation + audit.
EMAIL_LLM_BACKEND = os.environ.get("EMAIL_LLM_BACKEND", "anthropic")
EMAIL_LLM_MODEL = os.environ.get("EMAIL_LLM_MODEL", "")  # blank -> backend default
EMAIL_LLM_SEED = _env_int("EMAIL_LLM_SEED", 0)  # reproducibility (best-effort; Groq + Ollama)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "")  # blank -> backend default (loan-email)
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")  # dummy; Ollama ignores auth

# Model for the senior bias reviewer (Head of Compliance — holistic email review).
# Blank/unset -> claude-opus-4-8. Sampling-param handling for adaptive-only
# models lives in guarded_api_call.
BIAS_REVIEWER_MODEL = os.environ.get("BIAS_REVIEWER_MODEL", "") or "claude-opus-4-8"

# Demo mode: when set, every outbound email goes to this inbox instead of the
# applicant's address.
EMAIL_REDIRECT_ALL_TO = os.environ.get("EMAIL_REDIRECT_ALL_TO", "").strip()

# Backend for the bias verdicts: "anthropic" (default) or "ollama", which runs
# every bias agent on the local Ollama server. A 3B model passed blatantly
# discriminatory text as a false positive in testing; 7B is the floor.
BIAS_LLM_BACKEND = os.environ.get("BIAS_LLM_BACKEND", "anthropic").lower()
BIAS_OLLAMA_MODEL = os.environ.get("BIAS_OLLAMA_MODEL", "") or "qwen2.5:7b"

# Bias detection thresholds (used by orchestrator pipeline)
BIAS_THRESHOLD_PASS = 30  # 0-30: compliant, email can be sent
BIAS_THRESHOLD_REVIEW = 60  # 31-60: moderate bias, LLM reviews for false positives
# 61+: high bias, escalate to human review

# Marketing-specific bias thresholds (intentionally tighter than decision thresholds)
# Rationale: marketing emails target declined customers who are in a vulnerable position.
# ASIC REP 798 flagged insufficient consumer fairness policies — stricter marketing
# bias controls demonstrate responsible AI governance for vulnerable consumers.
# Decision emails: see BIAS_THRESHOLD_PASS / BIAS_THRESHOLD_REVIEW above
# Marketing emails: AI review at 51-70, blocked at 71+ (no human override — conservative)
MARKETING_BIAS_THRESHOLD_PASS = 50  # 0-50: compliant marketing email
MARKETING_BIAS_THRESHOLD_REVIEW = 70  # 51-70: high bias, senior AI review
# 71+: blocked entirely — marketing to vulnerable declined customers requires zero bias risk

# Bias-check failure policy. When the bias check cannot RUN
# (detector construction, pre-screen crash, or an unexpected error — NOT a
# Claude LLM outage, which already falls back to the deterministic score),
# the pipeline applies this policy. Mirrors the warn/block/off pattern of the
# ML gate modes.
#   "block" (default): FAIL-SAFE — withhold the decision email, roll the
#       application back to PENDING for retry, mark the AgentRun failed, and
#       emit the bias_check_unavailable_total alert. Never auto-ships a
#       decision with bias detection effectively off.
#   "warn": log + emit the alert metric but proceed fail-open (legacy score=25).
#   "off": explicit escape hatch — legacy fail-open with no special handling.
BIAS_FAILURE_MODE = os.environ.get("BIAS_FAILURE_MODE", "block").lower()

# Agent 2: rewrites a moderate-band flagged email once under a stricter
# check (bias detector clean + senior reviewer approved with confidence)
# before handing over to the deterministic template path.
BIAS_AGENT2_ENABLED = os.environ.get("BIAS_AGENT2_ENABLED", "true").lower() == "true"
BIAS_AGENT2_MIN_REVIEWER_CONFIDENCE = 0.70
# Agent 2 is skipped (the template path takes over) when less than this many
# seconds remain before the pipeline task's soft time limit: a rewrite plus a
# bias check plus a senior review can take minutes on a slow local LLM.
BIAS_AGENT2_MIN_SECONDS_LEFT = 240

# API Documentation (drf-spectacular)
SPECTACULAR_SETTINGS = {
    "TITLE": "AussieLoanAI API",
    "DESCRIPTION": "AI-powered loan approval system with ML prediction, email generation, and bias detection for Australian lending.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1/",
    "COMPONENT_SPLIT_REQUEST": True,
    "TAGS": [
        {"name": "Auth", "description": "Authentication and user management"},
        {"name": "Loans", "description": "Loan application CRUD"},
        {"name": "ML Engine", "description": "Model training, prediction, metrics, drift"},
        {"name": "Email Engine", "description": "Email generation with guardrails"},
        {"name": "Agents", "description": "Bias detection, NBO, orchestration pipeline"},
        {"name": "System", "description": "Health checks and monitoring"},
    ],
}

# Health check token (restricts /health/deep/ when set)
HEALTH_CHECK_TOKEN = os.environ.get("HEALTH_CHECK_TOKEN", "")

# Django admin URL path (randomize in production to prevent brute-force targeting)
DJANGO_ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "admin/")

# Sentry error tracking (no-op when SENTRY_DSN is empty)
_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,
        # Request bodies and frame locals hold passwords and applicant PII,
        # and send_default_pii=False does not stop the SDK sending them.
        max_request_body_size="never",
        include_local_variables=False,
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
    )

# Logging — wire the PII masking filter on the console in BASE settings so
# development and Docker (which inherit these) also redact PII from logs, not
# just production. production.py overrides LOGGING with its JSON/correlation-id
# variant (which also installs mask_pii). disable_existing_loggers=False keeps
# third-party + pytest log capture intact.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "filters": {
        "mask_pii": {"()": "config.logging_filters.PiiMaskingFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["mask_pii"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
}

# Validate environment variables on startup (fail fast if required vars are missing).
# Skipped during tests and when SKIP_ENV_VALIDATION=1.
import config.env_validation  # noqa: E402, F401
