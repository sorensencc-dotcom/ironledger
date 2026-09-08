"""Phase 2b: migration 0004 widens staged_transactions.status and adds review columns."""

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


def _seed(conn: sqlite3.Connection) -> tuple[str, str]:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1','text/csv','utf-8','p','2026-09-02T10:00:00Z','{'a'*64}',"
        " 'evidence/source_documents/doc-1','2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
        f" canonical_payload, content_sha256, created_at_utc) VALUES ('rec-1','doc-1',0,'{{}}',"
        f" '{'b'*64}','2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, "
        " proposed_date, payee, narration, identity_algo_version, identity_method, "
        " identity_fingerprint, created_at_utc) "
        f"VALUES ('stx-1','rec-1','pending','2026-09-01','Store','',1,'sha256_fallback',"
        f" '{'c'*64}','2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_postings (staged_posting_id, staged_transaction_id, source_record_id, "
        " role, posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc) "
        "VALUES ('sp-0','stx-1','rec-1','imported',0,'Assets:Bank:Checking',-1299,'USD',2,"
        " '2026-09-02T10:00:00Z'),"
        " ('sp-1','stx-1','rec-1','contra',1,NULL,1299,'USD',2,'2026-09-02T10:00:00Z')"
    )
    conn.commit()
    return "stx-1", "rec-1"


def test_reaches_version_four(db: sqlite3.Connection):
    assert migrations.current_version(db) == max(m.version for m in migrations.discover_migrations())


def test_status_check_accepts_categorized_and_rejects_unknown(db: sqlite3.Connection):
    _seed(db)
    db.execute("UPDATE staged_transactions SET status = 'categorized' WHERE staged_transaction_id = 'stx-1'")
    db.commit()
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = 'stx-1'"
    ).fetchone()[0] == "categorized"
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE staged_transactions SET status = 'archived' WHERE staged_transaction_id = 'stx-1'")


def test_new_columns_present_and_default_null(db: sqlite3.Connection):
    _seed(db)
    row = db.execute(
        "SELECT reject_reason, categorized_at_utc FROM staged_transactions WHERE staged_transaction_id = 'stx-1'"
    ).fetchone()
    assert row == (None, None)


def test_rebuild_preserves_rows_and_foreign_keys(db: sqlite3.Connection):
    _seed(db)
    assert db.execute("SELECT count(*) FROM staged_transactions").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM staged_postings").fetchone()[0] == 2
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_identity_uniqueness_still_enforced(db: sqlite3.Connection):
    _seed(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO staged_transactions (staged_transaction_id, source_record_id, status, "
            " proposed_date, payee, narration, identity_algo_version, identity_method, "
            " identity_fingerprint, created_at_utc) "
            f"VALUES ('stx-dup','rec-1','pending','2026-09-01','Store','',1,'sha256_fallback',"
            f" '{'c'*64}','2026-09-02T10:00:00Z')"
        )


def test_categorization_rules_table_and_index_present(db: sqlite3.Connection):
    db.execute(
        "INSERT INTO categorization_rules (rule_id, match_type, pattern, importing_account, "
        " target_account, priority, active, created_at_utc) "
        "VALUES ('r1','exact','coffee bar',NULL,'Expenses:Coffee',100,1,'2026-09-03T10:00:00Z')"
    )
    db.commit()
    assert db.execute("SELECT count(*) FROM categorization_rules").fetchone()[0] == 1
    names = {r[1] for r in db.execute("PRAGMA index_list('categorization_rules')")}
    assert "idx_categorization_rules_active_priority" in names


def test_source_record_index_survives_rebuild(db: sqlite3.Connection):
    names = {r[1] for r in db.execute("PRAGMA index_list('staged_transactions')")}
    assert "idx_staged_source_record" in names
