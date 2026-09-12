from pathlib import Path

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.prices.providers.manual import ManualProvider
from ironledger.prices.router import PriceCascadeRouter
from ironledger.prices.scraper_daemon import PriceScraperDaemon


def test_scraper_daemon_sync_watchlist(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(db_path)
    migrations.migrate(conn)
    conn.close()
    prices = tmp_path / "ledger" / "prices.beancount"
    router = PriceCascadeRouter({"DEFAULT": [ManualProvider({"AAPL/USD": "225.50", "MSFT/USD": "420.00"})]})
    result = PriceScraperDaemon(db_path, prices, router).sync_watchlist([("AAPL", "USD"), ("MSFT", "USD")])
    assert result["status"] == "success"
    assert result["synced_count"] == 2
    assert "price AAPL" in prices.read_text(encoding="utf-8")
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM price_feed_audit WHERE status='SUCCESS'").fetchone()[0] == 2
    conn.close()
