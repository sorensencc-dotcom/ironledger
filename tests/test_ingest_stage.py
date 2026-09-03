"""Phase 2a: staged transaction and posting upsert is idempotent and balanced."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import ParseError
from ironledger.ingest.stage import StagedInput, minor_units_from_text, upsert_staged


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        f"VALUES ('doc-1','text/csv','utf-8','p','2026-09-02T10:00:00Z','{'a'*64}',"
        " 'evidence/source_documents/doc-1','2026-09-02T10:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
        f" canonical_payload, content_sha256, created_at_utc) VALUES ('doc-1:0','doc-1',0,'{{}}',"
        f" '{'b'*64}','2026-09-02T10:00:00Z')"
    )
    conn.commit()
    return conn


def _input(fp: str = "d" * 64) -> StagedInput:
    return StagedInput(
        source_record_id="doc-1:0", account="Assets:Bank:Checking:B", iso_date="2026-08-15",
        minor_units=-1299, currency="USD", scale=2, payee="COFFEE BAR", fitid="",
        identity_method="sha256_fallback", identity_fingerprint=fp, institution_account_key="b/c1",
    )


@pytest.mark.parametrize(
    "text,scale,expected",
    [("-12.99", 2, -1299), ("2000.00", 2, 200000), ("-45", 2, -4500), ("100", 0, 100)],
)
def test_minor_units_from_text_exact(text: str, scale: int, expected: int):
    assert minor_units_from_text(text, scale) == expected


def test_minor_units_rejects_too_many_fraction_digits():
    with pytest.raises(ParseError):
        minor_units_from_text("1.239", 2)


def test_upsert_writes_header_and_two_balanced_postings(db: sqlite3.Connection):
    stx_id, created = upsert_staged(db, _input(), now_utc="2026-09-02T10:00:00Z")
    assert created is True
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx_id,)
    ).fetchone()[0] == "pending"
    rows = db.execute(
        "SELECT role, account, minor_units FROM staged_postings "
        "WHERE staged_transaction_id = ? ORDER BY posting_index", (stx_id,)
    ).fetchall()
    assert rows == [("imported", "Assets:Bank:Checking:B", -1299), ("contra", None, 1299)]


def test_upsert_is_idempotent_on_fingerprint(db: sqlite3.Connection):
    first_id, first_created = upsert_staged(db, _input(), now_utc="2026-09-02T10:00:00Z")
    second_id, second_created = upsert_staged(db, _input(), now_utc="2026-09-02T10:00:05Z")
    assert (first_id, second_created) == (second_id, False)
    assert db.execute("SELECT count(*) FROM staged_transactions").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM staged_postings").fetchone()[0] == 2
