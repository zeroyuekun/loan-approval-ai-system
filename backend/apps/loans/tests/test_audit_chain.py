"""Hash-chained AuditLog — PR-2 of the security gap-closure cycle.

Spec: docs/superpowers/specs/2026-05-25-security-gap-closure-design.md (PR-2)

The chain provides tamper evidence:
  - Every AuditLog row carries `hash_prev` (prior row's hash_self) and
    `hash_self` (SHA-256 of a canonical payload including hash_prev).
  - The first row's `hash_prev` is the genesis constant "0" * 64.
  - Concurrent inserts are serialized via a Postgres advisory lock so
    the chain stays linear under load.
"""

import hashlib
import json
import threading
import uuid

import pytest
from django.db import connection

from apps.loans.models import AuditLog
from apps.loans.services.audit_chain import (
    AUDIT_LOG_LOCK_KEY,
    GENESIS_HASH,
    compute_hash,
)


# ---------------------------------------------------------------------------
# compute_hash — pure function
# ---------------------------------------------------------------------------


def test_genesis_hash_is_64_zeros():
    """The chain root is the constant '0' * 64 (defined by spec)."""
    assert GENESIS_HASH == "0" * 64
    assert len(GENESIS_HASH) == 64


def test_compute_hash_returns_sha256_hex():
    digest = compute_hash(
        hash_prev=GENESIS_HASH,
        timestamp="2026-05-26T10:00:00+00:00",
        user_id=None,
        action="login",
        resource_type="User",
        resource_id="abc-123",
        details={"ip": "1.2.3.4"},
    )
    assert isinstance(digest, str)
    assert len(digest) == 64
    # Hex characters only
    int(digest, 16)


def test_compute_hash_is_deterministic():
    """Same inputs → same hash."""
    kw = dict(
        hash_prev=GENESIS_HASH,
        timestamp="2026-05-26T10:00:00+00:00",
        user_id="u1",
        action="login",
        resource_type="User",
        resource_id="abc-123",
        details={"ip": "1.2.3.4"},
    )
    assert compute_hash(**kw) == compute_hash(**kw)


def test_compute_hash_changes_if_any_field_changes():
    """Tampering with any single field must produce a different hash."""
    base = dict(
        hash_prev=GENESIS_HASH,
        timestamp="2026-05-26T10:00:00+00:00",
        user_id="u1",
        action="login",
        resource_type="User",
        resource_id="abc-123",
        details={"ip": "1.2.3.4"},
    )
    base_hash = compute_hash(**base)

    for field, mutated in [
        ("hash_prev", "f" * 64),
        ("timestamp", "2026-05-26T10:00:01+00:00"),
        ("user_id", "u2"),
        ("action", "logout"),
        ("resource_type", "Session"),
        ("resource_id", "xyz-999"),
        ("details", {"ip": "5.6.7.8"}),
    ]:
        mutated_kw = {**base, field: mutated}
        assert compute_hash(**mutated_kw) != base_hash, (
            f"hash must change when '{field}' changes"
        )


def test_compute_hash_details_dict_key_order_does_not_matter():
    """Canonical JSON: {a:1,b:2} and {b:2,a:1} must hash identically."""
    h1 = compute_hash(
        hash_prev=GENESIS_HASH,
        timestamp="t",
        user_id=None,
        action="a",
        resource_type="R",
        resource_id="1",
        details={"a": 1, "b": 2},
    )
    h2 = compute_hash(
        hash_prev=GENESIS_HASH,
        timestamp="t",
        user_id=None,
        action="a",
        resource_type="R",
        resource_id="1",
        details={"b": 2, "a": 1},
    )
    assert h1 == h2


