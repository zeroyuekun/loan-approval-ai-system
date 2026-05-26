"""verify_audit_chain management command — PR-2 of security gap-closure.

Recomputes hashes for every AuditLog row in chronological order and
exits non-zero if any link is broken (tampered, deleted, or rewritten).
"""

import io
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.loans.models import AuditLog
from apps.loans.services.audit_chain import GENESIS_HASH


@pytest.mark.django_db
def test_verify_passes_on_empty_db():
    """Zero rows = trivially valid chain."""
    out = io.StringIO()
    call_command("verify_audit_chain", stdout=out)
    assert "OK" in out.getvalue() or "verified" in out.getvalue().lower()


@pytest.mark.django_db
def test_verify_passes_on_clean_chain():
    for i in range(10):
        AuditLog.objects.create(action="evt", resource_type="R", resource_id=str(i))

    out = io.StringIO()
    call_command("verify_audit_chain", stdout=out)
    output = out.getvalue()
    assert "10" in output  # row count surfaced
    assert "OK" in output or "verified" in output.lower()


@pytest.mark.django_db
def test_verify_detects_tampered_action():
    """An attacker rewrites the 'action' field directly via SQL — the
    command must detect the hash mismatch and report which row broke."""
    log1 = AuditLog.objects.create(
        action="login", resource_type="User", resource_id="alice"
    )
    AuditLog.objects.create(
        action="login", resource_type="User", resource_id="bob"
    )

    # Tamper: rewrite action without recomputing hash_self
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE loans_auditlog SET action = %s WHERE id = %s",
            ["loan.approve", str(log1.id)],
        )

    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises((CommandError, SystemExit)):
        call_command("verify_audit_chain", stdout=out, stderr=err)

    combined = out.getvalue() + err.getvalue()
    assert "FAIL" in combined or "break" in combined.lower() or "mismatch" in combined.lower()
    assert str(log1.id) in combined


@pytest.mark.django_db
def test_verify_detects_deleted_row():
    """Deleting a middle row breaks the chain because the next row's
    hash_prev no longer matches the new prior row's hash_self."""
    rows = [
        AuditLog.objects.create(action="evt", resource_type="R", resource_id=str(i))
        for i in range(3)
    ]
    # Delete the middle row (raw SQL — bypasses Django since AuditLog
    # has delete permissions removed)
    with connection.cursor() as cur:
        cur.execute("DELETE FROM loans_auditlog WHERE id = %s", [str(rows[1].id)])

    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises((CommandError, SystemExit)):
        call_command("verify_audit_chain", stdout=out, stderr=err)

    combined = out.getvalue() + err.getvalue()
    # The break shows up at the row that survived but lost its parent
    assert str(rows[2].id) in combined


@pytest.mark.django_db
def test_verify_detects_tampered_details():
    """Same shape as action tampering but on the JSON details field."""
    log = AuditLog.objects.create(
        action="loan.approve",
        resource_type="LoanApplication",
        resource_id=str(uuid.uuid4()),
        details={"amount": 50000},
    )

    with connection.cursor() as cur:
        cur.execute(
            "UPDATE loans_auditlog SET details = %s::jsonb WHERE id = %s",
            ['{"amount": 5000000}', str(log.id)],
        )

    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises((CommandError, SystemExit)):
        call_command("verify_audit_chain", stdout=out, stderr=err)
    combined = out.getvalue() + err.getvalue()
    assert "FAIL" in combined or "mismatch" in combined.lower() or "break" in combined.lower()


@pytest.mark.django_db
def test_verify_detects_corrupted_genesis():
    """First row's hash_prev must be GENESIS_HASH; rewriting it is a break."""
    log = AuditLog.objects.create(action="evt", resource_type="R", resource_id="1")
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE loans_auditlog SET hash_prev = %s WHERE id = %s",
            ["f" * 64, str(log.id)],
        )
    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises((CommandError, SystemExit)):
        call_command("verify_audit_chain", stdout=out, stderr=err)
    combined = out.getvalue() + err.getvalue()
    assert str(log.id) in combined
