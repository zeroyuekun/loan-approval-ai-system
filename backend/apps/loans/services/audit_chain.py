"""Hash-chained AuditLog — tamper evidence for the audit trail.

PR-2 of the security gap-closure cycle.

Every AuditLog row carries:
  - hash_prev: the hash_self of the chronologically prior row (or
    GENESIS_HASH for the first row).
  - hash_self: SHA-256 of a canonical JSON payload containing every
    field that defines the row's meaning.

Verification: walk the table in (timestamp, id) order; recompute each
row's expected hash_self and compare to stored. Any mismatch =
tampering (or a bug).

Concurrency: AuditLog.save() acquires a Postgres transaction-scoped
advisory lock so two concurrent inserts can't both pick the same prior
row and create a fork.
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from typing import Any

from django.db import connection

# Genesis hash — value of hash_prev for the chain root.
GENESIS_HASH = "0" * 64

# Stable advisory-lock key used by AuditLog.save() to serialize inserts.
# Choosing a fixed integer rather than a string so we use the int form
# of pg_advisory_xact_lock (cheaper than hashtext on a string key).
AUDIT_LOG_LOCK_KEY = 0xA0D17

# Process-local fallback for non-Postgres backends (SQLite in dev).
# Production always runs Postgres so this branch never triggers there,
# but it keeps the concurrent-insert test deterministic in dev.
_PROCESS_LOCAL_LOCK = threading.Lock()


def compute_hash(
    *,
    hash_prev: str,
    timestamp: str,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> str:
    """SHA-256 of a canonical JSON payload binding the row together.

    The canonical form is sorted-keys / no-whitespace JSON so that
    semantically identical rows hash identically regardless of dict
    insertion order or string formatting.

    Tampering with any single field (including hash_prev) produces a
    different digest, which is what makes the chain detectable.
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


@contextmanager
def audit_log_insert_lock():
    """Serialize AuditLog inserts so concurrent writers can't fork the chain.

    On Postgres: transaction-scoped advisory lock (pg_advisory_xact_lock)
    that auto-releases at COMMIT/ROLLBACK. The caller MUST be inside a
    transaction (transaction.atomic()) — outside a transaction the lock
    is a no-op.

    On other backends (SQLite in dev): falls back to a process-local
    threading.Lock so the dev test suite stays deterministic. Production
    always runs Postgres.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [AUDIT_LOG_LOCK_KEY])
        yield
    else:
        with _PROCESS_LOCAL_LOCK:
            yield


def latest_hash_self() -> str:
    """Return the chain head's hash_self, or GENESIS_HASH if the chain
    is empty. Caller must hold the audit_log_insert_lock or accept
    races."""
    # Avoid circular import — AuditLog imports from this module.
    from apps.loans.models import AuditLog

    prior = AuditLog.objects.order_by("-timestamp", "-id").only("hash_self").first()
    return prior.hash_self if prior and prior.hash_self else GENESIS_HASH


def compute_for_row(audit_log) -> str:
    """Compute the canonical hash_self for an existing AuditLog row.

    Used by verify_audit_chain and by AuditLog.save(). Pulls fields
    off the instance so callers don't have to repeat the field list.
    """
    return compute_hash(
        hash_prev=audit_log.hash_prev,
        timestamp=audit_log.timestamp.isoformat(),
        user_id=str(audit_log.user_id) if audit_log.user_id else None,
        action=audit_log.action,
        resource_type=audit_log.resource_type,
        resource_id=audit_log.resource_id,
        details=audit_log.details or {},
    )
