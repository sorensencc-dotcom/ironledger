"""Phase 2b: upsert_staged can pre-fill the contra posting account from a rule match."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.stage import StagedInput, upsert_staged


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
        source_record_id="doc-1:0", account="Assets:Bank:Checking", iso_date="2026-08-15",
        minor_units=-1299, currency="USD", scale=2, payee="COFFEE BAR", fitid="",
        identity_method="sha256_fallback", identity_fingerprint=fp, institution_account_key="b/c1",
    )


def test_contra_account_none_leaves_null(db):
    stx_id, _ = upsert_staged(db, _input(), now_utc="2026-09-02T10:00:00Z")
    rows = db.execute(
        "SELECT role, account FROM staged_postings WHERE staged_transaction_id = ? ORDER BY posting_index",
        (stx_id,),
    ).fetchall()
    assert rows == [("imported", "Assets:Bank:Checking"), ("contra", None)]


def test_contra_account_filled_when_provided(db):
    stx_id, _ = upsert_staged(
        db, _input(), now_utc="2026-09-02T10:00:00Z", contra_account="Expenses:Coffee"
    )
    status = db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (stx_id,)
    ).fetchone()[0]
    contra = db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx_id,),
    ).fetchone()[0]
    assert status == "pending"
    assert contra == "Expenses:Coffee"


def test_still_idempotent_on_fingerprint(db):
    first_id, first_created = upsert_staged(db, _input(), now_utc="2026-09-02T10:00:00Z",
                                           contra_account="Expenses:Coffee")
    second_id, second_created = upsert_staged(db, _input(), now_utc="2026-09-02T10:05:00Z",
                                              contra_account="Expenses:Other")
    assert first_id == second_id
    assert (first_created, second_created) == (True, False)
    contra = db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (first_id,),
    ).fetchone()[0]
    assert contra == "Expenses:Coffee"  # the second call is a no-op
