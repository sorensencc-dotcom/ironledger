"""Phase 2b: the approve gate refuses incomplete or unbalanced staged transactions."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.stage import StagedInput, upsert_staged
from ironledger.review.approve_gate import ApproveGateError, check_approvable
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


def test_null_contra_account_blocks(db):
    stx = _stage(db)
    with pytest.raises(ApproveGateError) as exc:
        check_approvable(db, stx)
    assert exc.value.reason == "missing_account"


def test_categorized_and_balanced_passes(db):
    stx = _stage(db)
    categorize(db, stx, "Expenses:Coffee", now_utc="2026-09-03T12:00:00Z")
    db.commit()
    check_approvable(db, stx)  # no raise


def test_invalid_account_blocks(db):
    stx = _stage(db)
    db.execute(
        "UPDATE staged_postings SET account = 'Assets:lowercase' WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx,),
    )
    db.commit()
    with pytest.raises(ApproveGateError) as exc:
        check_approvable(db, stx)
    assert exc.value.reason == "invalid_account"


def test_unbalanced_blocks(db):
    stx = _stage(db, contra="Expenses:Coffee")
    db.execute(
        "UPDATE staged_postings SET minor_units = -1 WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx,),
    )
    db.commit()
    with pytest.raises(ApproveGateError) as exc:
        check_approvable(db, stx)
    assert exc.value.reason == "unbalanced"


def test_multi_currency_blocks(db):
    stx = _stage(db, contra="Expenses:Coffee")
    db.execute(
        "UPDATE staged_postings SET currency = 'EUR' WHERE staged_transaction_id = ? AND role = 'contra'",
        (stx,),
    )
    db.commit()
    with pytest.raises(ApproveGateError) as exc:
        check_approvable(db, stx)
    assert exc.value.reason in ("multi_currency", "unbalanced")


def test_approved_row_blocks_on_status(db):
    stx = _stage(db, contra="Expenses:Coffee")
    db.execute("UPDATE staged_transactions SET status = 'approved' WHERE staged_transaction_id = ?", (stx,))
    db.commit()
    with pytest.raises(ApproveGateError) as exc:
        check_approvable(db, stx)
    assert exc.value.reason == "status"


def test_unknown_id_raises_review_state_error_not_approve_gate_error(db):
    # An unknown id is a lookup error, not an authorization denial: it must raise
    # ReviewStateError (mapped by the CLI to exit 5, no audit event), matching every
    # sibling review command (show, categorize, reject, reopen) rather than
    # ApproveGateError (mapped to exit 3 + a denied audit event).
    with pytest.raises(ReviewStateError):
        check_approvable(db, "does-not-exist")
