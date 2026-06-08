"""Re-encrypt all PII fields with the current primary Fernet key.

Workflow:
    1. Generate a new key:
         python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    2. Prepend new key to FIELD_ENCRYPTION_KEY (comma-separated): NEW_KEY,OLD_KEY
    3. Dry-run first (default — no DB writes):
         python manage.py rotate_encryption_key
    4. Apply changes:
         python manage.py rotate_encryption_key --apply
    5. After successful rotation, remove the old key from FIELD_ENCRYPTION_KEY.

Codex adversarial review (v1.10.7) hardening: the previous version called
``getattr(profile, field)`` which triggered ``EncryptedCharField.from_db_value``;
that helper returns the raw ciphertext on ``InvalidToken``. The old command
then called ``profile.save()`` and re-encrypted that opaque ciphertext as if
it were plaintext, irreversibly double-encrypting corrupt rows. This rewrite:

  - Reads ciphertext via raw SQL (bypassing ``from_db_value``) so InvalidToken
    surfaces as a real failure rather than a silent ciphertext fallback.
  - Detects Fernet-shaped values (token version byte ``0x80`` → b64 ``gAAAAA``)
    so legitimate pre-migration plaintext still gets encrypted, while corrupt
    ciphertext aborts the run.
  - Defaults to ``--dry-run`` semantics (no writes) so operators see the impact
    before committing. ``--apply`` is required to write.
  - Provides ``--allow-failures`` to skip and continue on per-row decrypt
    errors with a structured report — without that flag, the first failure
    aborts cleanly.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

ENCRYPTED_FIELDS = [
    "primary_id_number",
    "secondary_id_number",
    "phone",
    "address_line_1",
    "address_line_2",
    "employer_name",
    # PII fields added in 0009 migration
    "date_of_birth",
    "gross_annual_income",
    "other_income",
    "partner_annual_income",
]

# Fernet tokens are urlsafe-base64-encoded and start with version byte 0x80,
# which encodes as `gAAAAA`. We use this prefix to distinguish ciphertext from
# pre-migration plaintext: a value that LOOKS like ciphertext but fails to
# decrypt is a corrupt-ciphertext / wrong-key scenario; a value that doesn't
# look like ciphertext is legitimate plaintext awaiting first encryption.
FERNET_TOKEN_PREFIX = "gAAAAA"

CUSTOMER_PROFILE_TABLE = "accounts_customerprofile"


class Command(BaseCommand):
    help = (
        "Re-encrypt CustomerProfile PII fields with the current primary Fernet key. "
        "Defaults to dry-run; pass --apply to write."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes. Without this flag the command runs in dry-run mode.",
        )
        parser.add_argument(
            "--allow-failures",
            action="store_true",
            help=(
                "Skip rows whose ciphertext fails to decrypt and continue. Without this "
                "flag, the first decryption failure aborts the entire run (the safe default)."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        allow_failures = options["allow_failures"]

        keys = self._load_keys()
        primary_fernet = Fernet(self._key_bytes(keys[0]))
        decrypt_fernets = [Fernet(self._key_bytes(k)) for k in keys]

        column_list = ", ".join(['"id"'] + [f'"{c}"' for c in ENCRYPTED_FIELDS])
        rows = self._fetch_rows(column_list)

        total = len(rows)
        rotated_rows = 0
        promoted_plaintext_rows = 0
        skipped_failures: list[dict] = []

        mode_label = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(
            f"[{mode_label}] Rotating {total} CustomerProfile rows across {len(ENCRYPTED_FIELDS)} fields..."
        )

        for row in rows:
            row_id = row[0]
            updates: dict[str, str] = {}
            row_errors: list[str] = []
            row_promoted_plaintext: list[str] = []

            for idx, field in enumerate(ENCRYPTED_FIELDS, start=1):
                ciphertext = row[idx]
                if ciphertext is None or ciphertext == "":
                    continue

                plaintext = self._decrypt_or_classify(
                    ciphertext,
                    decrypt_fernets,
                )

                if plaintext is None:
                    # Looked like ciphertext but failed to decrypt → corrupt / wrong key.
                    row_errors.append(field)
                    continue

                # plaintext is the recovered string. If the original was non-Fernet-shaped
                # (legitimate pre-migration plaintext), record that so the summary makes
                # the operator aware that those rows are being encrypted for the first time.
                if not str(ciphertext).startswith(FERNET_TOKEN_PREFIX):
                    row_promoted_plaintext.append(field)

                updates[field] = primary_fernet.encrypt(plaintext.encode()).decode()

            if row_errors:
                skipped_failures.append({"profile_id": str(row_id), "fields": row_errors})
                if not allow_failures:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Profile {row_id}: decryption failed on fields {row_errors}. "
                            f"Aborting. Pass --allow-failures to skip and continue past corrupt rows."
                        )
                    )
                    raise CommandError("Rotation aborted: ciphertext decryption failures detected.")
                self.stdout.write(self.style.WARNING(f"Skipping profile {row_id}: decryption failed on {row_errors}"))
                continue

            if not updates:
                continue

            if apply_changes:
                self._write_row(row_id, updates)

            rotated_rows += 1
            if row_promoted_plaintext:
                promoted_plaintext_rows += 1

        verb = "Re-encrypted" if apply_changes else "Would re-encrypt"
        self.stdout.write(self.style.SUCCESS(f"{verb} {rotated_rows} of {total} CustomerProfile rows."))
        if promoted_plaintext_rows:
            self.stdout.write(
                self.style.NOTICE(
                    f"  ↳ {promoted_plaintext_rows} row(s) contained pre-migration plaintext "
                    f"that {'was' if apply_changes else 'would be'} encrypted for the first time."
                )
            )
        if skipped_failures:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {len(skipped_failures)} row(s) with decryption failures: {skipped_failures}"
                )
            )
        if not apply_changes:
            self.stdout.write(self.style.NOTICE("DRY-RUN: no database changes written. Re-run with --apply to commit."))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key_bytes(key) -> bytes:
        return key.encode() if isinstance(key, str) else key

    @staticmethod
    def _load_keys() -> list[str]:
        raw = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise CommandError("FIELD_ENCRYPTION_KEY is not configured.")
        return keys

    @staticmethod
    def _fetch_rows(column_list: str):
        with connection.cursor() as cursor:
            # column_list is composed exclusively from the hardcoded
            # ENCRYPTED_FIELDS constant + literal "id"; CUSTOMER_PROFILE_TABLE
            # is also a module-level constant. No user input is interpolated.
            cursor.execute(f"SELECT {column_list} FROM {CUSTOMER_PROFILE_TABLE}")  # noqa: S608
            return cursor.fetchall()

    @staticmethod
    def _write_row(row_id, updates: dict[str, str]) -> None:
        set_clause = ", ".join(f'"{f}" = %s' for f in updates)
        params = list(updates.values()) + [row_id]
        with transaction.atomic():
            with connection.cursor() as cursor:
                # set_clause column names come from the ENCRYPTED_FIELDS
                # constant (filtered through `updates` keys); values + row_id
                # are passed through %s placeholders.
                cursor.execute(
                    f'UPDATE {CUSTOMER_PROFILE_TABLE} SET {set_clause} WHERE "id" = %s',  # noqa: S608
                    params,
                )

    @staticmethod
    def _decrypt_or_classify(value: str, decrypt_fernets: list[Fernet]) -> str | None:
        """Return plaintext if the value can be decrypted with any key OR if it
        looks like pre-migration plaintext. Return None if it looks like
        ciphertext but no key can decrypt it (the corrupt-ciphertext case).
        """
        encoded = value.encode() if isinstance(value, str) else value

        # Try every key — covers both single-key and rotation scenarios.
        for fernet in decrypt_fernets:
            try:
                return fernet.decrypt(encoded).decode()
            except InvalidToken:
                continue

        # No key worked. Decide between corrupt-ciphertext and plaintext based
        # on whether the value has the Fernet token shape.
        if str(value).startswith(FERNET_TOKEN_PREFIX):
            return None
        return str(value)
