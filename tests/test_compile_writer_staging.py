"""Tests for compile locking, staging directory isolation, and bean-check failure handling."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.compile.errors import CompileLockedError, BeanCheckFailedError
from ironledger.compile.model import load_approved_set
from ironledger.compile.beancheck import BeanCheckResult
from ironledger.compile.writer import acquire_compile_lock, compile_approved


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
        f"VALUES ('stx-1', 'rec-1', 'approved', '2026-09-01', 'Store', '', 1, 'fitid', '{'c'*64}', '2026-09-01T10:00:00Z', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-1', 'stx-1', 'rec-1', 'imported', 0, 'Assets:Checking', -1000, 'USD', 2, '2026-09-01T10:00:00Z'), "
        "       ('sp-2', 'stx-1', 'rec-1', 'contra', 1, 'Expenses:Supplies', 1000, 'USD', 2, '2026-09-01T10:00:00Z')"
    )
    conn.commit()


def test_acquire_lock_prevents_concurrent_access(tmp_path: Path):
    with acquire_compile_lock(tmp_path):
        with pytest.raises(CompileLockedError, match="Compile lock is currently held"):
            with acquire_compile_lock(tmp_path):
                pass


def test_stale_lock_from_hard_crash_blocks_with_actionable_message(tmp_path: Path):
    """A hard crash (SIGKILL / power-loss) leaves ``.compile.lock`` on disk with no
    process holding it and no ``finally`` having run. ``acquire_compile_lock`` must
    refuse with a message that names the lock file AND states the remedy, and must
    leave the stale file in place for the operator to clear deliberately."""
    lock_file = tmp_path / ".compile.lock"
    lock_file.write_text("pid=99999\nsince=2026-09-06T12:00:00Z\n", encoding="utf-8")

    with pytest.raises(CompileLockedError) as excinfo:
        with acquire_compile_lock(tmp_path):
            pass

    msg = str(excinfo.value)
    assert str(lock_file) in msg
    assert "remove" in msg.lower()
    assert lock_file.exists()  # not silently stolen


def test_acquire_lock_writes_self_describing_content(tmp_path: Path):
    """The lock file records the holding pid and an ISO-8601 ``since=`` timestamp so
    an operator inspecting a strand knows what to check before deleting it."""
    with acquire_compile_lock(tmp_path) as lock_file:
        body = lock_file.read_text(encoding="utf-8")
        assert f"pid={os.getpid()}" in body
        assert "since=" in body
    assert not lock_file.exists()  # released on normal exit


def test_bean_check_failure_isolates_staging_and_journals_error(db: sqlite3.Connection, tmp_path: Path):
    _seed_valid(db)
    failed_res = BeanCheckResult(ok=False, exit_code=1, stdout="", stderr="syntax error", beancount_version="3.0.0", compiler_version="0.1.0")

    with patch("ironledger.compile.writer.run_bean_check", return_value=failed_res):
        with pytest.raises(BeanCheckFailedError, match="bean-check validation failed"):
            compile_approved(db, tmp_path)

    # Verify staging moved to failed-run directory with bean-check.txt
    staging_failed_dirs = list((tmp_path / ".staging").glob("failed-*"))
    assert len(staging_failed_dirs) == 1
    assert (staging_failed_dirs[0] / "bean-check.txt").exists()
    assert "syntax error" in (staging_failed_dirs[0] / "bean-check.txt").read_text()

    # Verify run status is failed and audit row emitted
    run_row = db.execute("SELECT status FROM compile_runs").fetchone()
    assert run_row[0] == "failed"
    audit_row = db.execute("SELECT action, result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    assert audit_row == ("compile", "error")
