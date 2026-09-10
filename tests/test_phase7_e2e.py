# tests/test_phase7_e2e.py
"""Mocked SimpleFIN -> evidence archive -> staging -> idempotency E2E test."""

import json
from pathlib import Path
import sqlite3

import pytest

from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.simplefin import archive_evidence
from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload

PAYLOAD = {
    "accounts": [
        {
            "id": "chase-001",
            "currency": "USD",
            "transactions": [
                {
                    "id": "t001",
                    "posted": 1704067200,
                    "amount": "-42.50",
                    "description": "Grocery",
                    "memo": "",
                },
                {
                    "id": "t002",
                    "posted": 1704153600,
                    "amount": "1000.00",
                    "description": "Payroll",
                    "memo": "",
                },
            ],
        }
    ]
}


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrate_governed(conn, db_path)
    return conn, tmp_path / "evidence" / "source_documents"


def test_e2e_archive_then_stage(env):
    conn, ev_dir = env
    raw = json.dumps(PAYLOAD).encode()
    ev_path = archive_evidence(raw, evidence_dir=ev_dir)
    assert ev_path.suffix == ".raw"
    ins, skip = ingest_simplefin_payload(
        conn,
        PAYLOAD,
        evidence_path=ev_path,
        account_map={"chase-001": "Assets:Chase:Checking"},
    )
    assert ins == 2 and skip == 0

    tx_rows = conn.execute("SELECT * FROM staged_transactions").fetchall()
    post_rows = conn.execute("SELECT * FROM staged_postings").fetchall()
    assert len(tx_rows) == 2
    assert len(post_rows) == 4


def test_e2e_idempotent_repoll(env):
    conn, ev_dir = env
    raw = json.dumps(PAYLOAD).encode()
    ev_path = archive_evidence(raw, evidence_dir=ev_dir)
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=ev_path, account_map={})
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD, evidence_path=ev_path, account_map={})
    assert ins == 0 and skip == 2


def test_e2e_amount_normalization(env):
    conn, ev_dir = env
    payload = {
        "accounts": [
            {
                "id": "a",
                "currency": "USD",
                "transactions": [
                    {
                        "id": "t1",
                        "posted": 1704067200,
                        "amount": "-12",
                        "description": "X",
                        "memo": "",
                    },
                    {
                        "id": "t2",
                        "posted": 1704067200,
                        "amount": "-0.34",
                        "description": "Y",
                        "memo": "",
                    },
                ],
            }
        ]
    }
    raw = json.dumps(payload).encode()
    ev = archive_evidence(raw, evidence_dir=ev_dir)
    ingest_simplefin_payload(conn, payload, evidence_path=ev, account_map={})
    amounts = [
        r[0]
        for r in conn.execute(
            "SELECT minor_units FROM staged_postings WHERE role='imported' ORDER BY staged_posting_id"
        ).fetchall()
    ]
    assert -1200 in amounts and -34 in amounts


def test_e2e_no_secrets_in_audit(env, monkeypatch):
    secret = "s3cr3t"
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        f"https://u:{secret}@bridge.simplefin.org/simplefin",
    )
    conn, _ = env
    from ironledger.security.secrets import get_access_url

    get_access_url(conn)
    for row in conn.execute("SELECT * FROM audit_events").fetchall():
        for cell in row:
            assert secret not in str(cell)
