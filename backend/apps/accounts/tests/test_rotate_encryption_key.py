"""Regression tests for the rotate_encryption_key management command.

Codex adversarial review (2026-05-07) flagged that the command would
re-encrypt corrupt ciphertext as if it were plaintext — irreversible double
encryption — because ``EncryptedCharField.from_db_value`` silently returns
the raw ciphertext on ``InvalidToken``. These tests pin the post-fix
behaviour:

  - ``--dry-run`` is the default (no writes without ``--apply``)
  - Apply rotates rows whose ciphertext decrypts cleanly with the primary key
  - Pre-migration plaintext (non-Fernet-shaped) still gets encrypted
  - Corrupt ciphertext (Fernet-shaped but undecryptable) aborts the run
  - ``--allow-failures`` skips and continues past corrupt rows

See docs/superpowers/specs/2026-05-07-codex-adversarial-response-v1-10-7-design.md
"""

from contextlib import contextmanager
from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings

from apps.accounts.models import CustomerProfile, CustomUser
from apps.accounts.utils import encryption


def _set_raw_field(profile_id, field_name, raw_value):
    """Bypass the model's encrypted-field machinery and write a literal value
    directly to the column. Used to simulate corrupt ciphertext or
    pre-migration plaintext in tests.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE accounts_customerprofile SET "{field_name}" = %s WHERE "id" = %s',
            [raw_value, profile_id],
        )


def _read_raw_field(profile_id, field_name):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT "{field_name}" FROM accounts_customerprofile WHERE "id" = %s',
            [profile_id],
        )
        row = cursor.fetchone()
        return row[0] if row else None


def _clear_all_encrypted_fields(profile_id):
    """Null out every encrypted column on a row. Necessary because some
    fields have defaults (e.g. other_income='0') that get encrypted with the
    base test settings key — which differs from our test-local key pair.
    Without this, the rotation command would correctly flag those defaulted
    values as undecryptable ciphertext under our override.
    """
    encrypted_fields = [
        "primary_id_number",
        "secondary_id_number",
        "phone",
        "address_line_1",
        "address_line_2",
        "employer_name",
        "date_of_birth",
        "gross_annual_income",
        "other_income",
        "partner_annual_income",
    ]
    set_clause = ", ".join(f'"{f}" = %s' for f in encrypted_fields)
    # Columns are NOT NULL — empty-string is the rotation command's
    # "skip-this-field" sentinel, same effect as NULL would have been.
    params = [""] * len(encrypted_fields) + [profile_id]
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE accounts_customerprofile SET {set_clause} WHERE "id" = %s',
            params,
        )


@contextmanager
def _isolated_keys():
    """Generate a fresh (new, old) Fernet key pair, install it as
    FIELD_ENCRYPTION_KEY, clear the get_fernet cache before and after.
    """
    new_key = Fernet.generate_key().decode()
    old_key = Fernet.generate_key().decode()
    encryption.get_fernet.cache_clear()
    with override_settings(FIELD_ENCRYPTION_KEY=f"{new_key},{old_key}"):
        yield new_key, old_key
    encryption.get_fernet.cache_clear()


@pytest.fixture
def customer_profile(db):
    user = CustomUser.objects.create_user(
        username="rotation_target",
        email="rotation@test.com",
        password="x",
        role="customer",
    )
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    # Reset every encrypted column so these tests start from a known-empty
    # baseline rather than the model defaults (which were encrypted with the
    # test-settings key).
    _clear_all_encrypted_fields(profile.id)
    return profile


@pytest.mark.django_db
class TestRotateEncryptionKey:
    def test_dry_run_is_default_no_writes(self, customer_profile):
        with _isolated_keys() as (new_key, old_key):
            old_fernet = Fernet(old_key.encode())
            ciphertext_old = old_fernet.encrypt(b"0400123456").decode()
            _set_raw_field(customer_profile.id, "phone", ciphertext_old)

            out = StringIO()
            call_command("rotate_encryption_key", stdout=out)

            assert _read_raw_field(customer_profile.id, "phone") == ciphertext_old
            output = out.getvalue()
            assert "DRY-RUN" in output
            assert "no database changes" in output.lower()

    def test_apply_re_encrypts_with_primary_key(self, customer_profile):
        with _isolated_keys() as (new_key, old_key):
            old_fernet = Fernet(old_key.encode())
            new_fernet = Fernet(new_key.encode())
            ciphertext_old = old_fernet.encrypt(b"0400123456").decode()
            _set_raw_field(customer_profile.id, "phone", ciphertext_old)

            call_command("rotate_encryption_key", "--apply", stdout=StringIO())

            new_value = _read_raw_field(customer_profile.id, "phone")
            assert new_value != ciphertext_old
            assert new_fernet.decrypt(new_value.encode()).decode() == "0400123456"

    def test_corrupt_ciphertext_aborts_without_allow_failures(self, customer_profile):
        with _isolated_keys():
            corrupt_ciphertext = "gAAAAABimY-not-a-real-token-just-junk-data"
            _set_raw_field(customer_profile.id, "phone", corrupt_ciphertext)

            with pytest.raises(CommandError):
                call_command("rotate_encryption_key", "--apply", stdout=StringIO())

            # Column must be untouched after abort.
            assert _read_raw_field(customer_profile.id, "phone") == corrupt_ciphertext

    def test_corrupt_ciphertext_skipped_with_allow_failures(self, customer_profile):
        with _isolated_keys() as (new_key, old_key):
            old_fernet = Fernet(old_key.encode())
            ciphertext_old = old_fernet.encrypt(b"0400123456").decode()
            _set_raw_field(customer_profile.id, "phone", ciphertext_old)

            corrupt_ciphertext = "gAAAAABimY-not-a-real-token-just-junk-data"
            _set_raw_field(customer_profile.id, "address_line_1", corrupt_ciphertext)

            out = StringIO()
            call_command("rotate_encryption_key", "--apply", "--allow-failures", stdout=out)

            # Whole row is skipped — partial writes risk inconsistency.
            assert _read_raw_field(customer_profile.id, "phone") == ciphertext_old
            assert _read_raw_field(customer_profile.id, "address_line_1") == corrupt_ciphertext

            output = out.getvalue()
            assert "Skipping profile" in output or "Skipped" in output

    def test_promotes_pre_migration_plaintext(self, customer_profile):
        """Legitimate pre-migration plaintext (non-Fernet-shaped) must be
        encrypted on apply, not aborted as corrupt ciphertext."""
        with _isolated_keys() as (new_key, old_key):
            plaintext = "0400123456"
            _set_raw_field(customer_profile.id, "phone", plaintext)

            call_command("rotate_encryption_key", "--apply", stdout=StringIO())

            new_value = _read_raw_field(customer_profile.id, "phone")
            assert new_value.startswith("gAAAAA")
            assert Fernet(new_key.encode()).decrypt(new_value.encode()).decode() == plaintext

    def test_dry_run_reports_what_would_happen(self, customer_profile):
        with _isolated_keys() as (new_key, old_key):
            old_fernet = Fernet(old_key.encode())
            ciphertext_old = old_fernet.encrypt(b"0400123456").decode()
            _set_raw_field(customer_profile.id, "phone", ciphertext_old)

            out = StringIO()
            call_command("rotate_encryption_key", stdout=out)

            output = out.getvalue()
            assert "Would re-encrypt" in output
            assert "of 1 CustomerProfile rows" in output
            # Column truly untouched
            assert _read_raw_field(customer_profile.id, "phone") == ciphertext_old
