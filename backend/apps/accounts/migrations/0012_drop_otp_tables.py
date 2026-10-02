"""Drop django-otp's tables: two-factor authentication was removed.

The TOTP secrets they hold must not outlive the feature. Removing the
migration-history rows means a future re-install starts clean instead of
assuming the tables exist. Reversing is a no-op: the secrets are gone.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_customuser_deidentified_at")]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS otp_totp_totpdevice;",
                "DELETE FROM django_migrations WHERE app = 'otp_totp';",
            ],
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
