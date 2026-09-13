import sqlite3

from ironledger.db.migrations import migrate_governed


def test_lot_projection_schema_exists_after_migration():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"open_lots", "lot_disposal_allocations", "portfolio_holdings_cache"} <= tables

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(open_lots)")
    }
    assert {
        "lot_key",
        "remaining_functional_cost_basis_minor",
        "source_lot_key",
    } <= columns
