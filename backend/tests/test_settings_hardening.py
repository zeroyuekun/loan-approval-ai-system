"""Settings ordering, env validation and production secret checks.

- JWT_COOKIE_SECURE was computed in base.py from the DJANGO_DEBUG env var,
  before production.py forced DEBUG=False, and production never re-set it:
  DJANGO_DEBUG=true in a production env shipped the auth cookies without
  Secure. The inverse held for development (SSL redirect / HSTS from env).
- env_validation accepted DATABASE_URL / REDIS_URL / REDIS_PASSWORD, which
  settings never read (they read POSTGRES_* and CELERY_BROKER_URL).
- Production started with a placeholder or short DJANGO_SECRET_KEY and did
  not check that FIELD_ENCRYPTION_KEY is a real Fernet key.
"""

import os
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from config.env_validation import validate_env, validate_production_secrets

GOOD_SECRET = "k" * 20 + "Zq9-x7Rt2pLw4vNs8yBd3mFh6jKc1gTa"  # 52 chars, no placeholder words
FERNET = Fernet.generate_key().decode()


# --- production secret checks -------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    ["CHANGE_ME", "please-change-this-" + "x" * 40, "short-but-random-Zq9x7Rt2", "", "django-insecure-" + "a" * 50],
)
def test_production_refuses_placeholder_or_short_secret_key(secret):
    with pytest.raises(ImproperlyConfigured):
        validate_production_secrets(secret_key=secret, field_encryption_key=FERNET, kms_backend="env")


@pytest.mark.parametrize("key", ["CHANGE_ME", "not-a-fernet-key", "", f"{FERNET},CHANGE_ME"])
def test_production_refuses_a_field_key_that_is_not_fernet(key):
    with pytest.raises(ImproperlyConfigured):
        validate_production_secrets(secret_key=GOOD_SECRET, field_encryption_key=key, kms_backend="env")


def test_production_accepts_real_secrets_and_rotation_lists():
    validate_production_secrets(
        secret_key=GOOD_SECRET, field_encryption_key=f"{FERNET},{Fernet.generate_key().decode()}", kms_backend="env"
    )


def test_aws_kms_backend_does_not_need_a_local_fernet_key():
    validate_production_secrets(secret_key=GOOD_SECRET, field_encryption_key="", kms_backend="aws")


# --- env validation checks what settings read ----------------------------------


def _env(monkeypatch, **values):
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "REDIS_PASSWORD",
        "CELERY_BROKER_URL",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SKIP_ENV_VALIDATION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.production")
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.setenv("DJANGO_SECRET_KEY", GOOD_SECRET)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", FERNET)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_env_validation_rejects_vars_settings_never_read(monkeypatch):
    _env(monkeypatch, DATABASE_URL="postgres://u:p@db/x", REDIS_URL="redis://r:6379/0", REDIS_PASSWORD="x")
    with pytest.raises(ImproperlyConfigured) as exc:
        validate_env()
    assert "POSTGRES_DB" in str(exc.value)
    assert "CELERY_BROKER_URL" in str(exc.value)


def test_env_validation_accepts_what_settings_read(monkeypatch):
    _env(
        monkeypatch,
        POSTGRES_DB="loan",
        POSTGRES_USER="u",
        POSTGRES_PASSWORD="p",
        CELERY_BROKER_URL="redis://:p@redis:6379/0",
    )
    validate_env()


def test_env_validation_is_not_relaxed_by_debug_env_under_production_settings(monkeypatch):
    _env(monkeypatch, DJANGO_DEBUG="true")
    with pytest.raises(ImproperlyConfigured):
        validate_env()


# --- settings modules, loaded fresh in a subprocess ----------------------------


def _load_settings(module, **env):
    child_env = {**os.environ, "DJANGO_SETTINGS_MODULE": module, **env}
    code = (
        "import django; from django.conf import settings; django.setup(); "
        "print(settings.JWT_COOKIE_SECURE, settings.SECURE_SSL_REDIRECT, settings.SECURE_HSTS_SECONDS)"
    )
    return subprocess.run(  # noqa: S603 — fixed argv: this interpreter + a literal snippet
        [sys.executable, "-c", code], env=child_env, capture_output=True, text=True, timeout=120, check=False
    )


PROD_ENV = {
    "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "DJANGO_SECRET_KEY": GOOD_SECRET,
    "FIELD_ENCRYPTION_KEY": FERNET,
    "KMS_BACKEND": "env",
    "POSTGRES_DB": "loan",
    "POSTGRES_USER": "u",
    "POSTGRES_PASSWORD": "p",
    "CELERY_BROKER_URL": "redis://:p@redis:6379/0",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
}


def test_production_cookies_are_secure_even_with_debug_in_the_env():
    result = _load_settings("config.settings.production", DJANGO_DEBUG="true", **PROD_ENV)
    assert result.returncode == 0, result.stderr[-2000:]
    secure, ssl_redirect, _ = result.stdout.split()[-3:]
    assert secure == "True"
    assert ssl_redirect == "True"


def test_production_refuses_to_start_with_the_k8s_placeholder_secret():
    result = _load_settings("config.settings.production", **{**PROD_ENV, "DJANGO_SECRET_KEY": "CHANGE_ME"})
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_development_is_plain_http_even_without_debug_in_the_env():
    result = _load_settings("config.settings.development", DJANGO_DEBUG="")
    assert result.returncode == 0, result.stderr[-2000:]
    secure, ssl_redirect, hsts = result.stdout.split()[-3:]
    assert (secure, ssl_redirect, hsts) == ("False", "False", "0")
