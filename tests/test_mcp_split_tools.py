from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pytest

from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.amazon_order_normalizer import (
    ParsedItemizedOrder,
    ParsedOrderLine,
)
from ironledger.ingest.split_linker import propose_splits_for_order
from ironledger.mcp.tools import list_tools, call_tool


@pytest.fixture
def mcp_env(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    # Seed statement & staged transaction
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
        "  'rec_stx_001', 'doc_stmt_001', 0, '{\"amount\": -4500}', "
        "  'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-09-29T12:00:00Z'"
        ")"
    )
    conn.execute(
        "INSERT INTO staged_transactions ("
        "  staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        "  identity_algo_version, identity_method, identity_fingerprint, created_at_utc, ledger_id"
        ") VALUES ("
        "  'stx_mcp_split', 'rec_stx_001', 'pending', '2026-09-29', 'Amazon.com', 'Order', "
        "  1, 'sha256_fallback', 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', "
        "  '2026-09-29T12:00:00Z', 'default'"
        ")"
    )
    conn.execute(
        "INSERT INTO staged_postings ("
        "  staged_posting_id, staged_transaction_id, source_record_id, role, posting_index, "
        "  account, minor_units, currency, minor_unit_scale, created_at_utc, ledger_id"
        ") VALUES ("
        "  'sp_imp_001', 'stx_mcp_split', 'rec_stx_001', 'imported', 0, "
        "  'Liabilities:CreditCard:Amex', -4500, 'USD', 2, '2026-09-29T12:00:00Z', 'default'"
        "), ("
        "  'sp_contra_001', 'stx_mcp_split', 'rec_stx_001', 'contra', 1, "
        "  'Expenses:Shopping', 4500, 'USD', 2, '2026-09-29T12:00:00Z', 'default'"
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
        order_id="ord_mcp_001",
        merchant="Amazon",
        merchant_order_ref="114-1234567-0000000",
        order_date="2026-09-29",
        currency="USD",
        subtotal_minor_units=4500,
        tax_minor_units=0,
        shipping_minor_units=0,
        discount_minor_units=0,
        total_minor_units=4500,
        lines=(
            ParsedOrderLine(0, "Python Cookbook", "", 1, 2500, 2500, "Expenses:Books", 90),
            ParsedOrderLine(1, "USB Hub", "", 1, 2000, 2000, "Expenses:Electronics", 90),
        ),
    )
    proposal_id = propose_splits_for_order(conn, order, source_document_id="doc_ord_001", ledger_id="default")
    conn.commit()
    conn.close()

    return db_path, proposal_id, tmp_path


def test_list_tools_includes_split_tools():
    tools = list_tools(include_all=True)
    tool_names = [t["name"] for t in tools]
    assert "preview_order_split" in tool_names
    assert "confirm_order_split" in tool_names


def test_mcp_preview_and_confirm_order_split(mcp_env):
    db_path, proposal_id, tmp_path = mcp_env

    # 1. Call preview_order_split
    preview_res = call_tool(
        "preview_order_split",
        {"proposal_id": proposal_id},
        ledger_dir=str(tmp_path),
        projection_dir=str(tmp_path),
        db=str(db_path),
    )
    assert not preview_res.get("isError")
    preview_data = json.loads(preview_res["content"][0]["text"])
    assert preview_data["proposal_id"] == proposal_id
    assert preview_data["total_minor_units"] == 4500
    assert len(preview_data["lines"]) == 2

    # 2. Call confirm_order_split
    confirm_res = call_tool(
        "confirm_order_split",
        {"proposal_id": proposal_id},
        ledger_dir=str(tmp_path),
        projection_dir=str(tmp_path),
        db=str(db_path),
    )
    assert not confirm_res.get("isError")
    confirm_data = json.loads(confirm_res["content"][0]["text"])
    assert confirm_data["status"] == "confirmed"

    # 3. Verify audit log entry
    conn = connect(str(db_path))
    audit_row = conn.execute(
        "SELECT action, target, result FROM audit_events WHERE action = 'mcp confirm_order_split'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row[1] == proposal_id
    assert audit_row[2] == "ok"

    # 4. Verify staged postings in DB
    postings = conn.execute(
        "SELECT role, account, minor_units FROM staged_postings WHERE staged_transaction_id = 'stx_mcp_split' ORDER BY posting_index"
    ).fetchall()
    assert postings[0] == ("imported", "Liabilities:CreditCard:Amex", -4500)
    assert postings[1] == ("contra", "Expenses:Books", 2500)
    assert postings[2] == ("contra", "Expenses:Electronics", 2000)
    assert sum(p[2] for p in postings) == 0
    conn.close()
