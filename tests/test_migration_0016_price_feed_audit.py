import sqlite3

from ironledger.db import migrations
from ironledger.db.connection import connect


def test_price_feed_audit_table_is_migrated_and_accepts_success(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    try:
        assert migrations.migrate(conn) >= 16
        conn.execute(
            """
            INSERT INTO price_feed_audit (
                ledger_id, symbol, quote_currency, provider_id, status,
                rate_numerator, rate_denominator, latency_ms, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("default", "AAPL", "USD", "yahoo", "SUCCESS", 451, 2, 142, None),
        )
        conn.commit()
        row = conn.execute(
            "SELECT symbol, quote_currency, rate_numerator, rate_denominator "
            "FROM price_feed_audit"
        ).fetchone()
        assert row == ("AAPL", "USD", 451, 2)
    finally:
        conn.close()


def test_price_feed_audit_rejects_unknown_status(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    try:
        migrations.migrate(conn)
        with __import__("pytest").raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO price_feed_audit "
                "(symbol, quote_currency, provider_id, status, latency_ms) "
                "VALUES ('AAPL', 'USD', 'x', 'UNKNOWN', 0)"
            )
    finally:
        conn.close()
