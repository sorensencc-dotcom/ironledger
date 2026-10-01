from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.amazon_order_normalizer import (
    ParsedItemizedOrder,
    ParsedOrderLine,
)
from ironledger.ingest.split_linker import propose_splits_for_order
from ironledger.web.app import create_app


@pytest.fixture
def test_env(tmp_path: Path):
    db_path = tmp_path / "test_web_split.db"
    conn = connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # Seed data
    conn.execute(
        "INSERT INTO source_documents ("
        "  source_document_id, mime_type, encoding, provenance, "
        "  acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc"
        ") VALUES ("
        "  'doc_stmt_001', 'text/csv', 'utf-8', 'amex_statement', "
        "  '2026-09-29T12:00:00Z', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
        "  'evidence/amex.csv', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.execute(
        "INSERT INTO source_records ("
        "  source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc"
        ") VALUES ("
        "  'rec_stx_001', 'doc_stmt_001', 0, '{\"amount\": -5000}', "
        "  'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.execute(
        "INSERT INTO staged_transactions ("
        "  staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        "  identity_algo_version, identity_method, identity_fingerprint, created_at_utc, ledger_id"
        ") VALUES ("
        "  'stx_split_web', 'rec_stx_001', 'pending', '2026-09-29', 'Amazon.com', 'Order', "
        "  1, 'sha256_fallback', 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', "
        "  '2026-09-29T12:00:00Z', 'default'"
        ")"
    )
    conn.execute(
        "INSERT INTO staged_postings ("
        "  staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, "
        "  account, minor_units, currency, minor_unit_scale, created_at_utc, ledger_id"
        ") VALUES ("
        "  'sp_imp_001', 'stx_split_web', 'rec_stx_001', 'imported', 0, "
        "  'Liabilities:CreditCard:Amex', -5000, 'USD', 2, '2026-09-29T12:00:00Z', 'default'"
        "), ("
        "  'sp_contra_001', 'stx_split_web', 'rec_stx_001', 'contra', 1, "
        "  'Expenses:Shopping', 5000, 'USD', 2, '2026-09-29T12:00:00Z', 'default'"
        ")"
    )
    conn.execute(
        "INSERT INTO source_documents ("
        "  source_document_id, mime_type, encoding, provenance, "
        "  acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc"
        ") VALUES ("
        "  'doc_ord_001', 'text/csv', 'utf-8', 'amazon_orders', "
        "  '2026-09-29T12:00:00Z', 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', "
        "  'evidence/amazon.csv', '2026-09-29T12:00:00Z'"
        ")"
    )

    order = ParsedItemizedOrder(
        order_id="ord_web_001",
        merchant="Amazon",
        merchant_order_ref="114-0000000",
        order_date="2026-09-29",
        currency="USD",
        subtotal_minor_units=5000,
        tax_minor_units=0,
        shipping_minor_units=0,
        discount_minor_units=0,
        total_minor_units=5000,
        lines=(
            ParsedOrderLine(0, "Book 1", "", 1, 3000, 3000, "Expenses:Books", 90),
            ParsedOrderLine(1, "Electronics 1", "", 1, 2000, 2000, "Expenses:Electronics", 90),
        ),
    )
    proposal_id = propose_splits_for_order(conn, order, source_document_id="doc_ord_001", ledger_id="default")
    conn.commit()
    conn.close()

    app = create_app(db_path=db_path)
    app.state.op_token = "test-token"
    client = TestClient(app)

    db_check = connect(str(db_path))
    try:
        yield client, db_check, proposal_id
    finally:
        db_check.close()


def test_web_split_proposals_list(test_env):
    client, _conn, proposal_id = test_env
    res = client.get("/api/staging/splits/proposals", headers={"X-IronLedger-Op-Token": "test-token"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["proposal_id"] == proposal_id
    assert data[0]["status"] == "pending"
    assert data[0]["lines"] == [
        {
            "line_index": 0,
            "item_title": "Book 1",
            "item_description": "",
            "quantity": 1,
            "unit_price_minor": 3000,
            "total_price_minor": 3000,
            "proposed_account": "Expenses:Books",
            "confidence_score": 90,
        },
        {
            "line_index": 1,
            "item_title": "Electronics 1",
            "item_description": "",
            "quantity": 1,
            "unit_price_minor": 2000,
            "total_price_minor": 2000,
            "proposed_account": "Expenses:Electronics",
            "confidence_score": 90,
        },
    ]


def test_web_split_proposal_confirm_and_reject(test_env):
    client, conn, proposal_id = test_env
    # Confirm proposal
    res = client.post(
        f"/api/staging/splits/proposals/{proposal_id}/confirm",
        headers={"X-IronLedger-Op-Token": "test-token"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "confirmed"

    # Verify mutation in DB
    postings = conn.execute(
        "SELECT role, account, minor_units FROM staged_postings WHERE staged_transaction_id = 'stx_split_web' ORDER BY posting_index"
    ).fetchall()
    assert postings[0] == ("imported", "Liabilities:CreditCard:Amex", -5000)
    assert postings[1] == ("contra", "Expenses:Books", 3000)
    assert postings[2] == ("contra", "Expenses:Electronics", 2000)
    assert sum(p[2] for p in postings) == 0


def test_split_proposals_use_active_ledger_header(test_env):
    client, conn, proposal_id = test_env
    conn.execute("INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default-test', 'Test', 'USD')")
    conn.execute(
        "UPDATE itemized_orders SET ledger_id = 'default-test' WHERE order_id = 'ord_web_001'"
    )
    conn.commit()

    default_res = client.get("/api/staging/splits/proposals", headers={"X-IronLedger-Op-Token": "test-token"})
    assert default_res.status_code == 200
    assert default_res.json() == []

    ledger_res = client.get(
        "/api/staging/splits/proposals",
        headers={"X-IronLedger-Op-Token": "test-token", "X-IronLedger-Ledger-Id": "default-test"},
    )
    assert ledger_res.status_code == 200
    assert ledger_res.json()[0]["proposal_id"] == proposal_id
