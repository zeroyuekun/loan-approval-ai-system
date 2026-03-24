"""Data migration: encrypt any existing plaintext PII values.

Reads raw DB values and encrypts them using the current Fernet key.
Already-encrypted values (those that decrypt successfully) are skipped.
"""

from django.db import migrations


def encrypt_existing_pii(apps, schema_editor):
    """Encrypt plaintext primary_id_number and secondary_id_number values."""
    from apps.accounts.utils.encryption import get_fernet, decrypt_field

    try:
        f = get_fernet()
    except ValueError:
        # No encryption key configured (dev mode) — skip migration
        return

    CustomerProfile = apps.get_model('accounts', 'CustomerProfile')
    db_alias = schema_editor.connection.alias

    for profile in CustomerProfile.objects.using(db_alias).all().iterator(chunk_size=200):
        changed = False
        for field_name in ('primary_id_number', 'secondary_id_number'):
            raw_value = getattr(profile, field_name, None)
            if not raw_value or not raw_value.strip():
                continue

            # Check if value is already encrypted by trying to decrypt it
            try:
                f.decrypt(raw_value.encode())
                # Decrypted successfully — already encrypted, skip
                continue
            except Exception:
                # Not valid Fernet token — plaintext, needs encryption
                encrypted = f.encrypt(raw_value.encode()).decode()
                setattr(profile, field_name, encrypted)
                changed = True

        if changed:
            profile.save(update_fields=['primary_id_number', 'secondary_id_number'])


def decrypt_existing_pii(apps, schema_editor):
    """Reverse: decrypt encrypted values back to plaintext."""
    from apps.accounts.utils.encryption import get_fernet

    try:
        f = get_fernet()
    except ValueError:
        return

    CustomerProfile = apps.get_model('accounts', 'CustomerProfile')
    db_alias = schema_editor.connection.alias

    for profile in CustomerProfile.objects.using(db_alias).all().iterator(chunk_size=200):
        changed = False
        for field_name in ('primary_id_number', 'secondary_id_number'):
            raw_value = getattr(profile, field_name, None)
            if not raw_value or not raw_value.strip():
                continue

            try:
                decrypted = f.decrypt(raw_value.encode()).decode()
                setattr(profile, field_name, decrypted)
                changed = True
            except Exception:
                # Already plaintext
                continue

        if changed:
            profile.save(update_fields=['primary_id_number', 'secondary_id_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_customerprofile_data_sharing_consent_and_more'),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_pii, decrypt_existing_pii),
    ]
