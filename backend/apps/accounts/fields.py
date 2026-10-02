"""Custom Django model fields with transparent encryption."""

import logging

from cryptography.fernet import InvalidToken
from django.db import models

from apps.accounts.utils.encryption import get_fernet

logger = logging.getLogger("accounts.encryption")

# Every Fernet token starts with version byte 0x80, base64 "gAAAAA" (see
# rotate_encryption_key). Legacy plaintext never has this shape.
FERNET_TOKEN_PREFIX = "gAAAAA"


class UndecryptableValue(str):
    """Stand-in for a stored Fernet token this deployment cannot decrypt.

    Reads as the empty string, so the API never serves ciphertext as if it
    were the customer's data, and it keeps the stored token so a save writes
    that token back unchanged instead of encrypting it a second time.
    Assigning a real value to the field replaces it as usual.
    """

    def __new__(cls, ciphertext):
        obj = super().__new__(cls, "")
        obj.ciphertext = ciphertext
        return obj


class EncryptedCharField(models.CharField):
    """CharField that encrypts values at rest using Fernet symmetric encryption.

    Data is encrypted on write (``get_prep_value``) and decrypted on read
    (``from_db_value``).  The default ``max_length`` is 512 to accommodate the
    overhead of Fernet base64 encoding.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 512)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if isinstance(value, UndecryptableValue):
            return value.ciphertext  # never re-encrypt (or blank) what we could not read
        if value is None or value == "":
            return value
        value = str(value)  # Support non-string types (date, Decimal, etc.)
        f = get_fernet()
        return f.encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            f = get_fernet()
            return f.decrypt(value.encode()).decode()
        except InvalidToken:
            if not value.startswith(FERNET_TOKEN_PREFIX):
                return value  # legacy plaintext from before encryption was added
            logger.error(
                "EncryptedCharField %s: undecryptable Fernet token (length=%d) — wrong or missing key; "
                "serving it as empty and preserving the stored value",
                self.name,
                len(value),
            )
            return UndecryptableValue(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Always report the canonical import path for migrations
        path = "apps.accounts.fields.EncryptedCharField"
        # Remove max_length from kwargs if it matches the default
        if kwargs.get("max_length") == 512:
            del kwargs["max_length"]
        return name, path, args, kwargs
