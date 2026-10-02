"""Governance gates fail closed under production settings.

base.py defaults every gate to an advisory mode (warn / shadow / off) so local
training and the demo never get stuck, and production.py set none of them, so
production ran advisory-only: the live champion was serving with a failed
fairness gate. Owner decision: production defaults to the blocking mode of
every gate, with env overrides allowed; development keeps its defaults.
An unknown value in production is a start-up error, not a silent downgrade.
"""

import os
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet

GOOD_SECRET = "k" * 20 + "Zq9-x7Rt2pLw4vNs8yBd3mFh6jKc1gTa"
PROD_ENV = {
    "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "DJANGO_SECRET_KEY": GOOD_SECRET,
    "FIELD_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "KMS_BACKEND": "env",
    "POSTGRES_DB": "loan",
    "POSTGRES_USER": "u",
    "POSTGRES_PASSWORD": "p",
    "CELERY_BROKER_URL": "redis://:p@redis:6379/0",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
}
GATES = (
    "ML_FAIRNESS_GATE_MODE",
    "ML_PROMOTION_GATE_MODE",
    "ML_VALIDATION_SIGNOFF_GATE_MODE",
    "CREDIT_POLICY_OVERLAY_MODE",
    "DECISION_OVERTURN_GATE_MODE",
    "BIAS_FAILURE_MODE",
    "ML_ALLOW_UNHASHED_MODELS",
    "ENFORCE_2FA_FOR_STAFF",
)


def _settings(module, **env):
    child_env = {k: v for k, v in os.environ.items() if k not in GATES}
    child_env.update({"DJANGO_SETTINGS_MODULE": module, **env})
    code = (
        "import django; from django.conf import settings; django.setup(); "
        f"print(' '.join(str(getattr(settings, n)) for n in {GATES!r}))"
    )
    return subprocess.run(  # noqa: S603 — fixed argv: this interpreter + a literal snippet
        [sys.executable, "-c", code], env=child_env, capture_output=True, text=True, timeout=120, check=False
    )


def _values(result):
    assert result.returncode == 0, result.stderr[-2000:]
    return dict(zip(GATES, result.stdout.split()[-len(GATES) :], strict=True))


def test_production_gates_default_to_block():
    assert _values(_settings("config.settings.production", **PROD_ENV)) == {
        "ML_FAIRNESS_GATE_MODE": "block",
        "ML_PROMOTION_GATE_MODE": "block",
        "ML_VALIDATION_SIGNOFF_GATE_MODE": "block",
        "CREDIT_POLICY_OVERLAY_MODE": "enforce",
        "DECISION_OVERTURN_GATE_MODE": "second_approver",
        "BIAS_FAILURE_MODE": "block",
        "ML_ALLOW_UNHASHED_MODELS": "False",
        "ENFORCE_2FA_FOR_STAFF": "True",
    }


def test_production_gates_accept_an_env_override():
    values = _values(
        _settings(
            "config.settings.production", **PROD_ENV, ML_FAIRNESS_GATE_MODE="warn", CREDIT_POLICY_OVERLAY_MODE="shadow"
        )
    )
    assert values["ML_FAIRNESS_GATE_MODE"] == "warn"
    assert values["CREDIT_POLICY_OVERLAY_MODE"] == "shadow"
    assert values["ML_PROMOTION_GATE_MODE"] == "block"


def test_an_empty_env_value_means_the_production_default():
    """compose passes ${VAR:-} as an empty string when unset."""
    values = _values(_settings("config.settings.production", **PROD_ENV, ML_VALIDATION_SIGNOFF_GATE_MODE=""))
    assert values["ML_VALIDATION_SIGNOFF_GATE_MODE"] == "block"


def test_production_enforces_staff_2fa_unless_explicitly_disabled():
    """Staff 2FA is a fail-closed control: empty means the production default."""
    assert _values(_settings("config.settings.production", **PROD_ENV, ENFORCE_2FA_FOR_STAFF=""))[
        "ENFORCE_2FA_FOR_STAFF"
    ] == "True"
    assert _values(_settings("config.settings.production", **PROD_ENV, ENFORCE_2FA_FOR_STAFF="false"))[
        "ENFORCE_2FA_FOR_STAFF"
    ] == "False"


@pytest.mark.parametrize("name", ["ML_FAIRNESS_GATE_MODE", "CREDIT_POLICY_OVERLAY_MODE", "DECISION_OVERTURN_GATE_MODE"])
def test_production_refuses_to_start_with_an_unknown_gate_mode(name):
    result = _settings("config.settings.production", **PROD_ENV, **{name: "blcok"})
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert f"{name}='blcok'" in result.stderr


def test_production_never_loads_an_unhashed_model_even_with_debug_in_the_env():
    """M7: the hash check decided dev-vs-prod from the DJANGO_DEBUG env var."""
    values = _values(_settings("config.settings.production", **PROD_ENV, DJANGO_DEBUG="true"))
    assert values["ML_ALLOW_UNHASHED_MODELS"] == "False"


def test_development_keeps_its_advisory_defaults():
    assert _values(_settings("config.settings.development", DJANGO_DEBUG="")) == {
        "ML_FAIRNESS_GATE_MODE": "warn",
        "ML_PROMOTION_GATE_MODE": "warn",
        "ML_VALIDATION_SIGNOFF_GATE_MODE": "warn",
        "CREDIT_POLICY_OVERLAY_MODE": "shadow",
        "DECISION_OVERTURN_GATE_MODE": "off",
        "BIAS_FAILURE_MODE": "block",
        "ML_ALLOW_UNHASHED_MODELS": "True",
        "ENFORCE_2FA_FOR_STAFF": "False",
    }
