"""Hash-chained AuditLog — add hash_prev/hash_self and backfill existing rows.

PR-2 of the security gap-closure cycle. After this migration every AuditLog
row is bound to its chronological predecessor via SHA-256; the
``verify_audit_chain`` management command detects any subsequent tampering.

The backfill is idempotent: rows that already carry a non-empty hash_self
are skipped, so re-running the migration (e.g. after a failed partial run)
does not double-hash or corrupt the chain.
"""

import hashlib
import json

import django.utils.timezone
from django.db import migrations, models

GENESIS_HASH = "0" * 64


def _canonical_hash(*, hash_prev, timestamp, user_id, action, resource_type, resource_id, details):
    """Pinned canonical-form hash. Must stay byte-identical to
    ``apps.loans.services.audit_chain.compute_hash``; any divergence
    breaks every chain ever migrated.
    """
    payload = {
        "hash_prev": hash_prev,
        "timestamp": timestamp,
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details or {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def backfill_hash_chain(apps, schema_editor):
    """Walk existing AuditLog rows in (timestamp, id) order and compute
    their chain hashes. Skips rows that already have a hash_self so the
    operation is safely re-runnable.
    """
    AuditLog = apps.get_model("loans", "AuditLog")
    prior_hash = GENESIS_HASH
    for row in AuditLog.objects.order_by("timestamp", "id").iterator():
        if row.hash_self:
            # Already chained on a prior run — trust it and move on.
            prior_hash = row.hash_self
            continue
        digest = _canonical_hash(
            hash_prev=prior_hash,
            timestamp=row.timestamp.isoformat(),
            user_id=str(row.user_id) if row.user_id else None,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            details=row.details or {},
        )
        row.hash_prev = prior_hash
        row.hash_self = digest
        # Historical model save() has no override — straight UPDATE.
        row.save(update_fields=["hash_prev", "hash_self"])
        prior_hash = digest


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0025_loandecision_human_involvement"),
    ]

    operations = [
        # Switch timestamp off auto_now_add so AuditLog.save() can read
        # the value before INSERT and bind it into hash_self.
        migrations.AlterField(
            model_name="auditlog",
            name="timestamp",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="hash_prev",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="hash_self of the prior chronological row; '0'*64 for the chain root.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="hash_self",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="SHA-256 of this row's canonical payload (including hash_prev).",
                max_length=64,
            ),
        ),
        migrations.RunPython(backfill_hash_chain, reverse_code=migrations.RunPython.noop),
    ]
