"""Exit contract test suite for Phase 13: Portfolio Lot Matching, Cost Basis & Capital Gains."""

from __future__ import annotations

import ast
from pathlib import Path
import pytest
import sqlite3

from ironledger.db.migrations import migrate_governed
from ironledger.valuation.engine import ValuationEngine
from ironledger.valuation.lots import LotProcessor
from ironledger.valuation.models import PriceDirective


def test_phase13_ast_zero_float_division():
    """Verify zero floating-point division (/) in valuation, lots, and analytics modules."""
    targets = [
        Path("src/ironledger/valuation/lots.py"),
        Path("src/ironledger/valuation/models.py"),
        Path("src/ironledger/valuation/engine.py"),
        Path("src/ironledger/web/routers/analytics.py"),
    ]

    for p in targets:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                pytest.fail(f"Float division (/) detected in {p} at line {node.lineno}")


def test_phase13_zero_beancount_imports():
    """Verify zero runtime import beancount across Phase 13 modules."""
    targets = [
        Path("src/ironledger/valuation/lots.py"),
        Path("src/ironledger/valuation/models.py"),
        Path("src/ironledger/valuation/engine.py"),
        Path("src/ironledger/web/routers/analytics.py"),
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


def seed_postings(conn: sqlite3.Connection, postings: list[tuple[str, str, str]], ledger_id: str = "default"):
    import hashlib
    conn.execute(
        """
        INSERT OR IGNORE INTO source_documents (
            source_document_id, mime_type, encoding, provenance, acquisition_time_utc,
            content_sha256, raw_payload_ref, created_at_utc, ledger_id
        ) VALUES ('doc-1', 'text/csv', 'utf-8', 'test', '2026-09-01T00:00:00Z', ?, 'raw', '2026-09-01T00:00:00Z', ?)
        """,
        ("a" * 64, ledger_id)
    )
    for idx, (p_id, entry_id, acct) in enumerate(postings):
        rec_id = f"rec-{p_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO source_records (
                source_record_id, source_document_id, record_index, canonical_payload,
                content_sha256, created_at_utc, ledger_id
            ) VALUES (?, 'doc-1', ?, '{}', ?, '2026-09-01T00:00:00Z', ?)
            """,
            (rec_id, idx, hashlib.sha256(rec_id.encode()).hexdigest(), ledger_id)
        )
        stx_id = f"stx-{entry_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO staged_transactions (
                staged_transaction_id, source_record_id, status, proposed_date,
                payee, narration, identity_algo_version, identity_method,
                identity_fingerprint, created_at_utc, ledger_id
            ) VALUES (?, ?, 'approved', '2026-09-01', 'payee', 'narr', 1, 'sha256_fallback', ?, '2026-09-01T00:00:00Z', ?)
            """,
            (stx_id, rec_id, hashlib.sha256(stx_id.encode()).hexdigest(), ledger_id)
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO ledger_entries (
                ledger_entry_id, staged_transaction_id, compile_run_id, entry_date,
                flag, payee, narration, created_at_utc
            ) VALUES (?, ?, NULL, '2026-09-01', '*', 'payee', 'narr', '2026-09-01T00:00:00Z')
            """,
            (entry_id, stx_id)
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO ledger_postings (
                ledger_posting_id, ledger_entry_id, source_record_id, account,
                minor_units, currency, minor_unit_scale, identity_algo_version,
                identity_method, identity_fingerprint, created_at_utc
            ) VALUES (?, ?, ?, ?, 1000, 'USD', 2, 1, 'sha256_fallback', ?, '2026-09-01T00:00:00Z')
            """,
            (p_id, entry_id, rec_id, acct, hashlib.sha256(p_id.encode()).hexdigest())
        )
    conn.commit()


def test_phase13_e2e_lot_lifecycle_and_conservation(tmp_path: Path):
    """Verify end-to-end multi-lot acquisition, partial disposal, basis conservation, and cache refresh."""
    db_file = tmp_path / "e2e_lots.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_governed(conn)

    seed_postings(
        conn,
        [
            ("101", "1", "Assets:Brokerage:MSFT"),
            ("102", "2", "Assets:Brokerage:MSFT"),
            ("103", "3", "Assets:Brokerage:MSFT"),
        ]
    )

    engine = ValuationEngine(conn)
    processor = LotProcessor(conn, engine, functional_currency="USD")

    # 1. Acquire 2 lots of MSFT
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:MSFT",
        commodity="MSFT",
        date="2025-01-15",
        units_minor=100000,  # 10 shares
        unit_scale=4,
        cost_num=300,
        cost_denom=1,
        cost_currency="USD",
        posting_id=101,
        tx_id=1,
    )
    processor.process_acquisition(
        ledger_id="default",
        account="Assets:Brokerage:MSFT",
        commodity="MSFT",
        date="2025-07-20",
        units_minor=100000,  # 10 shares
        unit_scale=4,
        cost_num=400,
        cost_denom=1,
        cost_currency="USD",
        posting_id=102,
        tx_id=2,
    )

    # 2. Sell 12 shares of MSFT @ 450 USD on 2026-03-01
    allocations = processor.process_disposal(
        ledger_id="default",
        account="Assets:Brokerage:MSFT",
        commodity="MSFT",
        date="2026-03-01",
        units_disposed_minor=120000,  # 12 shares
        unit_scale=4,
        disposal_price_num=450,
        disposal_price_denom=1,
        disposal_currency="USD",
        strategy="FIFO",
        closing_posting_id=103,
        closing_tx_id=3,
    )

    assert len(allocations) == 2
    # Slice 1: 10 shares @ 300 -> $3000 basis, $4500 proceeds, $1500 gain (LONG_TERM)
    assert allocations[0].units_disposed_minor == 100000
    assert allocations[0].term_classification == "LONG_TERM"
    assert allocations[0].functional_cost_basis_minor == 300000
    assert allocations[0].functional_proceeds_minor == 450000
    assert allocations[0].functional_realized_gain_minor == 150000

    # Slice 2: 2 shares @ 400 -> $800 basis, $900 proceeds, $100 gain (SHORT_TERM)
    assert allocations[1].units_disposed_minor == 20000
    assert allocations[1].term_classification == "SHORT_TERM"
    assert allocations[1].functional_cost_basis_minor == 80000
    assert allocations[1].functional_proceeds_minor == 90000
    assert allocations[1].functional_realized_gain_minor == 10000

    # 3. Add price directive for remaining 8 shares
    engine.add_price_directive(
        PriceDirective(
            directive_date="2026-03-01",
            base_currency="MSFT",
            quote_currency="USD",
            rate_numerator=450,
            rate_denominator=1,
        )
    )

    # 4. Refresh portfolio cache
    engine.refresh_portfolio_cache(ledger_id="default")

    cur = conn.cursor()
    cur.execute(
        "SELECT commodity, total_units_minor, total_cost_basis_minor, market_value_minor, unrealized_gain_minor "
        "FROM portfolio_holdings_cache WHERE commodity = 'MSFT'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "MSFT"
    assert row[1] == 80000   # 8 remaining shares
    assert row[2] == 320000  # $3200.00 remaining basis (8 * $400)
    assert row[3] == 360000  # $3600.00 market value (8 * $450)
    assert row[4] == 40000   # $400.00 unrealized gain