"""Custom Django model fields with transparent encryption."""

from cryptography.fernet import InvalidToken
from django.db import models

from apps.accounts.utils.encryption import get_fernet


class EncryptedCharField(models.CharField):
    """CharField that encrypts values at rest using Fernet symmetric encryption.

    Data is encrypted on write (``get_prep_value``) and decrypted on read
    (``from_db_value``).  The default ``max_length`` is 512 to accommodate the
    overhead of Fernet base64 encoding.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 512)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        f = get_fernet()
        return f.encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        try:
            f = get_fernet()
            return f.decrypt(value.encode()).decode()
        except (InvalidToken, Exception):
            # Value may be unencrypted (pre-migration data)
            return value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Always report the canonical import path for migrations
        path = 'apps.accounts.fields.EncryptedCharField'
        # Remove max_length from kwargs if it matches the default
        if kwargs.get('max_length') == 512:
            del kwargs['max_length']
        return name, path, args, kwargs
