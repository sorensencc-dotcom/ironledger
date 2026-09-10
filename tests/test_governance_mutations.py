"""Tests for IronLedger governance mutation engine and chain verification."""

from __future__ import annotations

import concurrent.futures
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.governance.mutations import (
    GENESIS_MUTATION_PREV_HASH,
    MutationEvent,
    MutationVerificationError,
    MutationVerificationResult,
    append_mutation_event,
    canonical_mutation_bytes,
    compute_canonical_ledger_manifest_hash,
    compute_mutation_hash,
    load_mutation_events,
    verify_mutation_chain,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrations.migrate(conn)
    yield conn
    conn.close()


def test_monotonic_sequence_and_genesis_chaining(db: sqlite3.Connection) -> None:
    """Verify sequence is 1-based, strictly monotonic, and chained from genesis."""
    h0 = "0" * 64
    h1 = "1" * 64
    h2 = "2" * 64

    ev1 = append_mutation_event(
        db,
        operator_session="sess_1",
        action="compile",
        staged_count=2,
        rules_applied=1,
        rules_created=0,
        sha256_before=h0,
        sha256_after=h1,
        ts_utc="2026-09-09T10:00:00Z",
    )
    assert ev1.seq == 1
    assert ev1.prev_mutation_hash == GENESIS_MUTATION_PREV_HASH
    assert len(ev1.mutation_hash) == 64

    ev2 = append_mutation_event(
        db,
        operator_session="sess_2",
        action="compile",
        staged_count=3,
        rules_applied=2,
        rules_created=1,
        sha256_before=h1,
        sha256_after=h2,
        ts_utc="2026-09-09T11:00:00Z",
        audit_seq=42,
    )
    assert ev2.seq == 2
    assert ev2.prev_mutation_hash == ev1.mutation_hash
    assert len(ev2.mutation_hash) == 64
    assert ev2.audit_seq == 42

    res = verify_mutation_chain(db)
    assert res.is_valid is True
    assert res.mutation_count == 2
    assert res.head_hash == ev2.mutation_hash


def test_tamper_detection(db: sqlite3.Connection) -> None:
    """Verify hash mismatch and modified row detection."""
    h0 = "0" * 64
    ev1 = append_mutation_event(
        db,
        operator_session="sess_1",
        action="compile",
        staged_count=1,
        rules_applied=0,
        rules_created=0,
        sha256_before=h0,
        sha256_after="a" * 64,
        ts_utc="2026-09-09T10:00:00Z",
    )

    # Bypass append-only trigger in test to simulate database tampering
    db.execute("DROP TRIGGER IF EXISTS mutation_events_no_update")
    db.execute("UPDATE mutation_events SET staged_count = 99 WHERE seq = 1")

    with pytest.raises(MutationVerificationError, match="hash mismatch"):
        verify_mutation_chain(db)


def test_chain_gap_detection() -> None:
    """Verify gap in sequence numbers raises MutationVerificationError."""
    ev1 = MutationEvent(
        seq=1,
        mutation_id="mut_1",
        ts_utc="2026-09-09T10:00:00Z",
        operator_session="sess_1",
        action="compile",
        staged_count=1,
        rules_applied=0,
        rules_created=0,
        sha256_before="0" * 64,
        sha256_after="1" * 64,
        prev_mutation_hash=GENESIS_MUTATION_PREV_HASH,
    )
    ev1_hash = compute_mutation_hash(ev1)
    ev1 = MutationEvent(**{**ev1.__dict__, "mutation_hash": ev1_hash})

    # Event 2 has sequence 3 (gap!)
    ev2 = MutationEvent(
        seq=3,
        mutation_id="mut_2",
        ts_utc="2026-09-09T11:00:00Z",
        operator_session="sess_2",
        action="compile",
        staged_count=1,
        rules_applied=0,
        rules_created=0,
        sha256_before="1" * 64,
        sha256_after="2" * 64,
        prev_mutation_hash=ev1_hash,
    )
    ev2_hash = compute_mutation_hash(ev2)
    ev2 = MutationEvent(**{**ev2.__dict__, "mutation_hash": ev2_hash})

    with pytest.raises(MutationVerificationError, match="sequence gap or reordering"):
        verify_mutation_chain([ev1, ev2])


def test_broken_hash_link_detection() -> None:
    """Verify broken hash link raises MutationVerificationError."""
    ev1 = MutationEvent(
        seq=1,
        mutation_id="mut_1",
        ts_utc="2026-09-09T10:00:00Z",
        operator_session="sess_1",
        action="compile",
        staged_count=1,
        rules_applied=0,
        rules_created=0,
        sha256_before="0" * 64,
        sha256_after="1" * 64,
        prev_mutation_hash=GENESIS_MUTATION_PREV_HASH,
    )
    ev1_hash = compute_mutation_hash(ev1)
    ev1 = MutationEvent(**{**ev1.__dict__, "mutation_hash": ev1_hash})

    ev2 = MutationEvent(
        seq=2,
        mutation_id="mut_2",
        ts_utc="2026-09-09T11:00:00Z",
        operator_session="sess_2",
        action="compile",
        staged_count=1,
        rules_applied=0,
        rules_created=0,
        sha256_before="1" * 64,
        sha256_after="2" * 64,
        prev_mutation_hash="f" * 64,  # wrong prev hash
    )
    ev2_hash = compute_mutation_hash(ev2)
    ev2 = MutationEvent(**{**ev2.__dict__, "mutation_hash": ev2_hash})

    with pytest.raises(MutationVerificationError, match="broken hash link"):
        verify_mutation_chain([ev1, ev2])


def test_canonical_ledger_manifest_hash(tmp_path: Path) -> None:
    """Verify canonical manifest hash excludes transient files and sorts deterministically."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    # Empty directory
    h_empty = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert len(h_empty) == 64

    # Create files
    (ledger_dir / "main.beancount").write_text("option \"title\" \"Ledger\"\n", encoding="utf-8")
    (ledger_dir / "accounts.beancount").write_text("2020-01-01 open Assets:Bank:Checking USD\n", encoding="utf-8")
    txns_dir = ledger_dir / "txns"
    txns_dir.mkdir()
    (txns_dir / "2026.beancount").write_text("2026-01-01 * \"Opening\" \"Balance\"\n", encoding="utf-8")

    h1 = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert len(h1) == 64
    assert h1 != h_empty

    # Adding .staging.lock, .tmp files, or .staging dir must NOT change the manifest hash
    (ledger_dir / ".staging.lock").write_text("lock", encoding="utf-8")
    (ledger_dir / "temp.tmp").write_text("temporary", encoding="utf-8")
    staging_dir = ledger_dir / ".staging" / "crun-123"
    staging_dir.mkdir(parents=True)
    (staging_dir / "main.beancount").write_text("staged content", encoding="utf-8")

    h2 = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert h2 == h1, "Transient staging and tmp files must be excluded from manifest calculation"

    # Modifying an actual beancount file MUST change the manifest hash
    (ledger_dir / "main.beancount").write_text("option \"title\" \"Modified\"\n", encoding="utf-8")
    h3 = compute_canonical_ledger_manifest_hash(ledger_dir)
    assert h3 != h1


def test_transaction_serialization_begin_immediate(tmp_path: Path) -> None:
    """Verify append_mutation_event acquires BEGIN IMMEDIATE and serializes concurrent writers."""
    db_file = tmp_path / "concurrent.db"
    conn = connect(str(db_file))
    migrations.migrate(conn)
    conn.close()

    # Concurrently append mutation events across multiple threads
    def worker(worker_id: int) -> None:
        c = connect(str(db_file))
        append_mutation_event(
            c,
            operator_session=f"session_{worker_id}",
            action="compile",
            staged_count=1,
            rules_applied=1,
            rules_created=0,
            sha256_before="0" * 64,
            sha256_after=f"{worker_id:064x}"[-64:],
        )
        c.close()

    num_threads = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i + 1) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # Verify that all events were inserted with gapless sequence numbers and valid hash chain
    verify_conn = connect(str(db_file))
    res = verify_mutation_chain(verify_conn)
    assert res.is_valid is True
    assert res.mutation_count == num_threads

    events = load_mutation_events(verify_conn)
    seqs = [e.seq for e in events]
    assert seqs == list(range(1, num_threads + 1))
    verify_conn.close()


def test_empty_chain_verification() -> None:
    """Verify empty source returns valid result with 0 count."""
    res = verify_mutation_chain([])
    assert res.is_valid is True
    assert res.mutation_count == 0
    assert res.head_hash is None
