"""Add CustomUser.deidentified_at, the retention job's idempotency marker.

The job used to skip users whose email ended in @deidentified.local, a value
any user could set on themselves through /auth/me/. Accounts the job already
de-identified (that email plus the deidentified_<pk> username it assigns) are
backfilled from their last update.
"""

from django.db import migrations, models
from django.db.models import F


def backfill(apps, schema_editor):
    CustomUser = apps.get_model("accounts", "CustomUser")
    CustomUser.objects.filter(
        email__endswith="@deidentified.local", username__startswith="deidentified_", is_active=False
    ).update(deidentified_at=F("updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_add_on_time_payment_pct_validators"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="deidentified_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
