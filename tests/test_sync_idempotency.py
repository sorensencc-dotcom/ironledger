# tests/test_sync_idempotency.py
import sqlite3
import pytest
from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload

PAYLOAD = {"accounts": [{"id": "acct1", "currency": "USD", "transactions": [
    {"id": "tx1", "posted": 1704067200, "amount": "-12.00", "description": "Coffee", "memo": ""},
]}]}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    migrate_governed(conn)
    return conn, tmp_path


def test_first_poll_inserts(db):
    conn, tmp = db
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD,
        evidence_path=tmp / "ev.raw", account_map={"acct1": "Assets:Checking"})
    assert ins == 1 and skip == 0


def test_second_poll_skips(db):
    conn, tmp = db
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev.raw", account_map={"acct1": "Assets:Checking"})
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev2.raw", account_map={"acct1": "Assets:Checking"})
    assert ins == 0 and skip == 1


def test_prior_status_untouched(db):
    conn, tmp = db
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev.raw", account_map={"acct1": "Assets:Checking"})
    conn.execute("UPDATE staged_transactions SET status='approved'")
    conn.commit()
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev2.raw", account_map={"acct1": "Assets:Checking"})
    assert conn.execute("SELECT status FROM staged_transactions").fetchone()["status"] == "approved"


def test_unassigned_account_fallback(db):
    conn, tmp = db
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev.raw", account_map={})
    row = conn.execute("SELECT account FROM staged_postings WHERE role='imported'").fetchone()
    assert row["account"] == "Assets:Unassigned:SimpleFIN-acct1"


def test_multi_transaction_payload(db):
    conn, tmp = db
    multi_payload = {
        "accounts": [
            {
                "id": "acct1",
                "currency": "USD",
                "transactions": [
                    {"id": "tx1", "posted": 1704067200, "amount": "-12.00", "description": "Coffee", "memo": ""},
                    {"id": "tx2", "posted": 1704153600, "amount": "50.00", "description": "Paycheck", "memo": "Direct Dep"},
                ],
            },
            {
                "id": "acct2",
                "currency": "USD",
                "transactions": [
                    {"id": None, "posted": 1704240000, "amount": "-5.50", "description": "Pastry", "memo": ""},
                ],
            },
        ]
    }
    ins, skip = ingest_simplefin_payload(
        conn, multi_payload, evidence_path=tmp / "multi.raw", account_map={"acct1": "Assets:Checking"}
    )
    assert ins == 3 and skip == 0

    # Second poll should skip all 3
    ins2, skip2 = ingest_simplefin_payload(
        conn, multi_payload, evidence_path=tmp / "multi2.raw", account_map={"acct1": "Assets:Checking"}
    )
    assert ins2 == 0 and skip2 == 3
