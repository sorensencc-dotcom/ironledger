"""Tests for Phase 14 MCP Tax & Capital Gains Tool Surface Expansion."""

from __future__ import annotations

import hashlib
import io
import json
import socket
import threading
import urllib.request
import urllib.error
from pathlib import Path
import pytest
import sqlite3

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.mcp.http import serve_http
from ironledger.mcp.protocol import handle_message
from ironledger.mcp.stdio import run_stdio
from ironledger.mcp.token import load_or_create_token
from ironledger.mcp.tools import (
    CORE_TOOL_NAMES,
    ANALYTICS_TOOL_NAMES,
    TAX_TOOL_NAMES,
    ALL_TOOL_NAMES,
    list_tools,
    call_tool,
)
from ironledger.valuation.engine import ValuationEngine
from ironledger.valuation.lots import LotProcessor
from ironledger.valuation.models import PriceDirective
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def mcp_tax_env(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")
    conn = connect(str(db_path))
    migrations.migrate(conn)

    # Seed source records and entries for postings
    conn.execute(
        """
        INSERT OR IGNORE INTO source_documents (
            source_document_id, mime_type, encoding, provenance, acquisition_time_utc,
            content_sha256, raw_payload_ref, created_at_utc, ledger_id
        ) VALUES ('doc-tax', 'text/csv', 'utf-8', 'test', '2026-09-01T00:00:00Z', ?, 'raw', '2026-09-01T00:00:00Z', 'default')
        """,
        (hashlib.sha256(b"doc-tax").hexdigest(),)
    )
    for idx, p_id in enumerate(("p-101", "p-102", "p-103", "p-104")):
        rec_id = f"rec-{p_id}"
        stx_id = f"stx-{p_id}"
        entry_id = f"e-{p_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO source_records (
                source_record_id, source_document_id, record_index, canonical_payload,
                content_sha256, created_at_utc, ledger_id
            ) VALUES (?, 'doc-tax', ?, '{}', ?, '2026-09-01T00:00:00Z', 'default')
            """,
            (rec_id, idx, hashlib.sha256(rec_id.encode()).hexdigest())
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO staged_transactions (
                staged_transaction_id, source_record_id, status, proposed_date,
                payee, narration, identity_algo_version, identity_method,
                identity_fingerprint, created_at_utc, ledger_id
            ) VALUES (?, ?, 'approved', '2026-09-01', 'Broker', 'Trade', 1, 'sha256_fallback', ?, '2026-09-01T00:00:00Z', 'default')
            """,
            (stx_id, rec_id, hashlib.sha256(stx_id.encode()).hexdigest())
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO ledger_entries (
                ledger_entry_id, staged_transaction_id, compile_run_id, entry_date,
                flag, payee, narration, created_at_utc
            ) VALUES (?, ?, NULL, '2026-09-01', '*', 'Broker', 'Trade', '2026-09-01T00:00:00Z')
            """,
            (entry_id, stx_id)
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO ledger_postings (
                ledger_posting_id, ledger_entry_id, source_record_id, account,
                minor_units, currency, minor_unit_scale, identity_algo_version,
                identity_method, identity_fingerprint, created_at_utc
            ) VALUES (?, ?, ?, 'Assets:Brokerage:MSFT', 1000, 'USD', 2, 1, 'sha256_fallback', ?, '2026-09-01T00:00:00Z')
            """,
            (p_id, entry_id, rec_id, hashlib.sha256(p_id.encode()).hexdigest())
        )
    conn.commit()

    engine = ValuationEngine(conn)
    processor = LotProcessor(conn, engine, functional_currency="USD")

    # Acquire Lot 1: 10 MSFT @ 300 USD on 2025-01-15 (10 * 10^4 = 100000 units minor)
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:MSFT",
        commodity="MSFT",
        date="2025-01-15",
        units_minor=100000,
        unit_scale=4,
        cost_num=300,
        cost_denom=1,
        cost_currency="USD",
        posting_id="p-101",
        tx_id="e-p-101",
    )

    # Acquire Lot 2: 10 MSFT @ 400 USD on 2025-07-20
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:MSFT",
        commodity="MSFT",
        date="2025-07-20",
        units_minor=100000,
        unit_scale=4,
        cost_num=400,
        cost_denom=1,
        cost_currency="USD",
        posting_id="p-102",
        tx_id="e-p-102",
    )

    # Acquire Lot 3: 5 AAPL @ 150 USD on 2026-01-10 (5 * 10^4 = 50000 units minor)
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:AAPL",
        commodity="AAPL",
        date="2026-01-10",
        units_minor=50000,
        unit_scale=4,
        cost_num=150,
        cost_denom=1,
        cost_currency="USD",
        posting_id="p-103",
        tx_id="e-p-103",
    )

    # Dispose 12 MSFT @ 450 USD on 2026-03-01 (10 from Lot 1 @ 300, 2 from Lot 2 @ 400)
    processor.process_disposal(
        ledger_id="default",
        account="Assets:Brokerage:MSFT",
        commodity="MSFT",
        date="2026-03-01",
        units_disposed_minor=120000,
        unit_scale=4,
        disposal_price_num=450,
        disposal_price_denom=1,
        disposal_currency="USD",
        strategy="FIFO",
        closing_posting_id="p-104",
        closing_tx_id="e-p-104",
    )

    # Seed price history directives for mark-to-market valuation
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-03-01",
            base_currency="MSFT",
            quote_currency="USD",
            rate_numerator=500,
            rate_denominator=1,
        )
    )
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-03-01",
            base_currency="AAPL",
            quote_currency="USD",
            rate_numerator=200,
            rate_denominator=1,
        )
    )

    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()

    return ledger_dir, projection_dir, str(db_path)


