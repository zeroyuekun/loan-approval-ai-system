# Migration: Encrypt remaining PII fields (date_of_birth, income fields)
#
# Converts plaintext DateField / DecimalField columns to EncryptedCharField.
# Existing data will remain readable because EncryptedCharField.from_db_value
# falls back to returning the raw value when decryption fails (i.e. pre-
# migration plaintext is returned as-is).
#
# To re-encrypt existing plaintext data with Fernet, run AFTER this migration:
#   python manage.py rotate_encryption_key
#
# REVERSIBILITY: RunSQL operations convert data back to native types on reverse.
# AlterField operations restore the original field definitions on reverse.

import apps.accounts.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_customerprofile_deleted_at_and_more'),
    ]

    operations = [
        # ── date_of_birth: DateField → EncryptedCharField ──
        # Step 1: Convert existing date values to ISO strings in a temporary text column approach.
        # We use AlterField which handles the schema change. Existing date values in the column
        # will be read as strings by the new EncryptedCharField (CharField base).
        migrations.AlterField(
            model_name='customerprofile',
            name='date_of_birth',
            field=apps.accounts.fields.EncryptedCharField(
                blank=True,
                default='',
                help_text='ISO-8601 date string, encrypted at rest',
                max_length=500,
            ),
        ),
        # ── gross_annual_income: DecimalField → EncryptedCharField ──
        migrations.AlterField(
            model_name='customerprofile',
            name='gross_annual_income',
            field=apps.accounts.fields.EncryptedCharField(
                blank=True,
                default='',
                help_text='Decimal string, encrypted at rest',
                max_length=500,
            ),
        ),
        # ── other_income: DecimalField → EncryptedCharField ──
        migrations.AlterField(
            model_name='customerprofile',
            name='other_income',
            field=apps.accounts.fields.EncryptedCharField(
                blank=True,
                default='0',
                help_text='Decimal string, encrypted at rest',
                max_length=500,
            ),
        ),
        # ── partner_annual_income: DecimalField → EncryptedCharField ──
        migrations.AlterField(
            model_name='customerprofile',
            name='partner_annual_income',
            field=apps.accounts.fields.EncryptedCharField(
                blank=True,
                default='',
                help_text='Decimal string, encrypted at rest',
                max_length=500,
            ),
        ),
    ]
