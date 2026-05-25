"""Field-level encryption utilities using Fernet symmetric encryption.

Provides encrypt/decrypt helpers for PII fields stored at rest in the database.

The encryption key is fetched via the ``KMSAdapter`` indirection
(``apps.accounts.services.kms``). The default ``EnvKMS`` backend reads
``settings.FIELD_ENCRYPTION_KEY`` (single key or comma-separated list for
rotation) — preserving the pre-PR-1-security behaviour exactly. Setting
``KMS_BACKEND=aws`` switches to envelope-encrypted DEK fetched from AWS
KMS (see PR-1 of docs/superpowers/specs/2026-05-25-security-gap-closure-design.md).
"""

import functools
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from apps.accounts.services.kms import KMSError, get_kms_adapter

logger = logging.getLogger("accounts.encryption")


@functools.lru_cache(maxsize=1)
def get_fernet():
    """Return a Fernet (or MultiFernet) instance, cached as a singleton.

    The DEK is fetched via ``KMSAdapter.get_data_encryption_key()``:
      - ``EnvKMS`` returns the raw ``FIELD_ENCRYPTION_KEY`` (single key
        or comma-separated for rotation).
      - ``AWSKmsAdapter`` returns a single DEK from AWS KMS.

    For multi-key rotation in the env backend: prepend the new key to
    ``FIELD_ENCRYPTION_KEY``, then run
    ``python manage.py rotate_encryption_key`` to re-encrypt data.
    """
    try:
        raw = get_kms_adapter().get_data_encryption_key()
    except KMSError as exc:
        # Preserve the original ValueError contract for callers (and for
        # the existing tests that assert on this exception type).
        raise ValueError(str(exc)) from exc
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
    if len(fernets) == 1:
        return fernets[0]
    return MultiFernet(fernets)


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
