"""Phase 2a: migration 0003 creates staged_postings with role and account constraints."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _seed_txn(conn: sqlite3.Connection) -> tuple[str, str]:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        "VALUES ('doc-1', 'text/csv', 'utf-8', 'test', '2026-09-02T10:00:00Z', "
        f" '{'a' * 64}', 'evidence/source_documents/doc-1', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
        " canonical_payload, content_sha256, created_at_utc) "
        f"VALUES ('rec-1', 'doc-1', 0, '{{}}', '{'b' * 64}', '2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, "
        " proposed_date, payee, narration, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) "
        f"VALUES ('stx-1', 'rec-1', 'pending', '2026-09-01', 'Store', '', 1, 'sha256_fallback', "
        f" '{'c' * 64}', '2026-09-02T10:00:00Z')"
    )
    conn.commit()
    return "stx-1", "rec-1"


def test_migrate_reaches_version_three(db: sqlite3.Connection):
    assert migrations.current_version(db) == 3


def test_staged_postings_accepts_imported_named_and_contra_null(db: sqlite3.Connection):
    stx, rec = _seed_txn(db)
    db.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, "
        " role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        f"VALUES ('sp-1', '{stx}', '{rec}', 'imported', 0, 'Assets:Bank:Checking', -1299, 'USD', 2, "
        " '2026-09-02T10:00:00Z')"
    )
    db.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, "
        " role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        f"VALUES ('sp-2', '{stx}', '{rec}', 'contra', 1, NULL, 1299, 'USD', 2, "
        " '2026-09-02T10:00:00Z')"
    )
    db.commit()
    total = db.execute(
        "SELECT sum(minor_units) FROM staged_postings WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()[0]
    assert total == 0


def test_imported_posting_may_not_have_null_account(db: sqlite3.Connection):
    stx, rec = _seed_txn(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, "
            " role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
            f"VALUES ('sp-x', '{stx}', '{rec}', 'imported', 0, NULL, -1299, 'USD', 2, "
            " '2026-09-02T10:00:00Z')"
        )


def test_posting_index_is_unique_per_transaction(db: sqlite3.Connection):
    stx, rec = _seed_txn(db)
    db.execute(
        "INSERT INTO staged_postings VALUES ('sp-1', ?, ?, 'imported', 0, 'Assets:Bank:Checking', "
        " -1299, 'USD', 2, '2026-09-02T10:00:00Z')",
        (stx, rec),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO staged_postings VALUES ('sp-2', ?, ?, 'contra', 0, NULL, 1299, 'USD', 2, "
            " '2026-09-02T10:00:00Z')",
            (stx, rec),
        )


def test_deleting_staged_transaction_cascades_to_postings(db: sqlite3.Connection):
    stx, rec = _seed_txn(db)
    db.execute(
        "INSERT INTO staged_postings VALUES ('sp-1', ?, ?, 'imported', 0, 'Assets:Bank:Checking', "
        " -1299, 'USD', 2, '2026-09-02T10:00:00Z')",
        (stx, rec),
    )
    db.commit()
    db.execute("DELETE FROM staged_transactions WHERE staged_transaction_id = ?", (stx,))
    db.commit()
    assert db.execute("SELECT count(*) FROM staged_postings").fetchone()[0] == 0


def test_deleting_source_record_is_restricted_by_a_posting(db: sqlite3.Connection):
    stx, rec = _seed_txn(db)
    db.execute(
        "INSERT INTO staged_postings VALUES ('sp-1', ?, ?, 'imported', 0, 'Assets:Bank:Checking', "
        " -1299, 'USD', 2, '2026-09-02T10:00:00Z')",
        (stx, rec),
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM source_records WHERE source_record_id = ?", (rec,))
        db.commit()
