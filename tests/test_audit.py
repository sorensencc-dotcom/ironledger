"""Phase 1 task 5: audit chain and append-only enforcement tests.

Tests verify:
- Valid event sequences verify from genesis through head hash.
- Sequence gaps, reorderings, duplicate sequence numbers, broken prev-hashes,
  and tampered payloads fail closed with AuditVerificationError.
- Database triggers strictly reject UPDATE and DELETE operations on audit_events.
- Primary key and uniqueness constraints reject duplicate sequence numbers and hashes.
"""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.audit import (
    AuditEvent,
    AuditVerificationError,
    GENESIS_PREV_HASH,
    append_audit_event,
    compute_event_hash,
    verify_audit_chain,
)
from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def audit_db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with migrations applied."""
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def test_empty_audit_chain_verifies():
    """An empty event sequence or database verifies with zero count and null head."""
    res = verify_audit_chain([])
    assert res.is_valid is True
    assert res.event_count == 0
    assert res.head_hash is None


def test_valid_event_sequence_verifies_genesis_through_head(audit_db: sqlite3.Connection):
    """Appending valid events constructs a verified hash chain from genesis to head."""
    e1 = append_audit_event(
        audit_db,
        actor="operator",
        action="import_source",
        target="evidence/source_documents/doc-1",
        result="ok",
        ts_utc="2026-08-31T14:05:01Z",
    )
    assert e1.seq == 1
    assert e1.prev_event_hash == GENESIS_PREV_HASH

    e2 = append_audit_event(
        audit_db,
        actor="operator",
        action="approve_transaction",
        target="staged-1",
        result="ok",
        ts_utc="2026-08-31T14:05:02Z",
    )
    assert e2.seq == 2
    assert e2.prev_event_hash == e1.event_hash

    e3 = append_audit_event(
        audit_db,
        actor="operator",
        action="compile",
        target="ledger/txns/2026.beancount",
        result="ok",
        ts_utc="2026-08-31T14:05:03Z",
    )
    assert e3.seq == 3
    assert e3.prev_event_hash == e2.event_hash

    audit_db.commit()

    res = verify_audit_chain(audit_db)
    assert res.is_valid is True
    assert res.event_count == 3
    assert res.head_hash == e3.event_hash


def test_tampered_payload_fails_verification():
    """Altering any payload field in an event fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
        event_hash=e1_hash,
    )

    # Valid single event verifies
    assert verify_audit_chain([e1_complete]).is_valid is True

    # Tamper with the actor field while keeping stored event_hash
    tampered = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="attacker",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
        event_hash=e1_hash,
    )
    with pytest.raises(AuditVerificationError, match="hash mismatch"):
        verify_audit_chain([tampered])


def test_sequence_gap_fails_verification():
    """A sequence containing a gap (e.g. 1 -> 3) fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(**{**e1.__dict__, "event_hash": e1_hash})

    e3 = AuditEvent(
        seq=3,
        ts_utc="2026-08-31T14:05:03Z",
        actor="operator",
        action="compile",
        target="ledger",
        result="ok",
        prev_event_hash=e1_hash,
    )
    e3_hash = compute_event_hash(e3)
    e3_complete = AuditEvent(**{**e3.__dict__, "event_hash": e3_hash})

    with pytest.raises(AuditVerificationError, match="sequence gap"):
        verify_audit_chain([e1_complete, e3_complete])


def test_reordered_events_fail_verification():
    """Reordering events in the sequence fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(**{**e1.__dict__, "event_hash": e1_hash})

    e2 = AuditEvent(
        seq=2,
        ts_utc="2026-08-31T14:05:02Z",
        actor="operator",
        action="approve",
        target="staged-1",
        result="ok",
        prev_event_hash=e1_hash,
    )
    e2_hash = compute_event_hash(e2)
    e2_complete = AuditEvent(**{**e2.__dict__, "event_hash": e2_hash})

    with pytest.raises(AuditVerificationError, match="sequence gap or reordering"):
        verify_audit_chain([e2_complete, e1_complete])


