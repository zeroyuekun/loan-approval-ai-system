"""Key Management Service (KMS) abstraction for field-level encryption.

PR-1 of the security gap-closure cycle
(docs/superpowers/specs/2026-05-25-security-gap-closure-design.md).

Backends:
  - ``EnvKMS`` (default): reads the Fernet key from
    ``settings.FIELD_ENCRYPTION_KEY``. Current behaviour, unchanged.
  - ``AWSKmsAdapter``: NOT IMPLEMENTED — gated off behind ``NotImplementedError``.
    The naive ``GenerateDataKey`` approach discarded the ``CiphertextBlob`` and
    cached only the plaintext DEK, which silently loses data once the cache TTL
    expires. Do not enable ``KMS_BACKEND="aws"`` until real envelope encryption
    lands (see the ``AWSKmsAdapter`` class docstring).

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
    """Production backend placeholder — AWS KMS envelope encryption is NOT yet
    implemented and MUST NOT be enabled.

    A previous implementation called ``generate_data_key`` and cached only the
    plaintext DEK, discarding the ``CiphertextBlob``. Because ``GenerateDataKey``
    returns a NEW random key on every call, once the in-process cache expired
    (``KMS_DEK_TTL``) the next fetch produced a DIFFERENT DEK — silently making all
    previously-encrypted PII undecryptable (``decrypt_field`` returns ``""`` on
    ``InvalidToken``). That is a data-loss defect, so the AWS path is gated off
    behind ``NotImplementedError`` until real envelope encryption lands: persist
    the per-record ``CiphertextBlob`` and call ``kms.Decrypt`` (or use direct
    ``Encrypt``/``Decrypt`` per field). Tracked as a follow-up to PR-1.

    The default ``EnvKMS`` backend is unaffected and remains the supported path.
    """

    def get_data_encryption_key(self) -> str:
        raise NotImplementedError(
            "AWS KMS envelope encryption is not implemented. KMS_BACKEND='env' is "
            "the only supported backend; do not set KMS_BACKEND='aws' until "
            "per-record CiphertextBlob persistence + kms.Decrypt is implemented. "
            "The naive GenerateDataKey approach silently loses data once the DEK "
            "cache TTL expires (a new random DEK can no longer decrypt old data)."
        )


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
            raise KMSError(f"Unknown KMS_BACKEND={backend!r}. Must be 'env' or 'aws'.")
        logger.info("KMS adapter initialised: backend=%s", backend)
        return _adapter_singleton


def reset_kms_adapter() -> None:
    """Clear the cached adapter (test-only helper)."""
    global _adapter_singleton
    with _adapter_lock:
        _adapter_singleton = None
