"""Phase 2b: review auto-match fills NULL or Expenses:Unassigned contra pending rows from rules."""

from __future__ import annotations

import sqlite3

import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.ingest.stage import StagedInput, upsert_staged
from ironledger.review.rules import add_rule
from ironledger.review.state import auto_match


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


def _stage(db, i, payee, account="Assets:Bank:Checking", contra=None) -> str:
    stx_id, _ = upsert_staged(
        db,
        StagedInput(
            source_record_id=f"doc-1:{i}", account=account, iso_date="2026-08-15",
            minor_units=-1299, currency="USD", scale=2, payee=payee, fitid="",
            identity_method="sha256_fallback", identity_fingerprint=chr(100 + i) * 64,
            institution_account_key="b/c1",
        ),
        now_utc="2026-09-02T10:00:00Z", contra_account=contra,
    )
    db.commit()
    return stx_id


def test_auto_match_fills_and_categorizes(db):
    add_rule(db, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             now_utc="2026-09-03T09:00:00Z")
    db.commit()
    a = _stage(db, 0, "COFFEE BAR")
    b = _stage(db, 1, "GAS STATION")
    matched, candidates = auto_match(db, now_utc="2026-09-03T12:00:00Z")
    db.commit()
    assert (matched, candidates) == (1, 2)
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (a,)
    ).fetchone()[0] == "categorized"
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (b,)
    ).fetchone()[0] == "pending"
    actions = [r[0] for r in db.execute("SELECT action FROM audit_events ORDER BY seq")]
    assert "review auto-match (matched 1 of 2)" in actions
    assert any(x.startswith("review auto-match (Expenses:Coffee; rule ") for x in actions)


def test_auto_match_retargets_unassigned(db):
    add_rule(db, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             now_utc="2026-09-03T09:00:00Z")
    db.commit()
    a = _stage(db, 0, "COFFEE BAR", contra="Expenses:Unassigned")
    b = _stage(db, 1, "GAS STATION", contra="Expenses:Unassigned")
    matched, candidates = auto_match(db, now_utc="2026-09-03T12:00:00Z")
    db.commit()
    assert (matched, candidates) == (1, 2)
    assert db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (a,),
    ).fetchone()[0] == "Expenses:Coffee"
    assert db.execute(
        "SELECT status FROM staged_transactions WHERE staged_transaction_id = ?", (a,)
    ).fetchone()[0] == "categorized"
    assert db.execute(
        "SELECT account FROM staged_postings WHERE staged_transaction_id = ? AND role = 'contra'",
        (b,),
    ).fetchone()[0] == "Expenses:Unassigned"


def test_auto_match_skips_already_categorized(db):
    add_rule(db, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             now_utc="2026-09-03T09:00:00Z")
    db.commit()
    _stage(db, 0, "COFFEE BAR", contra="Expenses:Manual")
    matched, candidates = auto_match(db, now_utc="2026-09-03T12:00:00Z")
    assert (matched, candidates) == (0, 0)


def test_auto_match_honors_importing_account_filter(db):
    add_rule(db, match_type="exact", pattern="coffee bar", target_account="Expenses:Coffee",
             now_utc="2026-09-03T09:00:00Z")
    db.commit()
    _stage(db, 0, "COFFEE BAR", account="Assets:Bank:Checking")
    _stage(db, 1, "COFFEE BAR", account="Assets:Bank:Savings")
    matched, candidates = auto_match(db, importing_account="Assets:Bank:Savings",
                                    now_utc="2026-09-03T12:00:00Z")
    assert (matched, candidates) == (1, 1)