def test_compute_hash_matches_expected_canonical_form():
    """Pin the canonical form so we can reconstruct hashes elsewhere
    (e.g., the verify_audit_chain command) without coupling to internals."""
    payload = {
        "hash_prev": GENESIS_HASH,
        "timestamp": "2026-05-26T10:00:00+00:00",
        "user_id": None,
        "action": "login",
        "resource_type": "User",
        "resource_id": "abc-123",
        "details": {"ip": "1.2.3.4"},
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    actual = compute_hash(**payload)
    assert actual == expected


# ---------------------------------------------------------------------------
# AuditLog.save() — chain insertion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_first_audit_log_has_genesis_hash_prev():
    log = AuditLog.objects.create(
        action="login",
        resource_type="User",
        resource_id="abc-123",
        details={"ip": "1.2.3.4"},
    )
    assert log.hash_prev == GENESIS_HASH
    assert log.hash_self != ""
    assert len(log.hash_self) == 64


@pytest.mark.django_db
def test_subsequent_audit_log_links_to_prior():
    first = AuditLog.objects.create(
        action="login",
        resource_type="User",
        resource_id="abc-123",
    )
    second = AuditLog.objects.create(
        action="logout",
        resource_type="User",
        resource_id="abc-123",
    )
    assert second.hash_prev == first.hash_self
    assert second.hash_self != first.hash_self


@pytest.mark.django_db
def test_hash_self_matches_reconstructed_payload():
    """hash_self must be reconstructable from the row's fields alone."""
    log = AuditLog.objects.create(
        action="loan.approve",
        resource_type="LoanApplication",
        resource_id=str(uuid.uuid4()),
        details={"amount": 50000, "tier": "A"},
    )
    expected = compute_hash(
        hash_prev=log.hash_prev,
        timestamp=log.timestamp.isoformat(),
        user_id=str(log.user_id) if log.user_id else None,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        details=log.details,
    )
    assert log.hash_self == expected


@pytest.mark.django_db
def test_chain_holds_across_many_sequential_inserts():
    """Walk a 20-row chain and verify every link."""
    rows = [
        AuditLog.objects.create(
            action="evt",
            resource_type="R",
            resource_id=str(i),
            details={"i": i},
        )
        for i in range(20)
    ]
    assert rows[0].hash_prev == GENESIS_HASH
    for i in range(1, 20):
        assert rows[i].hash_prev == rows[i - 1].hash_self
    # All hash_selfs are unique
    assert len({r.hash_self for r in rows}) == 20


@pytest.mark.django_db(transaction=True)
def test_concurrent_inserts_produce_valid_linear_chain():
    """The Postgres advisory lock serializes inserts so threads can't
    race the chain (two threads picking the same hash_prev would create
    a fork, breaking the invariant)."""
    N = 5
    barrier = threading.Barrier(N)

    def insert(i: int):
        barrier.wait()  # release all threads simultaneously
        try:
            AuditLog.objects.create(
                action="concurrent",
                resource_type="Stress",
                resource_id=str(i),
                details={"thread": i},
            )
        finally:
            connection.close()  # release thread-local DB connection

    threads = [threading.Thread(target=insert, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = list(AuditLog.objects.order_by("timestamp", "id").all())
    assert len(rows) == N, f"Expected {N} rows, got {len(rows)}"

    # First row anchors to genesis
    assert rows[0].hash_prev == GENESIS_HASH

    # Each subsequent row's hash_prev must equal the prior row's hash_self
    for i in range(1, N):
        assert rows[i].hash_prev == rows[i - 1].hash_self, (
            f"Chain break at row {i}: "
            f"hash_prev={rows[i].hash_prev!r} != prior.hash_self={rows[i - 1].hash_self!r}"
        )

    # Every hash_self is unique — no two rows are the same link
    hash_selfs = {r.hash_self for r in rows}
    assert len(hash_selfs) == N, "Duplicate hash_self values — concurrency broke chain"

    # Every hash_prev (except genesis) is some other row's hash_self
    prev_set = {r.hash_prev for r in rows} - {GENESIS_HASH}
    assert prev_set.issubset(hash_selfs), (
        "Some hash_prev values don't link to any row's hash_self — fork detected"
    )


@pytest.mark.django_db
def test_audit_log_lock_key_is_stable():
    """The advisory lock key must not change between releases — locks
    are keyed by integer and we rely on every process using the same one."""
    assert isinstance(AUDIT_LOG_LOCK_KEY, int)
    # Pin the value so accidental edits surface in code review
    assert AUDIT_LOG_LOCK_KEY == 0xA0D17  # spells AUDIT-ish in hex


@pytest.mark.django_db
def test_resaving_existing_row_does_not_recompute_hash():
    """save() on an existing row must not rewrite hash_self — chain
    rows are append-only."""
    log = AuditLog.objects.create(action="a", resource_type="R", resource_id="1")
    original = log.hash_self
    log.details = {"modified": "after the fact"}
    log.save()
    log.refresh_from_db()
    # hash_self stays pinned to the value computed at insert time
    assert log.hash_self == original
