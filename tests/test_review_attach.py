"""Phase 15 T03: confirm and reject attach proposals."""

from __future__ import annotations

import json
import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.attach import assign_proposals
from ironledger.ingest.identity import fingerprint
from ironledger.ingest.stage import StagedInput, upsert_staged
from ironledger.review.state import ReviewStateError, confirm_attach, reject_attach

TS = "2026-09-14T18:00:00Z"
ACCOUNT = "Liabilities:CreditCard:ExampleCard"


def _conn() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


def _doc(conn: sqlite3.Connection, doc_id: str, n_records: int) -> None:
    conn.execute(
        "INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, "
        " acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc) "
        "VALUES (?, 'application/pdf', 'utf-8', 'card/example', ?, "
        " ?, 'evidence/source_documents/' || ?, ?)",
        (doc_id, TS, (doc_id + "0" * 64)[:64], doc_id, TS),
    )
    for i in range(n_records):
        rec = f"{doc_id}:{i}"
        conn.execute(
            "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
            " canonical_payload, content_sha256, created_at_utc) VALUES (?, ?, ?, '{}', ?, ?)",
            (rec, doc_id, i, (rec + "0" * 64)[:64], TS),
        )


def _input(*, rec: str, date: str, minor: int, payee: str) -> StagedInput:
    fp = fingerprint(
        account=ACCOUNT, iso_date=date, minor_units=minor, currency="USD",
        payee=payee, institution_account_key="card/example",
    )
    return StagedInput(
        source_record_id=rec, account=ACCOUNT, iso_date=date, minor_units=minor,
        currency="USD", scale=2, payee=payee, fitid="",
        identity_method="sha256_fallback", identity_fingerprint=fp,
        institution_account_key="card/example",
    )


def _stage(conn, staged):
    stx_id, _ = upsert_staged(conn, staged, now_utc=TS)
    return stx_id


def test_confirm_attach_writes_evidence_and_does_not_change_payee_or_postings():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    target = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-1299, payee="SIMPLEFIN CAFE"))
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=-1299, payee="CAFE PDF")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    before_postings = conn.execute("SELECT count(*) FROM staged_postings").fetchone()[0]
    confirm_attach(conn, "ap:pdf:0", target, now_utc=TS)
    after_postings = conn.execute("SELECT count(*) FROM staged_postings").fetchone()[0]
    payee, fp = conn.execute(
        "SELECT payee, identity_fingerprint FROM staged_transactions WHERE staged_transaction_id=?",
        (target,),
    ).fetchone()
    assert after_postings == before_postings
    assert payee == "SIMPLEFIN CAFE"
    assert fp == _input(rec="sf:0", date="2026-09-01", minor=-1299, payee="SIMPLEFIN CAFE").identity_fingerprint
    role, desc = conn.execute(
        "SELECT role, description_text FROM event_evidence WHERE source_record_id='pdf:0'"
    ).fetchone()
    assert role == "enrichment"
    assert desc == "CAFE PDF"
    status = conn.execute("SELECT status FROM attach_proposals WHERE proposal_id='ap:pdf:0'").fetchone()[0]
    assert status == "confirmed"
    audits = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    assert audits == 1


def test_confirm_requires_chosen_id_in_candidates():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-100, payee="A"))
    assign_proposals(
        conn, source_document_id="pdf",
        rows=((_input(rec="pdf:0", date="2026-09-01", minor=-100, payee="B"), 3),),
        now_utc=TS,
    )
    with pytest.raises(ReviewStateError):
        confirm_attach(conn, "ap:pdf:0", "stx:not-a-candidate", now_utc=TS)


def test_reject_unique_creates_pending_from_staged_input():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-400, payee="EXISTING"))
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=-400, payee="NEW PDF")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    before = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    new_id = reject_attach(conn, "ap:pdf:0", now_utc=TS)
    after = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    assert after == before + 1
    payee = conn.execute(
        "SELECT payee FROM staged_transactions WHERE staged_transaction_id=?", (new_id,)
    ).fetchone()[0]
    assert payee == "NEW PDF"
    status = conn.execute("SELECT status FROM attach_proposals WHERE proposal_id='ap:pdf:0'").fetchone()[0]
    assert status == "rejected"


def test_reject_near_miss_does_not_create_pending_by_default():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-800, payee="OLD"))
    incoming = _input(rec="pdf:0", date="2026-09-06", minor=-800, payee="PDF")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    before = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    reject_attach(conn, "ap:pdf:0", now_utc=TS)
    after = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    assert after == before