def test_broken_prev_event_hash_fails_verification():
    """An event with an invalid prev_event_hash fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(**{**e1.__dict__, "event_hash": e1_hash})

    e2 = AuditEvent(
        seq=2,
        ts_utc="2026-08-31T14:05:02Z",
        actor="operator",
        action="approve",
        target="staged-1",
        result="ok",
        prev_event_hash="f" * 64,  # corrupt previous hash pointer
    )
    e2_hash = compute_event_hash(e2)
    e2_complete = AuditEvent(**{**e2.__dict__, "event_hash": e2_hash})

    with pytest.raises(AuditVerificationError, match="broken hash link"):
        verify_audit_chain([e1_complete, e2_complete])


def test_invalid_genesis_prev_hash_fails_verification():
    """An event with seq=1 that does not point to GENESIS_PREV_HASH fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash="1" * 64,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(**{**e1.__dict__, "event_hash": e1_hash})

    with pytest.raises(AuditVerificationError, match="broken hash link"):
        verify_audit_chain([e1_complete])


def test_invalid_timestamp_fails_verification():
    """An audit event carrying a non-UTC or non-Z timestamp fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01+00:00",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
        prev_event_hash=GENESIS_PREV_HASH,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(**{**e1.__dict__, "event_hash": e1_hash})

    with pytest.raises(AuditVerificationError, match="invalid timestamp"):
        verify_audit_chain([e1_complete])


def test_invalid_result_fails_verification():
    """An audit event carrying an invalid result code fails verification."""
    e1 = AuditEvent(
        seq=1,
        ts_utc="2026-08-31T14:05:01Z",
        actor="operator",
        action="import_source",
        target="doc-1",
        result="unrecognized",
        prev_event_hash=GENESIS_PREV_HASH,
    )
    e1_hash = compute_event_hash(e1)
    e1_complete = AuditEvent(**{**e1.__dict__, "event_hash": e1_hash})

    with pytest.raises(AuditVerificationError, match="invalid result"):
        verify_audit_chain([e1_complete])


def test_append_only_triggers_reject_update(audit_db: sqlite3.Connection):
    """Database triggers forbid UPDATE statements on audit_events."""
    append_audit_event(
        audit_db,
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
    )
    audit_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only: UPDATE is forbidden"):
        audit_db.execute("UPDATE audit_events SET actor = 'attacker' WHERE seq = 1")


def test_append_only_triggers_reject_delete(audit_db: sqlite3.Connection):
    """Database triggers forbid DELETE statements on audit_events."""
    append_audit_event(
        audit_db,
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
    )
    audit_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="audit_events is append-only: DELETE is forbidden"):
        audit_db.execute("DELETE FROM audit_events WHERE seq = 1")



def test_duplicate_sequence_number_rejected_by_primary_key(audit_db: sqlite3.Connection):
    """Replaying or inserting a duplicate sequence number raises IntegrityError."""
    e1 = append_audit_event(
        audit_db,
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
    )
    audit_db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        audit_db.execute(
            "INSERT INTO audit_events "
            "(seq, ts_utc, actor, action, target, result, prev_event_hash, event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                e1.seq,
                "2026-08-31T14:05:02Z",
                "operator",
                "other_action",
                "target",
                "ok",
                GENESIS_PREV_HASH,
                "f" * 64,
            ),
        )


def test_duplicate_event_hash_rejected_by_unique_constraint(audit_db: sqlite3.Connection):
    """Inserting a duplicate event_hash raises IntegrityError."""
    e1 = append_audit_event(
        audit_db,
        actor="operator",
        action="import_source",
        target="doc-1",
        result="ok",
    )
    audit_db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        audit_db.execute(
            "INSERT INTO audit_events "
            "(seq, ts_utc, actor, action, target, result, prev_event_hash, event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2,
                "2026-08-31T14:05:02Z",
                "operator",
                "other_action",
                "target",
                "ok",
                e1.event_hash,
                e1.event_hash,  # duplicate event hash
            ),
        )
