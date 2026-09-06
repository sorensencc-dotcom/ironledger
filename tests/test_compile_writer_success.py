"""Tests for complete successful compile, atomic file replacement, and index population."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.errors import CompileError
from ironledger.compile.writer import compile_approved


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_valid(conn: sqlite3.Connection):
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


def test_compile_approved_end_to_end_success(db: sqlite3.Connection, tmp_path: Path):
    _seed_valid(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res):
        summary = compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")

    assert summary.entry_count == 1
    assert "txns/2026.beancount" in summary.year_files

    # Check live ledger files written
    assert (tmp_path / "main.beancount").exists()
    assert (tmp_path / "accounts.beancount").exists()
    assert (tmp_path / "txns" / "2026.beancount").exists()

    # Check ledger index populated
    entries = db.execute("SELECT ledger_entry_id, payee, compile_run_id FROM ledger_entries").fetchall()
    assert len(entries) == 1
    assert entries[0][1] == "Store"
    assert entries[0][2] == summary.compile_run_id

    postings = db.execute("SELECT ledger_posting_id, account, minor_units FROM ledger_postings").fetchall()
    assert len(postings) == 2

    # Check compile_runs row status and actual hash
    run = db.execute("SELECT status, actual_output_hash FROM compile_runs WHERE compile_run_id = ?", (summary.compile_run_id,)).fetchone()
    assert run[0] == "succeeded"
    assert run[1] == summary.output_hash

    # Check audit event
    audit = db.execute("SELECT action, result, compile_run_id FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert audit == ("compile", "ok", summary.compile_run_id)

    # Staging cleaned up on success
    assert not (tmp_path / ".staging" / summary.compile_run_id).exists()

    # Compile journal walks the full success lifecycle
    states = [
        r[0]
        for r in db.execute(
            "SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq",
            (summary.compile_run_id,),
        ).fetchall()
    ]
    for expected in ("started", "bean_checked", "replaced", "succeeded"):
        assert expected in states


def test_compile_approved_hash_mismatch_leaves_run_recoverable(db: sqlite3.Connection, tmp_path: Path):
    _seed_valid(db)
    success_res = BeanCheckResult(ok=True, exit_code=0, stdout="", stderr="", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=success_res), \
         patch("ironledger.compile.writer.compute_actual_output_hash", return_value="deadbeef" * 8):
        with pytest.raises(CompileError):
            compile_approved(db, tmp_path, now_utc="2026-09-06T12:00:00Z")

    # finish_compile_run was never reached
    run = db.execute("SELECT compile_run_id, status FROM compile_runs").fetchone()
    assert run[1] == "started"
    run_id = run[0]

    # Staging preserved for recovery
    assert list((tmp_path / ".staging").glob("crun-*"))

    # Lock released despite the raise
    assert not (tmp_path / ".compile.lock").exists()

    # Journal got past the replace loop but never succeeded
    states = [
        r[0]
        for r in db.execute(
            "SELECT state FROM compile_journal WHERE compile_run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
    ]
    assert states[-1] == "replaced"
    assert "succeeded" not in states
