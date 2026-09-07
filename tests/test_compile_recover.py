"""Tests for compiler recovery decision table."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.errors import AmbiguousRecoveryError
from ironledger.compile.hashing import compute_input_hash, compute_intended_output_hash
from ironledger.compile.journal import start_compile_run
from ironledger.compile.model import load_approved_set
from ironledger.compile.recover import recover_dangling_compile
from ironledger.compile.render import render_ledger


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_approved(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1', 'text/csv', 'utf-8', 'p', '2026-09-01T10:00:00Z', '{'a'*64}', 'ref-1', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b'*64}', '2026-09-01T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, proposed_date, payee, narration, identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', 'Supplies', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Supplies', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


def _seed_started_run_with_valid_staging(
    db: sqlite3.Connection, tmp_path: Path
) -> tuple[Path, str, dict[str, bytes]]:
    """Seed an approved set, render it, write the full render into
    ``tmp_path/.staging/<run_id>/``, and open a matching ``started`` compile run.

    Returns ``(ledger_dir, run_id, rendered_dict)``.
    """
    _seed_approved(db)
    approved_set = load_approved_set(db)
    rendered = render_ledger(approved_set)

    run_id = "crun-seedvalid01"
    staging_dir = tmp_path / ".staging" / run_id
    for rel, data in rendered.items():
        dst = staging_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)

    start_compile_run(
        db,
        compile_run_id=run_id,
        beancount_version="3.0.0",
        compiler_version="0.1.0",
        input_hash=compute_input_hash(approved_set),
        intended_output_hash=compute_intended_output_hash(rendered),
        now_utc="2026-09-06T11:00:00Z",
    )
    return tmp_path, run_id, rendered


def test_recover_when_nothing_to_recover(db: sqlite3.Connection, tmp_path: Path):
    res = recover_dangling_compile(db, tmp_path)
    assert res.action == "none"
    assert res.compile_run_id is None


def test_recover_pre_write_abort_marks_failed(db: sqlite3.Connection, tmp_path: Path):
    run_id = "crun-aborted"
    start_compile_run(
        db, compile_run_id=run_id, beancount_version="3.0.0", compiler_version="0.1.0",
        input_hash="a"*64, intended_output_hash="b"*64
    )
    # Staging directory absent
    res = recover_dangling_compile(db, tmp_path)
    assert res.action == "marked_failed"
    assert res.compile_run_id == run_id

    row = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()
    assert row[0] == "failed"


def test_recover_staging_hash_mismatch_refuses(db: sqlite3.Connection, tmp_path: Path):
    run_id = "crun-corrupt"
    start_compile_run(
        db, compile_run_id=run_id, beancount_version="3.0.0", compiler_version="0.1.0",
        input_hash="a"*64, intended_output_hash="b"*64
    )
    staging = tmp_path / ".staging" / run_id
    staging.mkdir(parents=True)
    (staging / "main.beancount").write_bytes(b"corrupted")

    with pytest.raises(AmbiguousRecoveryError, match="staging hash mismatch|re-render|unrecognized"):
        recover_dangling_compile(db, tmp_path)

    # Run remains started, journal records refused
    row = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()
    assert row[0] == "started"
    j_state = db.execute("SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()[0]
    assert j_state == "refused"


def test_recovery_is_reentrant_after_mid_recovery_crash(db: sqlite3.Connection, tmp_path: Path):
    """A4.1: a crash during recovery (only some live files written) still recovers on
    the next `compile recover` — no row-4 escalation, terminal state 'recovered'."""
    ledger_dir, run_id, rendered = _seed_started_run_with_valid_staging(db, tmp_path)
    # Simulate a partial recovery: write only accounts.beancount to live, leave the rest.
    (ledger_dir / "accounts.beancount").write_bytes(rendered["accounts.beancount"])

    res = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:00Z")
    assert res.action == "recovered"
    assert db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0] == "recovered"
    # Every live file now holds the intended bytes.
    for rel, want in rendered.items():
        assert (ledger_dir / rel).read_bytes() == want
    # No 'refused' journal row.
    states = [r[0] for r in db.execute("SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq", (run_id,)).fetchall()]
    assert "refused" not in states
    assert states[-1] == "recovered"


def test_recover_rerun_after_full_recovery_is_safe_noop(db: sqlite3.Connection, tmp_path: Path):
    """A4.1: re-running `compile recover` once the tree is intact is a safe no-op."""
    ledger_dir, run_id, rendered = _seed_started_run_with_valid_staging(db, tmp_path)
    first = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:00Z")
    assert first.action == "recovered"
    # Second call: nothing dangling now, so 'none'; if the run were still 'started'
    # it would re-finalize without error and without a row-4 refusal.
    second = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:05Z")
    assert second.action in {"none", "recovered"}
    for rel, want in rendered.items():
        assert (ledger_dir / rel).read_bytes() == want


def test_recovery_sweeps_stale_atomic_write_temp_files(db: sqlite3.Connection, tmp_path: Path):
    """Carry-forward from Task 9 review: a crash between `_atomic_write_file`'s temp
    write and its `os.replace` leaves a `<name>.tmp-<hex>` sibling behind. Deterministic
    recovery must unlink stale temps in both the ledger dir and `txns/`."""
    ledger_dir, run_id, rendered = _seed_started_run_with_valid_staging(db, tmp_path)
    stray_root = ledger_dir / "main.beancount.tmp-deadbeef"
    stray_root.write_bytes(b"half-written")
    (ledger_dir / "txns").mkdir(parents=True, exist_ok=True)
    stray_txns = ledger_dir / "txns" / "2026.beancount.tmp-cafef00d"
    stray_txns.write_bytes(b"half-written")

    res = recover_dangling_compile(db, ledger_dir, now_utc="2026-09-06T12:00:00Z")
    assert res.action == "recovered"
    assert not stray_root.exists()
    assert not stray_txns.exists()
    for rel, want in rendered.items():
        assert (ledger_dir / rel).read_bytes() == want
