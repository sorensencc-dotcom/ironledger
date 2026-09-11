# tests/test_migration_0007.py
import sqlite3
import pytest
from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    conn = connect(p)
    migrate_governed(conn)
    conn.close()
    return p


def test_external_id_column_exists(db):
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(staged_transactions)")}
    assert "external_id" in cols
    conn.close()


def test_external_id_unique_constraint(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO source_documents "
        "(source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        "VALUES "
        "('sd1','application/json','utf-8','test',"
        "'2024-01-01T00:00:00Z','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
        "'ref1','2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records "
        "(source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc) "
        "VALUES "
        "('sr1','sd1',0,'payload',"
        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions "
        "(staged_transaction_id,source_record_id,proposed_date,"
        "identity_algo_version,identity_method,identity_fingerprint,created_at_utc,external_id) "
        "VALUES ('stx1','sr1','2024-01-01',1,'fitid',"
        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
        "'2024-01-01T00:00:00Z','ext:1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO staged_transactions "
            "(staged_transaction_id,source_record_id,proposed_date,"
            "identity_algo_version,identity_method,identity_fingerprint,created_at_utc,external_id) "
            "VALUES ('stx2','sr1','2024-01-01',1,'fitid',"
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
            "'2024-01-01T00:00:00Z','ext:1')"
        )
    conn.close()


def test_simplefin_account_map_table(db):
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "simplefin_account_map" in tables
    conn.close()


def test_simplefin_account_map_no_delete(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO simplefin_account_map (remote_account_id, canonical_account, added_at_utc) "
        "VALUES ('act-1', 'Assets:Bank:Checking', '2026-09-10T00:00:00Z')"
    )
    conn.commit()
    with pytest.raises(
        (sqlite3.IntegrityError, sqlite3.OperationalError),
        match="simplefin_account_map is append-only: DELETE is forbidden",
    ):
        conn.execute("DELETE FROM simplefin_account_map WHERE remote_account_id = 'act-1'")
    conn.close()

