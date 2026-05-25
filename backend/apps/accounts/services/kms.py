"""Key Management Service (KMS) abstraction for field-level encryption.

PR-1 of the security gap-closure cycle
(docs/superpowers/specs/2026-05-25-security-gap-closure-design.md).

Backends:
  - ``EnvKMS`` (default): reads the Fernet key from
    ``settings.FIELD_ENCRYPTION_KEY``. Current behaviour, unchanged.
  - ``AWSKmsAdapter``: fetches the Data Encryption Key (DEK) from AWS KMS
    via ``GenerateDataKey``. Caches the DEK in-process for ``KMS_DEK_TTL``
    seconds (default 1 hour) to avoid hammering KMS on every field
    read/write.

Settings:
  - ``KMS_BACKEND``: ``"env"`` (default) or ``"aws"``.
  - ``AWS_KMS_KEY_ID``: required when ``KMS_BACKEND="aws"``. Can be a
    key ID, ARN, or alias (e.g. ``alias/loanapproval-fields``).
  - ``KMS_DEK_TTL``: seconds the DEK is cached in-process. Default 3600.

The DEK returned to callers is the same 32-byte url-safe-base64 Fernet
key format both backends use, so ``cryptography.fernet.Fernet(dek)`` is
the consumer in both cases.

For multi-key rotation (current ``FIELD_ENCRYPTION_KEY=k1,k2`` syntax),
``EnvKMS.get_data_encryption_key()`` returns the comma-separated string
as-is and the consumer parses it. ``AWSKmsAdapter`` returns a single
key — rotation via the AWS KMS key policy.
"""

from __future__ import annotations

import abc
import logging
import threading
import time

from django.conf import settings

logger = logging.getLogger("accounts.kms")


class KMSError(Exception):
    """Raised when the KMS backend cannot fetch a DEK."""


class KMSAdapter(abc.ABC):
    """Abstract base for KMS backends.

    Implementations return a key (or comma-separated keys) suitable for
    ``cryptography.fernet.Fernet`` / ``MultiFernet``.
    """

    @abc.abstractmethod
    def get_data_encryption_key(self) -> str:
        """Return the DEK as a string (single key or comma-separated keys)."""

    def rotate(self) -> None:  # pragma: no cover — default no-op
        """Trigger backend-specific key rotation. Default is a no-op."""


class EnvKMS(KMSAdapter):
    """Default backend — reads ``FIELD_ENCRYPTION_KEY`` from settings.

    Preserves the current pre-PR-1 behaviour exactly: same env var, same
    comma-separated multi-key syntax, same MultiFernet-driven rotation
    via ``manage.py rotate_encryption_key``.
    """

    def get_data_encryption_key(self) -> str:
        raw = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
        if not raw:
            raise KMSError(
                "FIELD_ENCRYPTION_KEY environment variable must be set when "
                "KMS_BACKEND='env'. Generate one with: python -c "
                '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        return raw


class AWSKmsAdapter(KMSAdapter):
    """Production backend — fetches the DEK from AWS KMS.

    Uses ``boto3.client('kms').generate_data_key`` with KeySpec='AES_256',
    then base64-url-encodes the plaintext key into Fernet's expected
    32-byte url-safe form. Caches the DEK in-process for ``KMS_DEK_TTL``
    seconds.

    boto3 is imported lazily so the default ``EnvKMS`` path has no boto3
    dependency. ``AWSKmsAdapter`` raises ``KMSError`` if boto3 is not
    installed.
    """

    def __init__(self) -> None:
        self._key_id = getattr(settings, "AWS_KMS_KEY_ID", "")
        self._ttl = int(getattr(settings, "KMS_DEK_TTL", 3600))
        self._cached_dek: str | None = None
        self._cached_at: float = 0.0
        self._lock = threading.Lock()

    def get_data_encryption_key(self) -> str:
        if not self._key_id:
            raise KMSError(
                "AWS_KMS_KEY_ID must be set when KMS_BACKEND='aws' "
                "(key ID, ARN, or alias)."
            )

        now = time.monotonic()
        with self._lock:
            if self._cached_dek is not None and (now - self._cached_at) < self._ttl:
                return self._cached_dek

            try:
                import base64

                import boto3
            except ImportError as exc:
                raise KMSError(
                    "boto3 is not installed but KMS_BACKEND='aws'. "
                    "Install boto3 or switch back to KMS_BACKEND='env'."
                ) from exc

            try:
                client = boto3.client("kms")
                response = client.generate_data_key(KeyId=self._key_id, KeySpec="AES_256")
                # Fernet expects 32 bytes encoded as url-safe base64
                plaintext = response["Plaintext"]
                dek = base64.urlsafe_b64encode(plaintext).decode()
            except Exception as exc:
                logger.error("AWS KMS generate_data_key failed: %s", exc)
                raise KMSError(f"AWS KMS DEK fetch failed: {exc}") from exc

            self._cached_dek = dek
            self._cached_at = now
            logger.info(
                "AWS KMS DEK fetched (key_id=%s, ttl=%ds)", self._key_id, self._ttl
            )
            return dek

    def rotate(self) -> None:
        """Invalidate the cached DEK so the next call re-fetches from KMS."""
        with self._lock:
            self._cached_dek = None
            self._cached_at = 0.0


_adapter_singleton: KMSAdapter | None = None
_adapter_lock = threading.Lock()


def get_kms_adapter() -> KMSAdapter:
    """Return the configured KMS adapter, cached as a singleton.

    Reads ``settings.KMS_BACKEND`` (default ``"env"``). Cache is
    invalidated via ``reset_kms_adapter()`` for tests.
    """
    global _adapter_singleton
    if _adapter_singleton is not None:
        return _adapter_singleton

    with _adapter_lock:
        if _adapter_singleton is not None:
            return _adapter_singleton

        backend = (getattr(settings, "KMS_BACKEND", "env") or "env").lower()
        if backend == "env":
            _adapter_singleton = EnvKMS()
        elif backend == "aws":
            _adapter_singleton = AWSKmsAdapter()
        else:
            raise KMSError(
                f"Unknown KMS_BACKEND={backend!r}. Must be 'env' or 'aws'."
            )
        logger.info("KMS adapter initialised: backend=%s", backend)
        return _adapter_singleton


def reset_kms_adapter() -> None:
    """Clear the cached adapter (test-only helper)."""
    global _adapter_singleton
    with _adapter_lock:
        _adapter_singleton = None
