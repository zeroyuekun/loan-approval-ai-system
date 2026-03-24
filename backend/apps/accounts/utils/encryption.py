"""Field-level encryption utilities using Fernet symmetric encryption.

Provides encrypt/decrypt helpers for PII fields stored at rest in the database.
The encryption key is read from ``settings.FIELD_ENCRYPTION_KEY`` which may be a
single Fernet key or a comma-separated list for key rotation (first key encrypts,
all keys are tried for decryption).
"""

import functools

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings


@functools.lru_cache(maxsize=1)
def get_fernet():
    """Return a Fernet (or MultiFernet) instance, cached as a singleton.

    ``FIELD_ENCRYPTION_KEY`` can be a single key or a comma-separated list.
    The first key is used for encryption; all keys are tried for decryption.
    To rotate: generate a new key, prepend it to the comma-separated list,
    then run ``python manage.py rotate_encryption_key`` to re-encrypt data.
    """
    raw = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not raw:
        raise ValueError(
            'FIELD_ENCRYPTION_KEY environment variable must be set. '
            'Generate one with: python -c '
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
    if len(fernets) == 1:
        return fernets[0]
    return MultiFernet(fernets)


def encrypt_field(value):
    """Encrypt a string value using Fernet. Returns the encrypted base64 string.

    Returns *None* / empty string unchanged so callers don't need to guard.
    """
    if value is None or value == '':
        return value
    f = get_fernet()
    return f.encrypt(str(value).encode()).decode()


def decrypt_field(value):
    """Decrypt a Fernet-encrypted string back to plaintext.

    Returns *None* / empty string unchanged.  If the token is invalid (e.g.
    pre-migration plaintext data), returns the original value so the system
    degrades gracefully.
    """
    if value is None or value == '':
        return value
    try:
        f = get_fernet()
        return f.decrypt(value.encode()).decode()
    except Exception:
        # Value may be unencrypted (pre-migration data) or key mismatch
        return value
