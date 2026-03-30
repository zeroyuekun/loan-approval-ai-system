"""
Environment variable validation — fail fast on startup if required vars are missing.

Imported at the bottom of config/settings/base.py so it runs during Django startup.
Skipped entirely when:
  - DJANGO_SETTINGS_MODULE contains 'test'
  - SKIP_ENV_VALIDATION=1
"""

import logging
import os

logger = logging.getLogger(__name__)


def validate_env():
    settings_module = os.environ.get('DJANGO_SETTINGS_MODULE', '')
    if 'test' in settings_module:
        return

    if os.environ.get('SKIP_ENV_VALIDATION') == '1':
        return

    # Skip in DEBUG mode — dev environments may not have all vars set
    is_debug = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')
    if is_debug:
        return

    missing = []

    # --- Required variables ---

    # Django secret key (hard requirement in all environments)
    if not os.environ.get('DJANGO_SECRET_KEY'):
        missing.append('DJANGO_SECRET_KEY')

    # Database: need either DATABASE_URL or the individual Postgres vars
    has_database_url = bool(os.environ.get('DATABASE_URL'))
    has_pg_individual = all(
        os.environ.get(v) for v in ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD')
    )
    if not has_database_url and not has_pg_individual:
        missing.append(
            'DATABASE_URL or (POSTGRES_DB + POSTGRES_USER + POSTGRES_PASSWORD)'
        )

    # Redis: need either REDIS_URL / CELERY_BROKER_URL or REDIS_PASSWORD
    has_redis_url = bool(
        os.environ.get('REDIS_URL') or os.environ.get('CELERY_BROKER_URL')
    )
    has_redis_password = bool(os.environ.get('REDIS_PASSWORD'))
    if not has_redis_url and not has_redis_password:
        missing.append('REDIS_URL (or CELERY_BROKER_URL) or REDIS_PASSWORD')

    # Field encryption key (Fernet)
    if not os.environ.get('FIELD_ENCRYPTION_KEY'):
        missing.append('FIELD_ENCRYPTION_KEY')

    if missing:
        from django.core.exceptions import ImproperlyConfigured

        formatted = '\n  - '.join(missing)
        raise ImproperlyConfigured(
            f"Missing required environment variable(s):\n  - {formatted}\n"
            "Set them in your .env file or export them before starting the server."
        )

    # --- Optional but warned ---
    optional_warned = {
        'ANTHROPIC_API_KEY': 'Claude API calls (email generation, bias detection) will fail',
        'EMAIL_HOST_USER': 'Outbound email delivery will fail',
        'EMAIL_HOST_PASSWORD': 'Outbound email delivery will fail',
    }

    for var, consequence in optional_warned.items():
        if not os.environ.get(var):
            logger.warning(
                "Environment variable %s is not set — %s.", var, consequence
            )


validate_env()