def test_tool_registration_and_schemas():
    """Verify tool names and schema structures for all tax tools."""
    assert "get_capital_gains_summary" in TAX_TOOL_NAMES
    assert "list_open_tax_lots" in TAX_TOOL_NAMES
    assert "get_unrealized_gains" in TAX_TOOL_NAMES
    assert "preview_lot_disposal" in TAX_TOOL_NAMES

    assert all(t in ALL_TOOL_NAMES for t in TAX_TOOL_NAMES)

    # Default core tools list
    core_tools = list_tools()
    assert [t["name"] for t in core_tools] == ["search", "balances", "projection_status"]

    # Tax tools included
    tax_tools = list_tools(include_tax=True)
    names = [t["name"] for t in tax_tools]
    assert "get_capital_gains_summary" in names
    assert "list_open_tax_lots" in names
    assert "get_unrealized_gains" in names
    assert "preview_lot_disposal" in names

    # Check preview_lot_disposal schema
    preview_tool = next(t for t in tax_tools if t["name"] == "preview_lot_disposal")
    schema = preview_tool["inputSchema"]
    assert "commodity" in schema["required"]
    assert "quantity" in schema["required"]
    assert "proceeds_rate" in schema["required"]
    assert schema["properties"]["strategy"]["enum"] == ["FIFO", "LIFO", "HIFO"]


