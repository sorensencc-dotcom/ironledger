import sqlite3

from ironledger.db.migrations import migrate_governed
from ironledger.valuation.engine import ValuationEngine


def test_refresh_cache_uses_exact_half_even_rounding():
    conn = sqlite3.connect(":memory:")
    migrate_governed(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""INSERT INTO open_lots
        (lot_key, ledger_id, account, commodity, acquisition_date, original_units_minor,
         remaining_units_minor, unit_scale, native_cost_numerator, native_cost_denominator,
         native_cost_currency, functional_currency, functional_unit_cost_numerator,
         functional_unit_cost_denominator, functional_cost_basis_minor,
         remaining_functional_cost_basis_minor, created_posting_id, created_entry_id)
        VALUES ('lot-1','default','Assets:A','X','2026-01-01',1,1,0,1,1,'USD','USD',1,1,2,2,'p','e')""")
    conn.execute("""INSERT INTO price_history
        (id, ledger_id, directive_date, base_currency, quote_currency, rate_numerator,
         rate_denominator, precision_scale, source)
        VALUES (1,'default','2026-01-02','X','USD',1,40,4,'MANUAL')""")
    conn.commit()

    ValuationEngine(conn).refresh_portfolio_cache("default")
    row = conn.execute("SELECT market_value_minor FROM portfolio_holdings_cache").fetchone()
    assert row == (2,)
