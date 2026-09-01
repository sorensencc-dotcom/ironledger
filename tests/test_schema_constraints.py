"""Phase 1 task 3: database schema constraint rejection tests.

Tests verify that the SQLite STRICT schema, check constraints, foreign keys,
and uniqueness rules reject invalid amounts, currencies, account names,
timestamps, duplicate identities, and restricted deletes.
"""

from __future__ import annotations

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with migrations applied."""
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def insert_test_document(
    conn: sqlite3.Connection,
    doc_id: str = "doc-1",
    sha256_hex: str = "a" * 64,
    acq_time: str = "2026-08-31T14:05:09Z",
) -> None:
    """Insert a valid source_documents row for test fixtures."""
    conn.execute(
        "INSERT INTO source_documents "
        "(source_document_id, mime_type, encoding, provenance, acquisition_time_utc, "
        " content_sha256, raw_payload_ref, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doc_id,
            "text/csv",
            "utf-8",
            "test-provenance",
            acq_time,
            sha256_hex,
            f"evidence/source_documents/{doc_id}",
            "2026-08-31T14:05:09Z",
        ),
    )


def insert_test_record(
    conn: sqlite3.Connection,
    rec_id: str = "rec-1",
    doc_id: str = "doc-1",
    rec_index: int = 0,
    sha256_hex: str = "b" * 64,
) -> None:
    """Insert a valid source_records row for test fixtures."""
    conn.execute(
        "INSERT INTO source_records "
        "(source_record_id, source_document_id, record_index, canonical_payload, "
        " content_sha256, created_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
        (rec_id, doc_id, rec_index, '{"amount": 100}', sha256_hex, "2026-08-31T14:05:09Z"),
    )


def insert_test_staged_transaction(
    conn: sqlite3.Connection,
    staged_id: str = "staged-1",
    rec_id: str = "rec-1",
    algo_version: int = 1,
    fingerprint: str = "c" * 64,
) -> None:
    """Insert a valid staged_transactions row for test fixtures."""
    conn.execute(
        "INSERT INTO staged_transactions "
        "(staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        " identity_algo_version, identity_method, identity_fingerprint, created_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            staged_id,
            rec_id,
            "pending",
            "2026-08-31",
            "Test Payee",
            "Test Narration",
            algo_version,
            "sha256_fallback",
            fingerprint,
            "2026-08-31T14:05:09Z",
        ),
    )


def test_amount_type_strict_enforcement(db_conn: sqlite3.Connection):
    """Reject floating-point values and non-integer strings in minor_units."""
    insert_test_document(db_conn)
    insert_test_record(db_conn)
    insert_test_staged_transaction(db_conn)

    db_conn.execute(
        "INSERT INTO ledger_entries "
        "(ledger_entry_id, staged_transaction_id, entry_date, flag, created_at_utc) "
        "VALUES ('entry-1', 'staged-1', '2026-08-31', '*', '2026-08-31T14:05:09Z')"
    )

    # STRICT table rejects float inserted into INTEGER column
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Assets:Bank:Checking', 12.34, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )

    # STRICT table rejects non-integer text strings
    for bad_val in ("abc", "12.34", b"blob"):
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO ledger_postings "
                "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
                " currency, minor_unit_scale, identity_algo_version, identity_method, "
                " identity_fingerprint, created_at_utc) VALUES "
                "('post-1', 'entry-1', 'rec-1', 'Assets:Bank:Checking', ?, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
                (bad_val, "d" * 64),
            )

    # NOT NULL rejects None / NULL
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Assets:Bank:Checking', NULL, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )



def test_currency_schema_constraints(db_conn: sqlite3.Connection):
    """Reject lowercase, malformed length, and negative scale currency values."""
    insert_test_document(db_conn)
    insert_test_record(db_conn)
    insert_test_staged_transaction(db_conn)

    db_conn.execute(
        "INSERT INTO ledger_entries "
        "(ledger_entry_id, staged_transaction_id, entry_date, flag, created_at_utc) "
        "VALUES ('entry-1', 'staged-1', '2026-08-31', '*', '2026-08-31T14:05:09Z')"
    )

    # Lowercase currency rejected by CHECK GLOB '[A-Z][A-Z][A-Z]'
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Assets:Bank:Checking', 1000, 'usd', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )

    # 4-letter currency rejected
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Assets:Bank:Checking', 1000, 'USDA', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )

    # Negative scale rejected by CHECK (minor_unit_scale >= 0)
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Assets:Bank:Checking', 1000, 'USD', -1, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )


def test_account_root_schema_constraints(db_conn: sqlite3.Connection):
    """Reject unapproved account roots and root names missing sub-accounts."""
    insert_test_document(db_conn)
    insert_test_record(db_conn)
    insert_test_staged_transaction(db_conn)

    db_conn.execute(
        "INSERT INTO ledger_entries "
        "(ledger_entry_id, staged_transaction_id, entry_date, flag, created_at_utc) "
        "VALUES ('entry-1', 'staged-1', '2026-08-31', '*', '2026-08-31T14:05:09Z')"
    )

    # Bad root rejected by account GLOB CHECK
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Cash:Checking', 1000, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )

    # Single root without colon sub-account rejected
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO ledger_postings "
            "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
            " currency, minor_unit_scale, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) VALUES "
            "('post-1', 'entry-1', 'rec-1', 'Assets', 1000, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("d" * 64,),
        )


def test_timestamp_glob_check_rejections(db_conn: sqlite3.Connection):
    """Reject timestamps missing trailing Z, with numeric offsets, or non-ISO shapes."""
    for bad_ts in (
        "2026-08-31T14:05:09",
        "2026-08-31 14:05:09Z",
        "2026-08-31T14:05:09+00:00",
        "2026-08-31T14:05:09-04:00",
        "2026/08/31 14:05:09",
        "yesterday",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            insert_test_document(db_conn, doc_id=f"doc-{bad_ts}", sha256_hex="e" * 64, acq_time=bad_ts)


def test_duplicate_identity_rejection(db_conn: sqlite3.Connection):
    """Reject duplicate identity insertions and verify original row is not overwritten."""
    insert_test_document(db_conn)
    insert_test_record(db_conn)

    fingerprint = "f" * 64
    insert_test_staged_transaction(
        db_conn,
        staged_id="staged-first",
        rec_id="rec-1",
        algo_version=1,
        fingerprint=fingerprint,
    )

    # Attempting to insert another transaction with identical algo_version and fingerprint
    with pytest.raises(sqlite3.IntegrityError):
        insert_test_staged_transaction(
            db_conn,
            staged_id="staged-second",
            rec_id="rec-1",
            algo_version=1,
            fingerprint=fingerprint,
        )

    # Verify first row remains untouched
    cursor = db_conn.execute(
        "SELECT staged_transaction_id, source_record_id, payee FROM staged_transactions "
        "WHERE identity_algo_version = 1 AND identity_fingerprint = ?",
        (fingerprint,),
    )
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0] == ("staged-first", "rec-1", "Test Payee")


def test_identity_version_immutability(db_conn: sqlite3.Connection):
    """Verify new identity algorithm versions do not alter or re-identify historical rows."""
    insert_test_document(db_conn)
    insert_test_record(db_conn, rec_id="rec-1", rec_index=0, sha256_hex="1" * 64)
    insert_test_record(db_conn, rec_id="rec-2", rec_index=1, sha256_hex="2" * 64)

    fp_v1 = "a" * 64
    fp_v2 = "b" * 64

    # Insert under algorithm version 1
    insert_test_staged_transaction(
        db_conn,
        staged_id="staged-v1",
        rec_id="rec-1",
        algo_version=1,
        fingerprint=fp_v1,
    )

    # Introduce algorithm version 2 for subsequent transaction
    insert_test_staged_transaction(
        db_conn,
        staged_id="staged-v2",
        rec_id="rec-2",
        algo_version=2,
        fingerprint=fp_v2,
    )

    # Assert historical row remains byte-identical
    row_v1 = db_conn.execute(
        "SELECT staged_transaction_id, identity_algo_version, identity_fingerprint "
        "FROM staged_transactions WHERE staged_transaction_id = 'staged-v1'"
    ).fetchone()
    assert row_v1 == ("staged-v1", 1, fp_v1)

    row_v2 = db_conn.execute(
        "SELECT staged_transaction_id, identity_algo_version, identity_fingerprint "
        "FROM staged_transactions WHERE staged_transaction_id = 'staged-v2'"
    ).fetchone()
    assert row_v2 == ("staged-v2", 2, fp_v2)


def test_hash_length_checks(db_conn: sqlite3.Connection):
    """Reject hashes that are not 64-character strings."""
    with pytest.raises(sqlite3.IntegrityError):
        insert_test_document(db_conn, doc_id="doc-short-hash", sha256_hex="a" * 32)

    with pytest.raises(sqlite3.IntegrityError):
        insert_test_document(db_conn, doc_id="doc-long-hash", sha256_hex="a" * 65)


def test_enum_value_checks(db_conn: sqlite3.Connection):
    """Reject unlisted enum values across status, result, and identity method columns."""
    insert_test_document(db_conn)
    insert_test_record(db_conn)

    # staged_transactions.status must be 'pending', 'approved', or 'rejected'
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO staged_transactions "
            "(staged_transaction_id, source_record_id, status, proposed_date, identity_algo_version, "
            " identity_method, identity_fingerprint, created_at_utc) VALUES "
            "('staged-bad', 'rec-1', 'invalid_status', '2026-08-31', 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
            ("a" * 64,),
        )

    # staged_transactions.identity_method must be 'fitid' or 'sha256_fallback'
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO staged_transactions "
            "(staged_transaction_id, source_record_id, status, proposed_date, identity_algo_version, "
            " identity_method, identity_fingerprint, created_at_utc) VALUES "
            "('staged-bad', 'rec-1', 'pending', '2026-08-31', 1, 'custom_hash', ?, '2026-08-31T14:05:09Z')",
            ("a" * 64,),
        )


def test_foreign_key_restricted_deletes(db_conn: sqlite3.Connection):
    """Verify that deleting referenced evidence or workflow rows raises IntegrityError."""
    insert_test_document(db_conn, doc_id="doc-fk")
    insert_test_record(db_conn, rec_id="rec-fk", doc_id="doc-fk")
    insert_test_staged_transaction(db_conn, staged_id="staged-fk", rec_id="rec-fk")

    db_conn.execute(
        "INSERT INTO compile_runs "
        "(compile_run_id, beancount_version, compiler_version, input_hash, "
        " intended_output_hash, status, started_at_utc) VALUES "
        "('run-1', '2.3.6', '1.0.0', ?, ?, 'succeeded', '2026-08-31T14:05:09Z')",
        ("a" * 64, "b" * 64),
    )

    db_conn.execute(
        "INSERT INTO ledger_entries "
        "(ledger_entry_id, staged_transaction_id, compile_run_id, entry_date, flag, created_at_utc) "
        "VALUES ('entry-fk', 'staged-fk', 'run-1', '2026-08-31', '*', '2026-08-31T14:05:09Z')"
    )

    db_conn.execute(
        "INSERT INTO ledger_postings "
        "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
        " currency, minor_unit_scale, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) VALUES "
        "('post-fk', 'entry-fk', 'rec-fk', 'Assets:Bank:Checking', 1000, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
        ("c" * 64,),
    )

    # Restricted delete of source_documents referenced by source_records
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute("DELETE FROM source_documents WHERE source_document_id = 'doc-fk'")

    # Restricted delete of source_records referenced by staged_transactions and ledger_postings
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute("DELETE FROM source_records WHERE source_record_id = 'rec-fk'")

    # Restricted delete of staged_transactions referenced by ledger_entries
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute("DELETE FROM staged_transactions WHERE staged_transaction_id = 'staged-fk'")

    # Restricted delete of compile_runs referenced by ledger_entries
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute("DELETE FROM compile_runs WHERE compile_run_id = 'run-1'")


def test_cascade_delete_within_projection_only(db_conn: sqlite3.Connection):
    """Verify ledger_entries cascade to ledger_postings without touching evidence."""
    insert_test_document(db_conn, doc_id="doc-casc")
    insert_test_record(db_conn, rec_id="rec-casc", doc_id="doc-casc")
    insert_test_staged_transaction(db_conn, staged_id="staged-casc", rec_id="rec-casc")

    db_conn.execute(
        "INSERT INTO ledger_entries "
        "(ledger_entry_id, staged_transaction_id, entry_date, flag, created_at_utc) "
        "VALUES ('entry-casc', 'staged-casc', '2026-08-31', '*', '2026-08-31T14:05:09Z')"
    )

    db_conn.execute(
        "INSERT INTO ledger_postings "
        "(ledger_posting_id, ledger_entry_id, source_record_id, account, minor_units, "
        " currency, minor_unit_scale, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) VALUES "
        "('post-casc', 'entry-casc', 'rec-casc', 'Assets:Bank:Checking', 1000, 'USD', 2, 1, 'fitid', ?, '2026-08-31T14:05:09Z')",
        ("c" * 64,),
    )

    # Deleting ledger_entries cascades to ledger_postings
    db_conn.execute("DELETE FROM ledger_entries WHERE ledger_entry_id = 'entry-casc'")

    postings_count = db_conn.execute(
        "SELECT count(*) FROM ledger_postings WHERE ledger_posting_id = 'post-casc'"
    ).fetchone()[0]
    assert postings_count == 0

    # Evidence and staging remain intact
    doc_exists = db_conn.execute(
        "SELECT count(*) FROM source_documents WHERE source_document_id = 'doc-casc'"
    ).fetchone()[0]
    rec_exists = db_conn.execute(
        "SELECT count(*) FROM source_records WHERE source_record_id = 'rec-casc'"
    ).fetchone()[0]
    staged_exists = db_conn.execute(
        "SELECT count(*) FROM staged_transactions WHERE staged_transaction_id = 'staged-casc'"
    ).fetchone()[0]

    assert doc_exists == 1
    assert rec_exists == 1
    assert staged_exists == 1
