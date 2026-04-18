"""Unit tests for prediction-cache helpers extracted from predictor.py.

Covers the module-level model-loading cache (TTLCache + lock), the integrity
and path-safety helpers, and `clear_model_cache()`. These were previously
free functions on the predictor module; they've been pulled into their own
module so predictor.py stays focused on orchestration.

The existing `backend/tests/test_predictor_cache.py` is the integration test
that exercises the same surface via the re-exports on `predictor`; this file
targets `prediction_cache` directly.
"""

from __future__ import annotations

import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest

from apps.ml_engine.services import prediction_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    prediction_cache.clear_model_cache()
    yield
    prediction_cache.clear_model_cache()


def _make_mock_version(pk=1, path="/tmp/fake.joblib", file_hash=None):
    v = MagicMock()
    v.id = pk
    v.file_path = path
    v.file_hash = file_hash
    return v


# ---------------------------------------------------------------------------
# _validate_model_path
# ---------------------------------------------------------------------------


class TestValidateModelPath:
    def test_rejects_path_outside_models_dir(self, tmp_path, settings):
        settings.ML_MODELS_DIR = str(tmp_path)
        outside_dir = tmp_path.parent / "evil"
        outside_dir.mkdir(exist_ok=True)
        outside = outside_dir / "evil.joblib"
        outside.write_bytes(b"")
        with pytest.raises(ValueError, match="outside"):
            prediction_cache._validate_model_path(str(outside))

    def test_rejects_wrong_suffix(self, tmp_path, settings):
        settings.ML_MODELS_DIR = str(tmp_path)
        wrong = tmp_path / "model.pkl"
        wrong.write_bytes(b"")
        with pytest.raises(ValueError, match=".joblib"):
            prediction_cache._validate_model_path(str(wrong))

    def test_rejects_missing_file(self, tmp_path, settings):
        settings.ML_MODELS_DIR = str(tmp_path)
        missing = tmp_path / "ghost.joblib"
        with pytest.raises(FileNotFoundError):
            prediction_cache._validate_model_path(str(missing))

    def test_accepts_valid_path(self, tmp_path, settings):
        settings.ML_MODELS_DIR = str(tmp_path)
        good = tmp_path / "good.joblib"
        good.write_bytes(b"")
        result = prediction_cache._validate_model_path(str(good))
        assert result == good.resolve()


# ---------------------------------------------------------------------------
# _verify_model_hash
# ---------------------------------------------------------------------------


class TestVerifyModelHash:
    def test_missing_expected_hash_skips_check(self, tmp_path):
        f = tmp_path / "m.joblib"
        f.write_bytes(b"contents")
        # Should not raise — caller just gets a warning log.
        prediction_cache._verify_model_hash(f, None)
        prediction_cache._verify_model_hash(f, "")

    def test_matching_hash_passes(self, tmp_path):
        f = tmp_path / "m.joblib"
        payload = b"hello-world"
        f.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        prediction_cache._verify_model_hash(f, expected)

    def test_mismatched_hash_raises(self, tmp_path):
        f = tmp_path / "m.joblib"
        f.write_bytes(b"hello-world")
        with pytest.raises(ValueError, match="integrity check failed"):
            prediction_cache._verify_model_hash(f, "0" * 64)


# ---------------------------------------------------------------------------
# _load_bundle + clear_model_cache
# ---------------------------------------------------------------------------


class TestLoadBundle:
    @patch("apps.ml_engine.services.prediction_cache._verify_model_hash")
    @patch("apps.ml_engine.services.prediction_cache._validate_model_path")
    @patch("apps.ml_engine.services.prediction_cache.joblib.load")
    def test_cache_hit_avoids_repeat_load(self, mock_load, mock_validate, mock_verify):
        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [{"model": "A"}, {"model": "B"}]
        version = _make_mock_version(pk=1)

        assert prediction_cache._load_bundle(version) == {"model": "A"}
        assert prediction_cache._load_bundle(version) == {"model": "A"}
        assert mock_load.call_count == 1

    @patch("apps.ml_engine.services.prediction_cache._verify_model_hash")
    @patch("apps.ml_engine.services.prediction_cache._validate_model_path")
    @patch("apps.ml_engine.services.prediction_cache.joblib.load")
    def test_cache_reloads_after_ttl(self, mock_load, mock_validate, mock_verify):
        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [{"model": "A"}, {"model": "B"}]
        version = _make_mock_version(pk=1)

        assert prediction_cache._load_bundle(version) == {"model": "A"}

        prediction_cache._model_cache.expire(time=time.time() + 10_000)

        assert prediction_cache._load_bundle(version) == {"model": "B"}
        assert mock_load.call_count == 2

    @patch("apps.ml_engine.services.prediction_cache._verify_model_hash")
    @patch("apps.ml_engine.services.prediction_cache._validate_model_path")
    @patch("apps.ml_engine.services.prediction_cache.joblib.load")
    def test_cache_bounded_to_maxsize(self, mock_load, mock_validate, mock_verify):
        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [{"m": i} for i in range(10)]

        for i in range(5):
            prediction_cache._load_bundle(_make_mock_version(pk=i))

        assert len(prediction_cache._model_cache) <= prediction_cache._MAX_CACHE_ENTRIES

    @patch("apps.ml_engine.services.prediction_cache._verify_model_hash")
    @patch("apps.ml_engine.services.prediction_cache._validate_model_path")
    @patch("apps.ml_engine.services.prediction_cache.joblib.load")
    def test_clear_model_cache_empties(self, mock_load, mock_validate, mock_verify):
        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.return_value = {"model": "A"}

        prediction_cache._load_bundle(_make_mock_version(pk=1))
        assert len(prediction_cache._model_cache) == 1

        prediction_cache.clear_model_cache()
        assert len(prediction_cache._model_cache) == 0
