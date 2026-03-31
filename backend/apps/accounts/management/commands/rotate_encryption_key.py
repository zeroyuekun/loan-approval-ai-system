"""Re-encrypt all PII fields with the current primary Fernet key.

Usage:
    1. Generate a new key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    2. Prepend the new key to FIELD_ENCRYPTION_KEY (comma-separated): NEW_KEY,OLD_KEY
    3. Run: python manage.py rotate_encryption_key
    4. After successful rotation, remove the old key from FIELD_ENCRYPTION_KEY
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import CustomerProfile


class Command(BaseCommand):
    help = "Re-encrypt all PII fields with the current primary Fernet key."

    def handle(self, *args, **options):
        encrypted_fields = [
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
        profiles = CustomerProfile.objects.all()
        total = profiles.count()
        rotated = 0

        self.stdout.write(f"Rotating encryption for {total} profiles across {len(encrypted_fields)} fields...")

        for profile in profiles.iterator(chunk_size=100):
            changed = False
            for field_name in encrypted_fields:
                value = getattr(profile, field_name, None)
                if value and str(value).strip():
                    # Reading decrypts with any key; saving re-encrypts with primary key
                    changed = True
            if changed:
                profile.save(update_fields=encrypted_fields)
                rotated += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Re-encrypted {rotated} of {total} profiles."))
