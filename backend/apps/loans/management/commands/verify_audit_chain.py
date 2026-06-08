"""Verify the AuditLog hash chain — PR-2 of the security gap-closure cycle.

Walks every ``AuditLog`` row in chronological (timestamp, id) order and
checks two invariants per row:

1. ``hash_prev`` matches the prior row's ``hash_self`` (or
   ``GENESIS_HASH`` for the first row).
2. ``hash_self`` matches the freshly-computed canonical hash for the
   row's current field values.

Any mismatch surfaces the offending row id and exits non-zero via
``CommandError``. Empty DB → trivially OK.

Intended to run as a Celery beat job (daily) and as a one-shot check
during incident response. The dashboard operator-status-strip
(PR #192 of the dashboard refit) will surface the most recent result.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.loans.models import AuditLog
from apps.loans.services.audit_chain import GENESIS_HASH, compute_for_row


class Command(BaseCommand):
    help = "Verify AuditLog hash chain integrity. Exits non-zero on any break."

    def handle(self, *args, **opts):
        prior_hash = GENESIS_HASH
        count = 0

        # iterator() so a huge AuditLog table doesn't materialise in RAM.
        for row in AuditLog.objects.order_by("timestamp", "id").iterator():
            count += 1
            if row.hash_prev != prior_hash:
                self._fail(
                    f"FAIL: chain break at row {row.id} (#{count}): "
                    f"hash_prev={row.hash_prev!r} != expected prior {prior_hash!r}"
                )
            expected_self = compute_for_row(row)
            if row.hash_self != expected_self:
                self._fail(
                    f"FAIL: chain break at row {row.id} (#{count}): "
                    f"hash_self stored {row.hash_self!r} != recomputed {expected_self!r}"
                )
            prior_hash = row.hash_self

        self.stdout.write(self.style.SUCCESS(f"Verified {count} AuditLog rows — chain OK"))

    def _fail(self, message: str):
        """Emit the failure to stderr (so operators see it on the terminal)
        and raise CommandError (so callers + CI get a non-zero exit code).
        """
        self.stderr.write(self.style.ERROR(message))
        raise CommandError(message)
