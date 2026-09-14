"""Exit contract test suite for Phase 14: IronLedger MCP Tool Surface Expansion (Tax & Gains)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import pytest
import sqlite3

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.mcp.tools import call_tool, list_tools, TAX_TOOL_NAMES
from ironledger.valuation.engine import ValuationEngine
from ironledger.valuation.lots import LotProcessor
from ironledger.valuation.models import PriceDirective
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


def test_phase14_ast_zero_float_division():
    """Verify zero floating-point division (/) in valuation, lots, and MCP tools modules."""
    targets = [
        Path("src/ironledger/valuation/lots.py"),
        Path("src/ironledger/valuation/models.py"),
        Path("src/ironledger/valuation/engine.py"),
        Path("src/ironledger/mcp/tools.py"),
    ]

    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                pytest.fail(f"Float division (/) detected in {p} at line {node.lineno}")


def test_phase14_zero_beancount_imports():
    """Verify zero runtime import beancount across Phase 14 modules."""
    targets = [
        Path("src/ironledger/valuation/lots.py"),
        Path("src/ironledger/valuation/models.py"),
        Path("src/ironledger/valuation/engine.py"),
        Path("src/ironledger/mcp/tools.py"),
        Path("src/ironledger/mcp/protocol.py"),
        Path("src/ironledger/mcp/stdio.py"),
        Path("src/ironledger/mcp/http.py"),
    ]

    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "beancount" not in alias.name, f"Import beancount in {p}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "beancount" not in node.module, f"ImportFrom beancount in {p}"


def test_phase14_e2e_mcp_tax_lifecycle(tmp_path: Path):
    """Verify end-to-end lot acquisition, partial disposal, MCP summary, and preview simulation."""
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir, "run-1")
    conn = connect(str(db_path))
    migrations.migrate(conn)

    # 1. Seed postings and lots with unique hashes
    conn.execute(
        """
        INSERT OR IGNORE INTO source_documents (
            source_document_id, mime_type, encoding, provenance, acquisition_time_utc,
            content_sha256, raw_payload_ref, created_at_utc, ledger_id
        ) VALUES ('doc-e2e', 'text/csv', 'utf-8', 'test', '2026-09-01T00:00:00Z', ?, 'raw', '2026-09-01T00:00:00Z', 'default')
        """,
        (hashlib.sha256(b"doc-e2e").hexdigest(),)
    )
    for idx, p_id in enumerate(("101", "102", "103")):
        rec_id = f"rec-{p_id}"
        stx_id = f"stx-{p_id}"
        entry_id = f"e-{p_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO source_records (
                source_record_id, source_document_id, record_index, canonical_payload,
                content_sha256, created_at_utc, ledger_id
            ) VALUES (?, 'doc-e2e', ?, '{}', ?, '2026-09-01T00:00:00Z', 'default')
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
            ) VALUES (?, ?, ?, 'Assets:Brokerage:NVDA', 1000, 'USD', 2, 1, 'sha256_fallback', ?, '2026-09-01T00:00:00Z')
            """,
            (p_id, entry_id, rec_id, hashlib.sha256(p_id.encode()).hexdigest())
        )
    conn.commit()

    engine = ValuationEngine(conn)
    processor = LotProcessor(conn, engine, functional_currency="USD")

    # Acquire 20 NVDA @ 100 USD (20 * 10^4 = 200000 units minor)
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:NVDA",
        commodity="NVDA",
        date="2025-02-01",
        units_minor=200000,
        unit_scale=4,
        cost_num=100,
        cost_denom=1,
        cost_currency="USD",
        posting_id="101",
        tx_id="e-101",
    )

    # Acquire 10 NVDA @ 150 USD (10 * 10^4 = 100000 units minor)
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:NVDA",
        commodity="NVDA",
        date="2025-06-01",
        units_minor=100000,
        unit_scale=4,
        cost_num=150,
        cost_denom=1,
        cost_currency="USD",
        posting_id="102",
        tx_id="e-102",
    )

    # Sell 15 NVDA @ 200 USD on 2026-04-01 (15 from Lot 1: cost $1500, proceeds $3000, gain $1500 LONG_TERM)
    processor.process_disposal(
        ledger_id="default",
        account="Assets:Brokerage:NVDA",
        commodity="NVDA",
        date="2026-04-01",
        units_disposed_minor=150000,
        unit_scale=4,
        disposal_price_num=200,
        disposal_price_denom=1,
        disposal_currency="USD",
        strategy="FIFO",
        closing_posting_id="103",
        closing_tx_id="e-103",
    )

    # Add current price directive: NVDA = $250
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-04-01",
            base_currency="NVDA",
            quote_currency="USD",
            rate_numerator=250,
            rate_denominator=1,
        )
    )

    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()

    # 2. Query get_capital_gains_summary via MCP
    res_gains = call_tool(
        "get_capital_gains_summary",
        {"ledger_id": "default"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=str(db_path),
    )
    assert res_gains["isError"] is False
    gains_data = json.loads(res_gains["content"][0]["text"])
    assert gains_data["total_realized_gain_minor"] == 150000
    assert gains_data["total_realized_gain_display"] == "1500.00"
    assert gains_data["long_term"]["realized_gain_minor"] == 150000

    # 3. Query list_open_tax_lots via MCP
    res_lots = call_tool(
        "list_open_tax_lots",
        {"ledger_id": "default", "commodity": "NVDA"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=str(db_path),
    )
    assert res_lots["isError"] is False
    lots_data = json.loads(res_lots["content"][0]["text"])
    assert lots_data["count"] == 2  # Lot 1 (5 remaining @ 100), Lot 2 (10 remaining @ 150)

    # 4. Preview disposal of 10 NVDA @ 300 USD with HIFO strategy
    # HIFO will take Lot 2 first (10 @ $150 basis = $1500 basis, $3000 proceeds -> $1500 gain)
    res_preview = call_tool(
        "preview_lot_disposal",
        {
            "ledger_id": "default",
            "commodity": "NVDA",
            "quantity": "10",
            "proceeds_rate": "300",
            "strategy": "HIFO",
            "disposal_date": "2026-09-12",
        },
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=str(db_path),
    )
    assert res_preview["isError"] is False
    prev_data = json.loads(res_preview["content"][0]["text"])
    assert prev_data["total_proceeds_minor"] == 300000
    assert prev_data["total_cost_basis_minor"] == 150000
    assert prev_data["total_realized_gain_minor"] == 150000
    assert prev_data["allocations"][0]["functional_cost_basis_minor"] == 150000
