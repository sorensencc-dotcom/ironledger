"""Integration tests for interrupted compile crash injection and recovery."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.writer import compile_approved
from ironledger.compile.recover import recover_dangling_compile


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed(conn: sqlite3.Connection):
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
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', '', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Food', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


def test_crash_mid_replace_recovers_cleanly(db: sqlite3.Connection, tmp_path: Path):
    _seed(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    original_replace = os.replace
    call_count = 0

    def mock_replace_crash(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("Simulated power failure / crash mid-replace")
        return original_replace(src, dst)

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res), \
         patch("os.replace", side_effect=mock_replace_crash):
        with pytest.raises(OSError, match="Simulated power failure"):
            compile_approved(db, tmp_path)

    # A started run is left active, staging exists
    run_row = db.execute("SELECT compile_run_id, status FROM compile_runs WHERE status = 'started'").fetchone()
    assert run_row is not None
    run_id = run_row[0]

    # Execute recovery
    rec = recover_dangling_compile(db, tmp_path)
    assert rec.action == "recovered"
    assert rec.compile_run_id == run_id

    # Verify status is now 'recovered'
    status = db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0]
    assert status == "recovered"

    # Verify live ledger files exist and are valid
    assert (tmp_path / "main.beancount").exists()
    assert (tmp_path / "accounts.beancount").exists()
    assert (tmp_path / "txns" / "2026.beancount").exists()


def test_crash_during_recovery_then_second_recover_completes(db: sqlite3.Connection, tmp_path: Path):
    """A4.1: crash the recovery itself mid-write, then a second `compile recover`
    drives the run to 'recovered' with no row-4 escalation (re-entrancy)."""
    _seed(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")
    original_replace = os.replace

    # First: crash the primary compile mid-replace.
    n = 0
    def crash_second(src, dst):
        nonlocal n
        n += 1
        if n == 2:
            raise OSError("crash mid-replace")
        return original_replace(src, dst)
    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res), \
         patch("os.replace", side_effect=crash_second):
        with pytest.raises(OSError):
            compile_approved(db, tmp_path)
    run_id = db.execute("SELECT compile_run_id FROM compile_runs WHERE status = 'started'").fetchone()[0]

    # Now crash the FIRST recovery attempt mid-write.
    m = 0
    def crash_first_recovery(src, dst):
        nonlocal m
        m += 1
        if m == 1:
            raise OSError("crash mid-recovery")
        return original_replace(src, dst)
    with patch("os.replace", side_effect=crash_first_recovery):
        with pytest.raises(OSError):
            recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:00:00Z")
    assert db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0] == "started"

    # Second recovery, no injected fault: must complete.
    rec = recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:00:10Z")
    assert rec.action == "recovered"
    assert db.execute("SELECT status FROM compile_runs WHERE compile_run_id = ?", (run_id,)).fetchone()[0] == "recovered"
    states = [r[0] for r in db.execute("SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq", (run_id,)).fetchall()]
    assert "refused" not in states and states[-1] == "recovered"

    # Item 12 tail: a third recover is a safe no-op.
    again = recover_dangling_compile(db, tmp_path, now_utc="2026-09-06T12:00:20Z")
    assert again.action in {"none", "recovered"}
