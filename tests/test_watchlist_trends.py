from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from ironledger.web.app import create_app
from ironledger.governance.migrations import migrate_governed


def test_watchlist_trending_signals(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    try:
        migrate_governed(conn, str(db_path))
        # Insert 2 price history entries for AAPL to simulate price rise (220 -> 225.50)
        conn.execute(
            """
            INSERT INTO price_history (id, ledger_id, directive_date, base_currency, quote_currency, rate_numerator, rate_denominator, precision_scale, source, created_at)
            VALUES (1, 'default', '2026-09-11', 'AAPL', 'USD', 220, 1, 4, 'POLLED_FEED', '2026-09-11 12:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO price_history (id, ledger_id, directive_date, base_currency, quote_currency, rate_numerator, rate_denominator, precision_scale, source, created_at)
            VALUES (2, 'default', '2026-09-12', 'AAPL', 'USD', 451, 2, 4, 'POLLED_FEED', '2026-09-12 12:00:00')
            """
        )
        # Insert 2 price history entries for MSFT to simulate price drop (450 -> 420)
        conn.execute(
            """
            INSERT INTO price_history (id, ledger_id, directive_date, base_currency, quote_currency, rate_numerator, rate_denominator, precision_scale, source, created_at)
            VALUES (3, 'default', '2026-09-11', 'MSFT', 'USD', 450, 1, 4, 'POLLED_FEED', '2026-09-11 12:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO price_history (id, ledger_id, directive_date, base_currency, quote_currency, rate_numerator, rate_denominator, precision_scale, source, created_at)
            VALUES (4, 'default', '2026-09-12', 'MSFT', 'USD', 420, 1, 4, 'POLLED_FEED', '2026-09-12 12:00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    prices_json = config_dir / "prices.json"
    prices_json.write_text(
        json.dumps({
            "quote_currency": "USD",
            "watchlist": [
                {"symbol": "AAPL", "quote_currency": "USD"},
                {"symbol": "MSFT", "quote_currency": "USD"},
                {"symbol": "GOOGL", "quote_currency": "USD"},
            ],
            "manual_quotes": {"GOOGL/USD": "180.25"}
        }),
        encoding="utf-8"
    )

    app = create_app(db_path=str(db_path), config_dir=str(config_dir))
    client = TestClient(app)

    resp = client.get("/api/analytics/watchlist")
    assert resp.status_code == 200
    data = resp.json()
    items = {item["symbol"]: item for item in data["items"]}

    # AAPL rose from 220 to 225.50 (+2.50%)
    assert items["AAPL"]["trend"] == "UP"
    assert items["AAPL"]["change_percent"] == "+2.50%"
    assert items["AAPL"]["price_display"] == "225.5000"
    assert items["AAPL"]["previous_price_display"] == "220.0000"

    # MSFT dropped from 450 to 420 (-6.67%)
    assert items["MSFT"]["trend"] == "DOWN"
    assert items["MSFT"]["change_percent"] == "-6.67%"
    assert items["MSFT"]["price_display"] == "420.0000"
    assert items["MSFT"]["previous_price_display"] == "450.0000"

    # GOOGL has only 1 quote (FLAT)
    assert items["GOOGL"]["trend"] == "FLAT"
