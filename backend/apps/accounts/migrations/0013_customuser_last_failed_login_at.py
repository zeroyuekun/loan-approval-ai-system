"""Add CustomUser.last_failed_login_at, so failed sign-ins expire.

The failure count used to grow until a successful sign-in, and fifteen or
more failures locked the account for 24 hours on every further failure. One
wrong password a day kept a staff account locked. record_failed_login now
starts a new count when the previous failure is older than
LOGIN_FAILURE_WINDOW. Existing rows have no failure time, so their next
failure starts a new count.
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
