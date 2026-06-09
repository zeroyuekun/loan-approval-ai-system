"""Tests for the training-data self-heal guard in ml_engine.tasks.

"Train Model" reads the disposable .tmp/synthetic_loans.csv. That file is
gitignored and absent on a fresh clone or after .tmp is cleared, which used to
make training die with a cryptic FileNotFoundError deep in the trainer. The
guard auto-generates a synthetic dataset on demand instead.

The sync `train_model` management command also self-heals; the segment training
path shares `_do_train`, so the wiring test pins that the guard runs before the
trainer regardless of caller.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

import apps.ml_engine.tasks as tasks_mod
from apps.ml_engine.tasks import _ensure_training_data

_FAKE_DF = pd.DataFrame({"approved": [0, 1] * 10})


def test_generates_synthetic_csv_when_missing(tmp_path):
    target = tmp_path / "seed" / "synthetic_loans.csv"
    assert not target.exists()

    generated = _ensure_training_data(str(target), num_records=200)

    assert generated is True
    assert target.exists()
    df = pd.read_csv(target)
    # Must be a TRAINABLE dataset, not just a non-empty file: the trainer needs
    # >=20 rows and >=5 samples in each class of the `approved` label.
    assert len(df) == 200
    assert "approved" in df.columns
    assert df["approved"].nunique() == 2
    assert df["approved"].value_counts().min() >= 5


def test_noop_when_csv_already_present(tmp_path):
    target = tmp_path / "synthetic_loans.csv"
    target.write_text("sentinel,row\n1,2\n")

    generated = _ensure_training_data(str(target), num_records=100)

    assert generated is False
    # Existing data must never be overwritten.
    assert target.read_text() == "sentinel,row\n1,2\n"


def test_zero_byte_csv_is_treated_as_missing(tmp_path, monkeypatch):
    # A torn/interrupted write can leave a 0-byte file. os.path.exists() returns
    # True for it, so an existence-only check would trust it forever and break
    # every future run. The guard must regenerate instead.
    target = tmp_path / "synthetic_loans.csv"
    target.write_bytes(b"")
    monkeypatch.setattr(
        "apps.ml_engine.services.datagen.data_generator.DataGenerator.generate",
        lambda self, num_records=50000, **k: _FAKE_DF.copy(),
    )

    generated = _ensure_training_data(str(target), num_records=20)

    assert generated is True
    df = pd.read_csv(target)
    assert len(df) > 0


def test_uses_setting_default_when_num_records_omitted(tmp_path, settings, monkeypatch):
    # The wired path calls _ensure_training_data(data_path) with no num_records,
    # so ML_AUTO_SEED_ROWS must flow through to the generator.
    settings.ML_AUTO_SEED_ROWS = 7
    captured = {}

    def fake_generate(self, num_records=50000, **kwargs):
        captured["n"] = num_records
        return _FAKE_DF.copy()

    monkeypatch.setattr(
        "apps.ml_engine.services.datagen.data_generator.DataGenerator.generate",
        fake_generate,
    )

    _ensure_training_data(str(tmp_path / "synthetic_loans.csv"))

    assert captured["n"] == 7


def test_do_train_self_heals_before_training(settings, monkeypatch):
    # Regression guard for the core contract: _do_train must call the self-heal
    # with the default BASE_DIR path BEFORE invoking the trainer. A refactor that
    # drops or reorders the guard must turn this test red.
    calls = []
    monkeypatch.setattr(tasks_mod, "_ensure_training_data", lambda p, *a, **k: calls.append(("ensure", p)) or False)

    class _Boom(Exception):
        pass

    def _boom_train(self, *a, **k):
        calls.append(("train",))
        raise _Boom()

    monkeypatch.setattr("apps.ml_engine.services.training.trainer.ModelTrainer.train", _boom_train)

    with pytest.raises(_Boom):
        tasks_mod._do_train(None, "xgb", None, MagicMock())

    assert calls[0] == ("ensure", str(settings.BASE_DIR / ".tmp" / "synthetic_loans.csv"))
    assert calls[1] == ("train",)