def test_get_capital_gains_summary(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    # 1. Total summary
    res = call_tool(
        "get_capital_gains_summary",
        {"ledger_id": "default"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])

    # Slice 1: 10 MSFT @ 300 -> $3000 basis, $4500 proceeds, $1500 gain (LONG_TERM)
    # Slice 2: 2 MSFT @ 400 -> $800 basis, $900 proceeds, $100 gain (SHORT_TERM)
    # Total: $3800 basis, $5400 proceeds, $1600 gain
    assert data["total_realized_gain_minor"] == 160000
    assert data["total_realized_gain_display"] == "1600.00"
    assert data["total_proceeds_minor"] == 540000
    assert data["total_cost_basis_minor"] == 380000
    assert data["short_term"]["realized_gain_minor"] == 10000
    assert data["short_term"]["realized_gain_display"] == "100.00"
    assert data["long_term"]["realized_gain_minor"] == 150000
    assert data["long_term"]["realized_gain_display"] == "1500.00"
    assert data["disposal_count"] == 2

    # 2. Filter by tax year 2026
    res_year = call_tool(
        "get_capital_gains_summary",
        {"ledger_id": "default", "tax_year": 2026},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res_year["isError"] is False
    data_year = json.loads(res_year["content"][0]["text"])
    assert data_year["total_realized_gain_minor"] == 160000

    # 3. Filter by year 2025 (no disposals in 2025)
    res_2025 = call_tool(
        "get_capital_gains_summary",
        {"ledger_id": "default", "tax_year": 2025},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res_2025["isError"] is False
    data_2025 = json.loads(res_2025["content"][0]["text"])
    assert data_2025["total_realized_gain_minor"] == 0
    assert data_2025["disposal_count"] == 0

    # 4. Filter by term SHORT_TERM
    res_st = call_tool(
        "get_capital_gains_summary",
        {"ledger_id": "default", "term": "SHORT_TERM"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res_st["isError"] is False
    data_st = json.loads(res_st["content"][0]["text"])
    assert data_st["total_realized_gain_minor"] == 10000
    assert data_st["disposal_count"] == 1

    # 5. Invalid term validation error
    res_invalid_term = call_tool(
        "get_capital_gains_summary",
        {"ledger_id": "default", "term": "INVALID_TERM"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res_invalid_term["isError"] is True


def test_list_open_tax_lots(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    res = call_tool(
        "list_open_tax_lots",
        {"ledger_id": "default"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert "lots" in data
    assert data["count"] == 2  # 8 shares remaining of MSFT Lot 2, 5 shares of AAPL Lot 3

    lots = {lot["commodity"]: lot for lot in data["lots"]}

    # MSFT lot: 8 shares @ $400 basis = $3200 basis; market price = $500 -> $4000 market value -> $800 unrealized gain
    msft_lot = lots["MSFT"]
    assert msft_lot["remaining_units_minor"] == 80000
    assert msft_lot["quantity_display"] == "8.0000"
    assert msft_lot["current_basis_minor"] == 320000
    assert msft_lot["current_basis_display"] == "3200.00"
    assert msft_lot["market_value_minor"] == 400000
    assert msft_lot["market_value_display"] == "4000.00"
    assert msft_lot["unrealized_gain_loss_minor"] == 80000
    assert msft_lot["unrealized_gain_loss_display"] == "800.00"

    # AAPL lot: 5 shares @ $150 basis = $750 basis; market price = $200 -> $1000 market value -> $250 unrealized gain
    aapl_lot = lots["AAPL"]
    assert aapl_lot["remaining_units_minor"] == 50000
    assert aapl_lot["quantity_display"] == "5.0000"
    assert aapl_lot["current_basis_minor"] == 75000
    assert aapl_lot["current_basis_display"] == "750.00"
    assert aapl_lot["market_value_minor"] == 100000
    assert aapl_lot["unrealized_gain_loss_minor"] == 25000


def test_get_unrealized_gains(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    res = call_tool(
        "get_unrealized_gains",
        {"ledger_id": "default"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])

    # Total basis = $3200 (MSFT) + $750 (AAPL) = $3950.00 (395000 minor)
    # Total market value = $4000 (MSFT) + $1000 (AAPL) = $5000.00 (500000 minor)
    # Total unrealized gain = $1050.00 (105000 minor)
    assert data["total_cost_basis_minor"] == 395000
    assert data["total_cost_basis_display"] == "3950.00"
    assert data["total_market_value_minor"] == 500000
    assert data["total_market_value_display"] == "5000.00"
    assert data["total_unrealized_gain_minor"] == 105000
    assert data["total_unrealized_gain_display"] == "1050.00"

    assert len(data["positions"]) == 2


def test_preview_lot_disposal_and_immutability(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    # Capture DB row counts and state before preview
    conn = connect(db)
    count_lots_before = conn.execute("SELECT COUNT(*), SUM(remaining_units_minor), SUM(remaining_functional_cost_basis_minor) FROM open_lots").fetchone()
    count_allocs_before = conn.execute("SELECT COUNT(*) FROM lot_disposal_allocations").fetchone()
    conn.close()

    # Preview disposal of 4 shares of MSFT @ 600 USD on 2026-09-10
    res = call_tool(
        "preview_lot_disposal",
        {
            "ledger_id": "default",
            "commodity": "MSFT",
            "quantity": "4",
            "proceeds_rate": "600",
            "strategy": "FIFO",
            "disposal_date": "2026-09-10",
        },
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])

    assert data["simulation_status"] == "SUCCESS"
    assert data["commodity"] == "MSFT"
    assert data["strategy"] == "FIFO"
    assert data["units_disposed_minor"] == 40000
    assert data["units_disposed_display"] == "4.0000"

    # 4 shares disposed from Lot 2 (acquired 2025-07-20 @ 400 basis, >365 days holding period -> LONG_TERM)
    # Basis: 4 * $400 = $1600.00; Proceeds: 4 * $600 = $2400.00; Gain: $800.00 (LONG_TERM)
    assert data["total_cost_basis_minor"] == 160000
    assert data["total_proceeds_minor"] == 240000
    assert data["total_realized_gain_minor"] == 80000
    assert data["long_term_gain_minor"] == 80000
    assert data["short_term_gain_minor"] == 0

    assert len(data["allocations"]) == 1
    assert data["allocations"][0]["term_classification"] == "LONG_TERM"
    assert data["allocations"][0]["holding_period_days"] > 365

    # 4 shares remaining in Lot 2 (8 - 4 = 4)
    assert len(data["remaining_lots"]) == 1
    assert data["remaining_lots"][0]["remaining_units_minor"] == 40000
    assert data["remaining_lots"][0]["remaining_basis_minor"] == 160000

    # CRITICAL: Verify database immutability — row counts and remaining sums MUST be unchanged
    conn = connect(db)
    count_lots_after = conn.execute("SELECT COUNT(*), SUM(remaining_units_minor), SUM(remaining_functional_cost_basis_minor) FROM open_lots").fetchone()
    count_allocs_after = conn.execute("SELECT COUNT(*) FROM lot_disposal_allocations").fetchone()
    conn.close()

    assert count_lots_before == count_lots_after
    assert count_allocs_before == count_allocs_after


def test_preview_lot_disposal_insufficient_inventory(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    # Request 20 shares of MSFT when only 8 are available
    res = call_tool(
        "preview_lot_disposal",
        {
            "ledger_id": "default",
            "commodity": "MSFT",
            "quantity": "20",
            "proceeds_rate": "600",
            "strategy": "FIFO",
        },
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )
    assert res["isError"] is True
    assert "insufficient inventory" in res["content"][0]["text"].lower()


def test_dual_transport_stdio_and_http(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    # 1. Test stdio transport
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {
            "name": "get_capital_gains_summary",
            "arguments": {"ledger_id": "default"}
        }
    })
    stdin = io.BytesIO(req_json.encode("utf-8") + b"\n")
    stdout = io.BytesIO()
    stderr = io.StringIO()

    rc = run_stdio(stdin, stdout, stderr, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    assert rc == 0
    lines = stdout.getvalue().decode("utf-8").splitlines()
    assert len(lines) == 1
    resp_obj = json.loads(lines[0])
    assert resp_obj["id"] == 42
    assert resp_obj["result"]["isError"] is False
    res_text = json.loads(resp_obj["result"]["content"][0]["text"])
    assert res_text["total_realized_gain_minor"] == 160000

    # 2. Test HTTP transport with Bearer token
    token = load_or_create_token(projection_dir)
    server = serve_http(host="127.0.0.1", port=0, ledger_dir=ledger_dir, projection_dir=projection_dir, db=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{port}/mcp"
        http_req_body = json.dumps({
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "list_open_tax_lots",
                "arguments": {"ledger_id": "default", "commodity": "AAPL"}
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=http_req_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["id"] == 101
            assert data["result"]["isError"] is False
            content = json.loads(data["result"]["content"][0]["text"])
            assert content["count"] == 1
            assert content["lots"][0]["commodity"] == "AAPL"
    finally:
        server.shutdown()
        server.server_close()


def test_tax_tool_audit_logging(mcp_tax_env):
    ledger_dir, projection_dir, db = mcp_tax_env

    # Run tool call
    call_tool(
        "preview_lot_disposal",
        {
            "ledger_id": "default",
            "commodity": "MSFT",
            "quantity": "2",
            "proceeds_rate": "550",
            "strategy": "FIFO",
        },
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db,
    )

    conn = connect(db)
    row = conn.execute("SELECT actor, action, target, result FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    conn.close()

    assert row is not None
    actor, action, target, result = row
    assert actor == "operator"
    assert action == "mcp preview_lot_disposal"
    assert target == "preview_lot_disposal"
    assert result == "ok"
