"""Phase 15 T02: candidate matcher — attach, don't duplicate."""

from __future__ import annotations

import json
import sqlite3

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.attach import assign_proposals
from ironledger.ingest.identity import fingerprint
from ironledger.ingest.stage import StagedInput, upsert_staged

TS = "2026-09-14T18:00:00Z"
ACCOUNT = "Liabilities:CreditCard:ExampleCard"
CURRENCY = "USD"
SCALE = 2


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


def _input(*, rec: str, date: str, minor: int, payee: str, key: str = "card/example") -> StagedInput:
    fp = fingerprint(
        account=ACCOUNT, iso_date=date, minor_units=minor, currency=CURRENCY,
        payee=payee, institution_account_key=key,
    )
    return StagedInput(
        source_record_id=rec, account=ACCOUNT, iso_date=date, minor_units=minor,
        currency=CURRENCY, scale=SCALE, payee=payee, fitid="",
        identity_method="sha256_fallback", identity_fingerprint=fp,
        institution_account_key=key,
    )


def _stage(conn: sqlite3.Connection, staged: StagedInput) -> str:
    stx_id, _ = upsert_staged(conn, staged, now_utc=TS)
    return stx_id


def test_unique_hit_writes_one_proposal_and_no_new_staged_row():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    existing = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-1299, payee="SIMPLEFIN CAFE"))
    before = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=-1299, payee="CAFE PDF")
    proposals = assign_proposals(
        conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS,
    )
    after = conn.execute("SELECT count(*) FROM staged_transactions").fetchone()[0]
    assert after == before
    assert len(proposals) == 1
    kind, cands, status = conn.execute(
        "SELECT kind, candidate_staged_ids, status FROM attach_proposals WHERE source_record_id='pdf:0'"
    ).fetchone()
    assert kind == "unique" and status == "pending"
    assert json.loads(cands) == [existing]


def test_nearest_hit_in_window_is_unique():
    conn = _conn()
    _doc(conn, "sf", 2)
    _doc(conn, "pdf", 1)
    a = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-5000, payee="MERCHANT A"))
    b = _stage(conn, _input(rec="sf:1", date="2026-09-02", minor=-5000, payee="MERCHANT B"))
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=-5000, payee="MERCHANT")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    kind, cands = conn.execute(
        "SELECT kind, candidate_staged_ids FROM attach_proposals WHERE source_record_id='pdf:0'"
    ).fetchone()
    assert kind == "unique"
    assert json.loads(cands) == [a]


def test_same_date_hits_remain_ambiguous():
    conn = _conn()
    _doc(conn, "sf", 2)
    _doc(conn, "pdf", 1)
    a = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-5000, payee="MERCHANT A"))
    b = _stage(conn, _input(rec="sf:1", date="2026-09-01", minor=-5000, payee="MERCHANT B"))
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=-5000, payee="MERCHANT")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    kind, cands = conn.execute(
        "SELECT kind, candidate_staged_ids FROM attach_proposals WHERE source_record_id='pdf:0'"
    ).fetchone()
    assert kind == "ambiguous"
    assert set(json.loads(cands)) == {a, b}


def test_two_pdf_rows_cannot_claim_the_same_event():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 2)
    existing = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-2000, payee="ONCE"))
    r0 = _input(rec="pdf:0", date="2026-09-01", minor=-2000, payee="ONCE PDF0")
    r1 = _input(rec="pdf:1", date="2026-09-01", minor=-2000, payee="ONCE PDF1")
    assign_proposals(conn, source_document_id="pdf", rows=((r0, 3), (r1, 3)), now_utc=TS)
    claimed = conn.execute(
        "SELECT source_record_id, candidate_staged_ids FROM attach_proposals WHERE source_document_id='pdf'"
    ).fetchall()
    owners = [sid for sid, raw in claimed if existing in json.loads(raw)]
    assert owners == ["pdf:0"]
    second = conn.execute(
        "SELECT count(*) FROM attach_proposals WHERE source_record_id='pdf:1'"
    ).fetchone()[0]
    assert second == 0


def test_date_outside_window_is_near_miss():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    existing = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-800, payee="MERCHANT"))
    incoming = _input(rec="pdf:0", date="2026-09-06", minor=-800, payee="MERCHANT PDF")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    kind, cands = conn.execute(
        "SELECT kind, candidate_staged_ids FROM attach_proposals WHERE source_record_id='pdf:0'"
    ).fetchone()
    assert kind == "near_miss"
    assert json.loads(cands) == [existing]


def test_sign_flip_in_window_is_near_miss():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    existing = _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-1500, payee="MERCHANT"))
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=1500, payee="MERCHANT PDF")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    kind, cands = conn.execute(
        "SELECT kind, candidate_staged_ids FROM attach_proposals WHERE source_record_id='pdf:0'"
    ).fetchone()
    assert kind == "near_miss"
    assert json.loads(cands) == [existing]


def test_reassign_does_not_duplicate_proposals():
    conn = _conn()
    _doc(conn, "sf", 1)
    _doc(conn, "pdf", 1)
    _stage(conn, _input(rec="sf:0", date="2026-09-01", minor=-100, payee="MERCHANT X"))
    incoming = _input(rec="pdf:0", date="2026-09-01", minor=-100, payee="MERCHANT Y")
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 3),), now_utc=TS)
    n = conn.execute("SELECT count(*) FROM attach_proposals").fetchone()[0]
    assert n == 1


def test_different_same_amount_payee_is_not_a_candidate():
    conn = _conn()
    _doc(conn, "sf", 2)
    _doc(conn, "pdf", 1)
    holiday_inn = _stage(conn, _input(
        rec="sf:0", date="2026-09-06", minor=-1000,
        payee="HOLIDAY INN JOHNSTOWN PA",
    ))
    sunpass = _stage(conn, _input(
        rec="sf:1", date="2026-03-27", minor=-1000,
        payee="SUNPASS*ACC18237778 888-865-5352 FL",
    ))
    incoming = _input(
        rec="pdf:0", date="2026-04-13", minor=-1000,
        payee="SUNPASS*ACC18237778 888-865-5352 FL",
    )
    assign_proposals(conn, source_document_id="pdf", rows=((incoming, 365),), now_utc=TS)
    cands = conn.execute(
        "SELECT candidate_staged_ids FROM attach_proposals WHERE source_record_id='pdf:0'"
    ).fetchone()[0]
    assert json.loads(cands) == [sunpass]
    assert holiday_inn not in json.loads(cands)
