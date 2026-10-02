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
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    if "test" in settings_module:
        return

    if os.environ.get("SKIP_ENV_VALIDATION") == "1":
        return

    # NOTE: we intentionally do NOT skip in DEBUG mode. Skipping all checks
    # when DJANGO_DEBUG=True creates a risk that a misconfigured production
    # deployment (where DEBUG was accidentally set to True) bypasses secret
    # validation entirely. Required vars are always checked; only the optional
    # warnings are gated on the non-debug path.
    #
    # This runs while base.py is importing, before production.py forces
    # DEBUG=False, so the env var alone cannot say whether this is production:
    # under the production settings module the non-debug checks always run.
    is_production = settings_module.endswith(".production")
    is_debug = not is_production and os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")

    missing = []

    # --- Always required (even in DEBUG mode) ---

    # Django secret key (hard requirement in all environments)
    if not os.environ.get("DJANGO_SECRET_KEY"):
        missing.append("DJANGO_SECRET_KEY")

    # Field encryption key (Fernet) — required whenever the DB is reachable
    if not os.environ.get("FIELD_ENCRYPTION_KEY"):
        missing.append("FIELD_ENCRYPTION_KEY")

    # --- Required outside of test/CI mode ---
    # Only what settings actually read: base.py builds DATABASES from POSTGRES_*
    # and the broker/cache from CELERY_BROKER_URL. DATABASE_URL, REDIS_URL and
    # REDIS_PASSWORD are not read, so accepting them let a deployment pass
    # validation and then connect to the localhost defaults.
    if not is_debug:
        for var in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "CELERY_BROKER_URL"):
            if not os.environ.get(var):
                missing.append(var)

    if missing:
        from django.core.exceptions import ImproperlyConfigured

        formatted = "\n  - ".join(missing)
        raise ImproperlyConfigured(
            f"Missing required environment variable(s):\n  - {formatted}\n"
            "Set them in your .env file or export them before starting the server."
        )

    # --- Optional but warned (only in non-debug mode to avoid noisy dev logs) ---
    if not is_debug:
        optional_warned = {
            "ANTHROPIC_API_KEY": "Claude API calls (email generation, bias detection) will fail",
            "EMAIL_HOST_USER": "Outbound email delivery will fail",
            "EMAIL_HOST_PASSWORD": "Outbound email delivery will fail",
        }

        # When the email backend is set to Groq, warn (don't block) on a missing
        # key — a missing key degrades cleanly to the deterministic template path.
        if os.environ.get("EMAIL_LLM_BACKEND", "").lower() == "groq":
            optional_warned["GROQ_API_KEY"] = "Groq email generation will fall back to deterministic templates"

        for var, consequence in optional_warned.items():
            if not os.environ.get(var):
                logger.warning("Environment variable %s is not set — %s.", var, consequence)

        # The senior bias reviewer always calls the Anthropic API; a non-Claude
        # model ID (e.g. an Ollama tag) would 404 every senior review, silently
        # degrading to human escalation and feeding the shared circuit breaker.
        reviewer_model = os.environ.get("BIAS_REVIEWER_MODEL", "")
        if reviewer_model and not reviewer_model.startswith(("claude-", "anthropic.", "us.anthropic.")):
            logger.warning(
                "BIAS_REVIEWER_MODEL=%r does not look like an Anthropic model ID — "
                "senior bias reviews will fail and fall back to human escalation.",
                reviewer_model,
            )


# A Django SECRET_KEY shorter than this, or containing a placeholder word, is
# refused in production (Django's own check --deploy uses 50 as the floor).
MIN_SECRET_KEY_LENGTH = 50
_PLACEHOLDER_MARKERS = ("change", "django-insecure", "placeholder", "example")


def validate_production_secrets(*, secret_key, field_encryption_key, kms_backend):
    """Refuse to start production with placeholder or malformed secrets.

    Called from config/settings/production.py, after DEBUG is final. Dev and
    test settings never call it. ``k8s/secrets.yaml`` ships "CHANGE_ME" for
    both secrets, which this rejects until real values are set.
    """
    from django.core.exceptions import ImproperlyConfigured

    lowered = (secret_key or "").lower()
    if len(secret_key or "") < MIN_SECRET_KEY_LENGTH or any(m in lowered for m in _PLACEHOLDER_MARKERS):
        raise ImproperlyConfigured(
            f"DJANGO_SECRET_KEY must be a random value of at least {MIN_SECRET_KEY_LENGTH} characters with no "
            'placeholder text. Generate one with: python -c "from django.core.management.utils import '
            'get_random_secret_key; print(get_random_secret_key())"'
        )

    if kms_backend == "env":
        keys = [k.strip() for k in (field_encryption_key or "").split(",") if k.strip()]
        if not keys:
            raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be set in production (KMS_BACKEND=env).")
        from cryptography.fernet import Fernet

        for position, key in enumerate(keys, start=1):
            try:
                Fernet(key.encode())
            except (ValueError, TypeError) as exc:
                raise ImproperlyConfigured(
                    f"FIELD_ENCRYPTION_KEY entry {position} is not a valid Fernet key. Generate one with: "
                    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                ) from exc


validate_env()
