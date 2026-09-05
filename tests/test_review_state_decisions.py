"""Phase 2b: approve / reject / reopen transitions and the approved-is-terminal rule."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.stage import StagedInput, upsert_staged
from ironledger.review.approve_gate import ApproveGateError
from ironledger.review.state import ReviewStateError, approve, categorize, reject, reopen


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


def test_approve_sets_approved_and_decided_at(db):
    stx = _stage(db, contra="Expenses:Coffee")
    approve(db, stx, now_utc="2026-09-03T13:00:00Z")
    db.commit()
    status, decided = db.execute(
        "SELECT status, decided_at_utc FROM staged_transactions WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()
    assert (status, decided) == ("approved", "2026-09-03T13:00:00Z")
    assert db.execute("SELECT action FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()[0] == "review approve"


def test_approve_propagates_gate_failure(db):
    stx = _stage(db)  # NULL contra
    with pytest.raises(ApproveGateError):
        approve(db, stx)


def test_reject_with_reason(db):
    stx = _stage(db)
    reject(db, stx, reason="duplicate of check 1041", now_utc="2026-09-03T13:00:00Z")
    db.commit()
    status, reason = db.execute(
        "SELECT status, reject_reason FROM staged_transactions WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()
    assert (status, reason) == ("rejected", "duplicate of check 1041")


def test_reject_is_idempotent(db):
    stx = _stage(db)
    reject(db, stx, now_utc="2026-09-03T13:00:00Z")
    db.commit()
    reject(db, stx, now_utc="2026-09-03T13:05:00Z")  # no raise
    db.commit()


def test_reopen_from_rejected_clears_fields_keeps_contra(db):
    stx = _stage(db, contra="Expenses:Coffee")
    categorize(db, stx, "Expenses:Coffee", now_utc="2026-09-03T12:00:00Z")
    reject(db, stx, reason="x", now_utc="2026-09-03T13:00:00Z")
    db.commit()
    reopen(db, stx, now_utc="2026-09-03T14:00:00Z")
    db.commit()
    status, reason, cat_at, decided = db.execute(
        "SELECT status, reject_reason, categorized_at_utc, decided_at_utc "
        "FROM staged_transactions WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()
    contra = db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'", (stx,)
    ).fetchone()[0]
    assert (status, reason, cat_at, decided, contra) == ("pending", None, None, None, "Expenses:Coffee")
    assert db.execute(
        "SELECT action FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0] == "review reopen (from rejected)"


def test_reopen_from_categorized_clears_fields_keeps_contra(db):
    stx = _stage(db, contra="Expenses:Coffee")
    categorize(db, stx, "Expenses:Coffee", now_utc="2026-09-03T12:00:00Z")
    db.commit()
    reopen(db, stx, now_utc="2026-09-03T14:00:00Z")
    db.commit()
    status, reason, cat_at, decided = db.execute(
        "SELECT status, reject_reason, categorized_at_utc, decided_at_utc "
        "FROM staged_transactions WHERE staged_transaction_id = ?", (stx,)
    ).fetchone()
    contra = db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'", (stx,)
    ).fetchone()[0]
    assert (status, reason, cat_at, decided, contra) == ("pending", None, None, None, "Expenses:Coffee")
    assert db.execute(
        "SELECT action FROM audit_events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0] == "review reopen (from categorized)"


def test_approved_is_terminal(db):
    stx = _stage(db, contra="Expenses:Coffee")
    approve(db, stx, now_utc="2026-09-03T13:00:00Z")
    db.commit()
    with pytest.raises(ReviewStateError):
        reject(db, stx)
    with pytest.raises(ReviewStateError):
        reopen(db, stx)
    with pytest.raises(ReviewStateError):
        categorize(db, stx, "Expenses:Other")
