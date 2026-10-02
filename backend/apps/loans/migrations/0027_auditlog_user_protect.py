"""AuditLog.user: SET_NULL -> PROTECT.

The user id is hashed into each AuditLog row. SET_NULL nulls it with a bulk
UPDATE that never recomputes the hash, so deleting an audited user broke the
chain. A user who appears in the audit trail now cannot be deleted
(deactivate them instead).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0026_auditlog_hash_chain"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="audit_logs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
