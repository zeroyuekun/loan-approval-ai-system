"""TTL behavior for the ML model cache."""
import time
from unittest.mock import MagicMock, patch


def _make_mock_version(pk=1, path="/tmp/fake.joblib", file_hash=None):
    v = MagicMock()
    v.id = pk
    v.file_path = path
    v.file_hash = file_hash
    return v


class TestModelCacheTTL:
    def setup_method(self):
        from apps.ml_engine.services import predictor
        predictor.clear_model_cache()

    @patch("apps.ml_engine.services.predictor._verify_model_hash")
    @patch("apps.ml_engine.services.predictor._validate_model_path")
    @patch("apps.ml_engine.services.predictor.joblib.load")
    def test_cache_reloads_after_ttl(self, mock_load, mock_validate, mock_verify):
        from apps.ml_engine.services import predictor

        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [
            {"model": "A"},
            {"model": "B"},
        ]
        version = _make_mock_version(pk=1)

        # First load -> cache miss, calls joblib.load
        assert predictor._load_bundle(version) == {"model": "A"}
        # Second load within TTL -> cache hit, no new joblib.load
        assert predictor._load_bundle(version) == {"model": "A"}
        assert mock_load.call_count == 1

        # Expire cache manually (TTL-aware cache must support this)
        predictor._model_cache.expire(time=time.time() + 10_000)

        # Third load after expiry -> cache miss, joblib.load called again
        assert predictor._load_bundle(version) == {"model": "B"}
        assert mock_load.call_count == 2

    @patch("apps.ml_engine.services.predictor._verify_model_hash")
    @patch("apps.ml_engine.services.predictor._validate_model_path")
    @patch("apps.ml_engine.services.predictor.joblib.load")
    def test_cache_bounded_to_maxsize(self, mock_load, mock_validate, mock_verify):
        from apps.ml_engine.services import predictor

        mock_validate.return_value = "/tmp/fake.joblib"
        mock_load.side_effect = [{"m": i} for i in range(10)]

        for i in range(5):
            v = _make_mock_version(pk=i)
            predictor._load_bundle(v)

        # TTLCache with maxsize=3 should never hold more than 3 entries
        assert len(predictor._model_cache) <= 3
