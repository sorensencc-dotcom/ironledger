"""Phase 2b: review categorize sets the contra account and advances pending -> categorized."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.stage import StagedInput, upsert_staged
from ironledger.review.state import ReviewStateError, categorize


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


def _stage(db, fp="d" * 64, contra=None) -> str:
    stx_id, _ = upsert_staged(
        db,
        StagedInput(
            source_record_id="doc-1:0", account="Assets:Bank:Checking", iso_date="2026-08-15",
            minor_units=-1299, currency="USD", scale=2, payee="COFFEE BAR", fitid="",
            identity_method="sha256_fallback", identity_fingerprint=fp,
            institution_account_key="b/c1",
        ),
        now_utc="2026-09-02T10:00:00Z", contra_account=contra,
    )
    db.commit()
    return stx_id


def test_categorize_pending_advances_to_categorized(db):
    stx = _stage(db)
    categorize(db, stx, "Expenses:Coffee", now_utc="2026-09-03T12:00:00Z")
    db.commit()
    status, cat_at = db.execute(
        "SELECT status, categorized_at_utc FROM staged_transactions WHERE staged_transaction_id = ?",
        (stx,),
    ).fetchone()
    contra = db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx,),
    ).fetchone()[0]
    assert (status, cat_at, contra) == ("categorized", "2026-09-03T12:00:00Z", "Expenses:Coffee")
    action, target = db.execute(
        "SELECT action, target FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert action == "review categorize (Expenses:Coffee)"
    assert target == stx


def test_categorize_again_replaces_account_keeps_status(db):
    stx = _stage(db)
    categorize(db, stx, "Expenses:Coffee", now_utc="2026-09-03T12:00:00Z")
    db.commit()
    categorize(db, stx, "Expenses:DiningOut", rule_id="rule:abc", now_utc="2026-09-03T12:05:00Z")
    db.commit()
    status, cat_at = db.execute(
        "SELECT status, categorized_at_utc FROM staged_transactions WHERE staged_transaction_id = ?",
        (stx,),
    ).fetchone()
    contra = db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx,),
    ).fetchone()[0]
    assert (status, cat_at, contra) == ("categorized", "2026-09-03T12:00:00Z", "Expenses:DiningOut")
    assert db.execute(
        "SELECT action FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0] == "review categorize (Expenses:DiningOut; rule rule:abc)"


def test_categorize_rejects_bad_account(db):
    stx = _stage(db)
    with pytest.raises(ValueError):
        categorize(db, stx, "NotARoot:X")


def test_categorize_unknown_id_raises(db):
    with pytest.raises(ReviewStateError):
        categorize(db, "stx:missing", "Expenses:Coffee")
