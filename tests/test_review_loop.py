"""Phase 2b: the guided review loop, driven by a scripted stdin stream."""

from __future__ import annotations

import io
import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.errors import AuthorizationError
from ironledger.ingest.stage import StagedInput, upsert_staged
from ironledger.review.loop import run_review_loop


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
    for i in range(3):
        conn.execute(
            "INSERT INTO source_records (source_record_id, source_document_id, record_index, "
            f" canonical_payload, content_sha256, created_at_utc) VALUES ('doc-1:{i}','doc-1',{i},'{{}}',"
            f" '{chr(98 + i) * 64}','2026-09-02T10:00:00Z')"
        )
    conn.commit()
    return conn


def _stage(db, i, payee="COFFEE BAR", contra=None) -> str:
    stx_id, _ = upsert_staged(
        db,
        StagedInput(
            source_record_id=f"doc-1:{i}", account="Assets:Bank:Checking", iso_date="2026-08-15",
            minor_units=-1299, currency="USD", scale=2, payee=payee, fitid="",
            identity_method="sha256_fallback", identity_fingerprint=chr(100 + i) * 64,
            institution_account_key="b/c1",
        ),
        now_utc=f"2026-09-02T10:0{i}:00Z", contra_account=contra,
    )
    db.commit()
    return stx_id


def test_loop_categorize_then_approve_then_reject_then_quit(db):
    a = _stage(db, 0)
    b = _stage(db, 1)
    _c = _stage(db, 2)
    # row a: c -> account -> (re-shown) a ; first 'a' needs the phrase (confirm passed in)
    # row b: r -> reason
    # row c: q
    script = "c\nExpenses:Coffee\na\nr\nnot needed\nq\n"
    counts = run_review_loop(
        db, stdin=io.StringIO(script), stdout=io.StringIO(), db_basename="ledger.db",
        confirm="review-session ledger.db", stdin_isatty=False, now_utc="2026-09-03T12:00:00Z",
    )
    assert counts == {"c": 1, "a": 1, "r": 1, "s": 0}
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (a,)
    ).fetchone()[0] == "approved"
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (b,)
    ).fetchone()[0] == "rejected"
    actions = [r[0] for r in db.execute("SELECT action FROM audit_events ORDER BY seq")]
    assert actions[0] == "review-session start"
    assert actions[-1] == "review-session end (c=1 a=1 r=1 s=0)"
    assert actions.count("review approve") == 1


def test_loop_first_decision_without_phrase_fails_closed(db):
    _stage(db, 0)
    script = "a\n"
    with pytest.raises(AuthorizationError):
        run_review_loop(
            db, stdin=io.StringIO(script), stdout=io.StringIO(), db_basename="ledger.db",
            confirm=None, stdin_isatty=False, now_utc="2026-09-03T12:00:00Z",
        )


def test_loop_phrase_prompted_once_only(db):
    _stage(db, 0, contra="Expenses:Coffee")
    _stage(db, 1, contra="Expenses:Coffee")
    # two approves; phrase provided once via confirm; second 'a' must not re-check
    script = "a\na\nq\n"
    counts = run_review_loop(
        db, stdin=io.StringIO(script), stdout=io.StringIO(), db_basename="ledger.db",
        confirm="review-session ledger.db", stdin_isatty=False, now_utc="2026-09-03T12:00:00Z",
    )
    # both rows had a valid contra -> approve gate succeeds; phrase is checked once
    assert counts["a"] == 2


def test_loop_approve_gate_error_reshows_same_row(db):
    ok = _stage(db, 0, contra="Expenses:Coffee")
    blocked = _stage(db, 1, contra=None)
    # row ok: a -> approves, grants the phrase
    # row blocked: a -> ApproveGateError (missing_account), re-shown same row;
    #   c -> categorize with a valid account; a -> now approves
    script = "a\na\nc\nExpenses:Coffee\na\nq\n"
    stdout = io.StringIO()
    counts = run_review_loop(
        db, stdin=io.StringIO(script), stdout=stdout, db_basename="ledger.db",
        confirm="review-session ledger.db", stdin_isatty=False, now_utc="2026-09-03T12:00:00Z",
    )
    assert counts == {"c": 1, "a": 2, "r": 0, "s": 0}
    assert "cannot approve" in stdout.getvalue()
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (ok,)
    ).fetchone()[0] == "approved"
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (blocked,)
    ).fetchone()[0] == "approved"
