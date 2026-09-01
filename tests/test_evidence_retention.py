"""Phase 1 task 4: evidence retention and destructive delete transaction tests.

Tests verify that attempts to delete referenced source evidence fail closed,
and that failed destructive transactions leave all evidence, staging records,
and index references unmodified. Tests also verify that projection cleanup
operates in complete isolation from retained evidence.
"""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def populated_db() -> sqlite3.Connection:
    """Return a database connection with a full reference graph populated."""
    conn = connect(":memory:")
    migrations.migrate(conn)

    # 1. Source document (immutable retained evidence)
    conn.execute(
        "INSERT INTO source_documents "
        "(source_document_id, mime_type, encoding, provenance, acquisition_time_utc, "
        " content_sha256, raw_payload_ref, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "doc-100",
            "text/csv",
            "utf-8",
            "checking-export-20260831",
            "2026-08-31T14:05:09Z",
            "a" * 64,
            "evidence/source_documents/doc-100",
            "2026-08-31T14:05:09Z",
        ),
    )

    # 2. Source record (per-transaction evidence)
    conn.execute(
        "INSERT INTO source_records "
        "(source_record_id, source_document_id, record_index, canonical_payload, "
        " content_sha256, created_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "rec-100",
            "doc-100",
            0,
            '{"date": "2026-08-31", "amount": -10000, "payee": "Grocery Store"}',
            "b" * 64,
            "2026-08-31T14:05:09Z",
        ),
    )

    # 3. Staged transaction (proposed workflow state)
    conn.execute(
        "INSERT INTO staged_transactions "
        "(staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        " identity_algo_version, identity_method, identity_fingerprint, created_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "staged-100",
            "rec-100",
            "approved",
            "2026-08-31",
            "Grocery Store",
            "Weekly supplies",
            1,
            "sha256_fallback",
            "c" * 64,
            "2026-08-31T14:05:09Z",
        ),
    )

    # 4. Compile run (audit trail of compilation)
    conn.execute(
        "INSERT INTO compile_runs "
        "(compile_run_id, beancount_version, compiler_version, input_hash, "
        " intended_output_hash, actual_output_hash, status, started_at_utc, finished_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run-100",
            "2.3.6",
            "1.0.0",
            "d" * 64,
            "e" * 64,
            "e" * 64,
            "succeeded",
            "2026-08-31T14:05:10Z",
            "2026-08-31T14:05:11Z",
        ),
    )

    # 5. Ledger entry (projection index)
    conn.execute(
        "INSERT INTO ledger_entries "
        "(ledger_entry_id, staged_transaction_id, compile_run_id, entry_date, flag, payee, narration, created_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "entry-100",
            "staged-100",
            "run-100",
            "2026-08-31",
            "*",
            "Grocery Store",
            "Weekly supplies",
            "2026-08-31T14:05:12Z",
        ),
    )

    # 6. Ledger postings (projection index postings)
    conn.execute(
        "INSERT INTO ledger_postings "
        "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
        " currency, minor_unit_scale, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "post-100-a",
            "entry-100",
            "rec-100",
            "Assets:Bank:Checking:Ally",
            -10000,
            "USD",
            2,
            1,
            "sha256_fallback",
            "c" * 64,
            "2026-08-31T14:05:12Z",
        ),
    )
    conn.execute(
        "INSERT INTO ledger_postings "
        "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
        " currency, minor_unit_scale, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "post-100-b",
            "entry-100",
            "rec-100",
            "Expenses:Groceries:Supermarket",
            10000,
            "USD",
            2,
            1,
            "sha256_fallback",
            "c" * 64,
            "2026-08-31T14:05:12Z",
        ),
    )

    # 7. Audit event
    conn.execute(
        "INSERT INTO audit_events "
        "(seq, ts_utc, actor, action, target, result, projection_version, compile_run_id, "
        " prev_event_hash, event_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "2026-08-31T14:05:13Z",
            "operator",
            "compile",
            "ledger/txns/2026.beancount",
            "ok",
            "1.0.0",
            "run-100",
            "0" * 64,
            "f" * 64,
        ),
    )

    conn.commit()
    return conn


