"""Add CustomUser.last_failed_login_at (see LOGIN_FAILURE_WINDOW in settings).

Existing rows have no failure time, so their next failure starts a new count.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_drop_otp_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="last_failed_login_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
