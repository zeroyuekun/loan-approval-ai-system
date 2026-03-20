"""
Base settings for loan approval AI system.
"""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')

_secret_key = os.environ.get('DJANGO_SECRET_KEY', '')
if not _secret_key and not DEBUG:
    raise ValueError(
        'DJANGO_SECRET_KEY environment variable must be set in production (DEBUG=False). '
        'Generate one with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
    )
SECRET_KEY = _secret_key or 'django-insecure-dev-key-change-in-production'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'django_celery_results',
    # Local apps
    'apps.accounts',
    'apps.loans',
    'apps.ml_engine',
    'apps.email_engine',
    'apps.agents',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'loan_approval'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': 600,
        'CONN_HEALTH_CHECKS': True,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'accounts.CustomUser'

LANGUAGE_CODE = 'en-au'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'apps.accounts.authentication.CookieJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/min',
        'user': '60/min',
    },
}

# Simple JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# JWT Cookie settings (HttpOnly cookies instead of localStorage)
JWT_COOKIE_SECURE = not DEBUG  # Secure flag in production
JWT_COOKIE_SAMESITE = 'Lax'
JWT_COOKIE_HTTPONLY = True
JWT_ACCESS_COOKIE_NAME = 'access_token'
JWT_REFRESH_COOKIE_NAME = 'refresh_token'

# CORS
CORS_ALLOWED_ORIGINS = os.environ.get(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:3000,http://127.0.0.1:3000'
).split(',')
CORS_ALLOW_CREDENTIALS = True

# CSRF trusted origins (must match CORS origins for cookie-based auth)
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS[:]
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False  # Frontend JS needs to read CSRF token

# Celery
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_ROUTES = {
    'apps.ml_engine.tasks.*': {'queue': 'ml'},
    'apps.email_engine.tasks.*': {'queue': 'email'},
    'apps.agents.tasks.*': {'queue': 'agents'},
}

# Django Cache (Redis-backed)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0').replace('/0', '/1'),
        'TIMEOUT': 300,  # 5 minutes default TTL
    }
}

# ML Models
ML_MODELS_DIR = BASE_DIR / 'ml_models'

# Security headers (applied in all environments)
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Password hashing — prefer Argon2, fall back to PBKDF2
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# Field-level encryption key for PII (Fernet)
FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')

# Email (Gmail SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'aussieloanai@gmail.com')

# AI Budget Controls
AI_DAILY_CALL_LIMIT = int(os.environ.get('AI_DAILY_CALL_LIMIT', '500'))
AI_DAILY_BUDGET_LIMIT_USD = float(os.environ.get('AI_DAILY_BUDGET_LIMIT_USD', '50.0'))
AI_CIRCUIT_BREAKER_THRESHOLD = 3   # consecutive failures before circuit opens
AI_CIRCUIT_BREAKER_COOLDOWN = 600  # seconds to keep circuit open (10 min)

# AI Temperature Settings
AI_TEMPERATURE_ANALYSIS = 0.0       # Bias detection, reviews, structured analysis
AI_TEMPERATURE_DECISION_EMAIL = 0.0  # Approval/denial emails (regulatory documents)
AI_TEMPERATURE_MARKETING = 0.2       # Marketing/retention content (slight variance for anti-spam)

# Bias detection thresholds (used by orchestrator pipeline)
BIAS_THRESHOLD_PASS = 60       # 0-60: compliant, email can be sent
BIAS_THRESHOLD_REVIEW = 80     # 61-80: high bias, AI review then human escalation
# 81+: severe bias, direct human escalation

# Marketing-specific bias thresholds (tighter — declined customers are vulnerable)
MARKETING_BIAS_THRESHOLD_PASS = 50    # 0-50: compliant marketing email
MARKETING_BIAS_THRESHOLD_REVIEW = 70  # 51-70: high bias, senior review (Opus)
# 71+: blocked, marketing email not sent