def snapshot_database(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Capture full row snapshots across all tables in the database."""
    tables = [
        "source_documents",
        "source_records",
        "staged_transactions",
        "compile_runs",
        "ledger_entries",
        "ledger_postings",
        "audit_events",
    ]
    snapshot = {}
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        snapshot[table] = rows
    return snapshot


def test_destructive_delete_source_document_fails_and_leaves_state_intact(
    populated_db: sqlite3.Connection,
):
    """Attempting to delete a referenced source document rolls back and leaves state unchanged."""
    initial_snapshot = snapshot_database(populated_db)

    # Attempt destructive delete within a transaction
    with pytest.raises(sqlite3.IntegrityError):
        populated_db.execute("BEGIN TRANSACTION")
        populated_db.execute("DELETE FROM source_documents WHERE source_document_id = 'doc-100'")

    populated_db.rollback()

    post_snapshot = snapshot_database(populated_db)
    assert post_snapshot == initial_snapshot


def test_destructive_delete_source_record_fails_and_leaves_state_intact(
    populated_db: sqlite3.Connection,
):
    """Attempting to delete a referenced source record rolls back and leaves state unchanged."""
    initial_snapshot = snapshot_database(populated_db)

    with pytest.raises(sqlite3.IntegrityError):
        populated_db.execute("BEGIN TRANSACTION")
        populated_db.execute("DELETE FROM source_records WHERE source_record_id = 'rec-100'")

    populated_db.rollback()

    post_snapshot = snapshot_database(populated_db)
    assert post_snapshot == initial_snapshot


def test_multi_statement_destructive_batch_fails_closed(populated_db: sqlite3.Connection):
    """A batch containing mutations and a destructive evidence delete rolls back entirely."""
    initial_snapshot = snapshot_database(populated_db)

    with pytest.raises(sqlite3.IntegrityError):
        populated_db.execute("BEGIN TRANSACTION")
        # Mutate staging
        populated_db.execute(
            "UPDATE staged_transactions SET narration = 'Mutated narration' WHERE staged_transaction_id = 'staged-100'"
        )
        # Attempt destructive evidence deletion (fails on FK RESTRICT)
        populated_db.execute("DELETE FROM source_documents WHERE source_document_id = 'doc-100'")

    populated_db.rollback()

    post_snapshot = snapshot_database(populated_db)
    assert post_snapshot == initial_snapshot


def test_update_restrict_on_evidence_ids_fails_and_leaves_state_intact(
    populated_db: sqlite3.Connection,
):
    """Updating primary keys of referenced evidence rows is restricted and fails."""
    initial_snapshot = snapshot_database(populated_db)

    # Attempt to update source_document_id
    with pytest.raises(sqlite3.IntegrityError):
        populated_db.execute("BEGIN TRANSACTION")
        populated_db.execute(
            "UPDATE source_documents SET source_document_id = 'doc-renamed' WHERE source_document_id = 'doc-100'"
        )

    populated_db.rollback()

    # Attempt to update source_record_id
    with pytest.raises(sqlite3.IntegrityError):
        populated_db.execute("BEGIN TRANSACTION")
        populated_db.execute(
            "UPDATE source_records SET source_record_id = 'rec-renamed' WHERE source_record_id = 'rec-100'"
        )

    populated_db.rollback()

    post_snapshot = snapshot_database(populated_db)
    assert post_snapshot == initial_snapshot


def test_projection_cleanup_isolation(populated_db: sqlite3.Connection):
    """Purging ledger index projection rows leaves all evidence and staging rows intact."""
    # Count rows before projection wipe
    doc_count = populated_db.execute("SELECT count(*) FROM source_documents").fetchone()[0]
    rec_count = populated_db.execute("SELECT count(*) FROM source_records").fetchone()[0]
    staged_count = populated_db.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    compile_count = populated_db.execute("SELECT count(*) FROM compile_runs").fetchone()[0]
    audit_count = populated_db.execute("SELECT count(*) FROM audit_events").fetchone()[0]

    # Delete ledger entries (cascades to ledger_postings)
    populated_db.execute("DELETE FROM ledger_entries")
    populated_db.commit()

    # Verify projection index is empty
    assert populated_db.execute("SELECT count(*) FROM ledger_entries").fetchone()[0] == 0
    assert populated_db.execute("SELECT count(*) FROM ledger_postings").fetchone()[0] == 0

    # Verify evidence, staging, compile runs, and audit logs remain untouched
    assert populated_db.execute("SELECT count(*) FROM source_documents").fetchone()[0] == doc_count
    assert populated_db.execute("SELECT count(*) FROM source_records").fetchone()[0] == rec_count
    assert populated_db.execute("SELECT count(*) FROM staged_transactions").fetchone()[0] == staged_count
    assert populated_db.execute("SELECT count(*) FROM compile_runs").fetchone()[0] == compile_count
    assert populated_db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == audit_count
