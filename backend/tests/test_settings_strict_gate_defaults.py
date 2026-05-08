"""Pin the strict default gate modes in base settings.

Defaults must be enforcement-by-default so a non-compliant model cannot
silently activate. Env vars can still relax the modes for emergency
rollback.
"""

import importlib

import pytest


def test_credit_policy_overlay_mode_default_is_enforce(monkeypatch):
    monkeypatch.delenv("CREDIT_POLICY_OVERLAY_MODE", raising=False)
    from config.settings import base
    importlib.reload(base)
    assert base.CREDIT_POLICY_OVERLAY_MODE == "enforce"


def test_ml_fairness_gate_mode_default_is_block(monkeypatch):
    monkeypatch.delenv("ML_FAIRNESS_GATE_MODE", raising=False)
    from config.settings import base
    importlib.reload(base)
    assert base.ML_FAIRNESS_GATE_MODE == "block"


def test_ml_promotion_gate_mode_default_is_block(monkeypatch):
    monkeypatch.delenv("ML_PROMOTION_GATE_MODE", raising=False)
    from config.settings import base
    importlib.reload(base)
    assert base.ML_PROMOTION_GATE_MODE == "block"


def test_env_var_override_still_works(monkeypatch):
    """An operator setting ML_FAIRNESS_GATE_MODE=warn must still see warn."""
    monkeypatch.setenv("ML_FAIRNESS_GATE_MODE", "warn")
    from config.settings import base
    importlib.reload(base)
    assert base.ML_FAIRNESS_GATE_MODE == "warn"
