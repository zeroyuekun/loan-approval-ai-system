"""Field-level encryption utilities using Fernet symmetric encryption.

Provides encrypt/decrypt helpers for PII fields stored at rest in the database.
The encryption key is read from the ``FIELD_ENCRYPTION_KEY`` environment variable
which may be a single Fernet key or a comma-separated list for key rotation (first
key encrypts, all keys are tried for decryption).
"""

import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger("accounts.encryption")

_fernet_lock = threading.Lock()
_fernet_instance: MultiFernet | None = None


def get_fernet() -> MultiFernet:
    """Return a MultiFernet instance, using a thread-safe singleton pattern.

    ``FIELD_ENCRYPTION_KEY`` can be a single key or a comma-separated list.
    The first key is used for encryption; all keys are tried for decryption.
    To rotate: generate a new key, prepend it to the comma-separated list,
    then run ``python manage.py rotate_encryption_key`` to re-encrypt data.
    Call ``clear_fernet_cache()`` after updating the environment variable so
    the new primary key is picked up without a process restart.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    with _fernet_lock:
        if _fernet_instance is not None:
            return _fernet_instance
        raw = os.environ.get("FIELD_ENCRYPTION_KEY", "")
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
