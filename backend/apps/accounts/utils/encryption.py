"""Field-level encryption utilities using Fernet symmetric encryption.

Provides encrypt/decrypt helpers for PII fields stored at rest in the database.

The encryption key is fetched via the ``KMSAdapter`` indirection
(``apps.accounts.services.kms``). The default ``EnvKMS`` backend reads
``settings.FIELD_ENCRYPTION_KEY`` (single key or comma-separated list for
rotation) — preserving the pre-PR-1-security behaviour exactly. Setting
``KMS_BACKEND=aws`` switches to envelope-encrypted DEK fetched from AWS
KMS (see PR-1 of docs/superpowers/specs/2026-05-25-security-gap-closure-design.md).
"""

import logging
import threading

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from apps.accounts.services.kms import KMSError, get_kms_adapter

logger = logging.getLogger("accounts.encryption")

_fernet_lock = threading.Lock()
_fernet_instance: MultiFernet | None = None


def get_fernet() -> MultiFernet:
    """Return a MultiFernet instance, using a thread-safe singleton pattern.

    The data-encryption key is fetched via ``KMSAdapter.get_data_encryption_key()``
    (``apps.accounts.services.kms``). The default ``EnvKMS`` backend returns the raw
    ``FIELD_ENCRYPTION_KEY`` (single key or comma-separated list for rotation).
    To rotate: prepend the new key to ``FIELD_ENCRYPTION_KEY``, run
    ``python manage.py rotate_encryption_key`` to re-encrypt data, then call
    ``clear_fernet_cache()`` so the new primary key is picked up without a restart.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    with _fernet_lock:
        if _fernet_instance is not None:
            return _fernet_instance
        try:
            raw = get_kms_adapter().get_data_encryption_key()
        except KMSError as exc:
            # Preserve the original ValueError contract for callers (and tests).
            raise ValueError(str(exc)) from exc
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise ValueError("FIELD_ENCRYPTION_KEY is not set or empty")
        _fernet_instance = MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
        return _fernet_instance


def clear_fernet_cache() -> None:
    """Call this after rotating FIELD_ENCRYPTION_KEY so the new primary key is picked up."""
    global _fernet_instance
    with _fernet_lock:
        _fernet_instance = None


def encrypt_field(value):
    """Encrypt a string value using Fernet. Returns the encrypted base64 string.

    Returns *None* / empty string unchanged so callers don't need to guard.
    """
    if value is None or value == "":
        return value
    f = get_fernet()
    return f.encrypt(str(value).encode()).decode()


def decrypt_field(value):
    """Decrypt a Fernet-encrypted string back to plaintext.

    Returns *None* / empty string unchanged. On ``InvalidToken`` (wrong key,
    corrupted ciphertext, or key rotation gap) returns ``""`` rather than the
    raw token so callers never surface ciphertext as if it were plaintext PII.
    """
    if value is None or value == "":
        return value
    try:
        f = get_fernet()
        return f.decrypt(value.encode()).decode()
    except InvalidToken:
        logger.error(
            "decrypt_field: invalid token (length=%d) — wrong key or corrupted data",
            len(value),
        )
        return ""
    except Exception:
        logger.exception("decrypt_field: unexpected error (length=%d)", len(value))
        return ""
