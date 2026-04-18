"""Model-bundle loading cache used by the prediction hot path.

This module owns the TTL cache, lock, path-safety check, hash-integrity check,
and the double-checked-locking loader that the predictor calls when resolving
a model version to an in-memory bundle. It was extracted from `predictor.py`
(Arm C Phase 1) so the predictor itself focuses on orchestration.

The cache is a `cachetools.TTLCache` — entries auto-evict on `_CACHE_TTL_SECONDS`
and the max size caps resident memory. A single module-level lock guards the
cache across threads so concurrent first-loads of the same version don't burn
duplicate joblib reads.

`predictor.py` re-exports the public names (`_model_cache`, `_cache_lock`,
`_load_bundle`, `clear_model_cache`, `_validate_model_path`, `_verify_model_hash`)
so existing callers and test patches keep working.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

import joblib
from cachetools import TTLCache
from django.conf import settings

__all__ = [
    "_MAX_CACHE_ENTRIES",
    "_CACHE_TTL_SECONDS",
    "_model_cache",
    "_cache_lock",
    "_validate_model_path",
    "_verify_model_hash",
    "_load_bundle",
    "clear_model_cache",
]

logger = logging.getLogger(__name__)


# Module-level cache for loaded model bundles, keyed by model version ID.
# TTLCache auto-evicts entries older than _CACHE_TTL_SECONDS and enforces
# maxsize (LRU), preventing unbounded memory growth and serving stale models.
_MAX_CACHE_ENTRIES = 3
_CACHE_TTL_SECONDS = 3600  # 1 hour
_model_cache: TTLCache = TTLCache(maxsize=_MAX_CACHE_ENTRIES, ttl=_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()


def _validate_model_path(file_path):
    """Validate that the model file path is safe to load."""
    models_dir = Path(settings.ML_MODELS_DIR).resolve()
    resolved = Path(file_path).resolve()

    if not resolved.is_relative_to(models_dir):
        raise ValueError(f"Model file path '{file_path}' is outside the allowed directory")
    if resolved.suffix != ".joblib":
        raise ValueError(f"Model file must have .joblib extension, got '{resolved.suffix}'")
    if not resolved.exists():
        raise FileNotFoundError(f"Model file not found: {resolved}")

    return resolved


def _verify_model_hash(file_path, expected_hash):
    """Verify SHA-256 hash of model file to detect tampering."""
    if not expected_hash:
        logger.warning("No file_hash stored for model — skipping integrity check")
        return
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual_hash = sha256.hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            f"Model file integrity check failed: expected hash {expected_hash[:16]}..., got {actual_hash[:16]}..."
        )


def _load_bundle(model_version):
    """Load and cache a model bundle, returning it from cache if available."""
    version_id = model_version.id
    with _cache_lock:
        if version_id in _model_cache:
            return _model_cache[version_id]

    resolved_path = _validate_model_path(model_version.file_path)
    _verify_model_hash(resolved_path, getattr(model_version, "file_hash", None))

    bundle = joblib.load(resolved_path)

    with _cache_lock:
        # Re-check after expensive load — another worker may have cached it first
        if version_id in _model_cache:
            return _model_cache[version_id]
        # TTLCache auto-evicts expired + LRU entries on set
        _model_cache[version_id] = bundle
        logger.info("Cached model version %s (cache size now %d)", version_id, len(_model_cache))
    return bundle


def clear_model_cache():
    """Clear the model cache (e.g. after retraining)."""
    with _cache_lock:
        _model_cache.clear()
