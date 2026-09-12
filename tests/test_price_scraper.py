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


def test_scraper_daemon_config_loading(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(db_path)
    migrations.migrate(conn)
    conn.close()
    prices = tmp_path / "ledger" / "prices.beancount"
    config_file = tmp_path / "prices.json"
    import json
    config_file.write_text(json.dumps({
        "quote_currency": "USD",
        "watchlist": [
            {"symbol": "BTC", "quote_currency": "USD"},
            "ETH",
            ["SOL", "USD"],
        ],
    }), encoding="utf-8")

    router = PriceCascadeRouter({"DEFAULT": [ManualProvider({"BTC/USD": "60000.00", "ETH/USD": "2400.00", "SOL/USD": "130.00"})]})
    daemon = PriceScraperDaemon(db_path, prices, router)
    targets = daemon.load_config_watchlist(config_file)
    assert len(targets) == 3
    assert ("BTC", "USD") in targets
    assert ("ETH", "USD") in targets
    assert ("SOL", "USD") in targets

    result = daemon.sync_watchlist(config_path=config_file)
    assert result["status"] == "success"
    assert result["synced_count"] == 3


def test_cli_prices_poll(tmp_path: Path, monkeypatch):
    import json
    from ironledger.cli.__main__ import main

    db_path = tmp_path / "ironledger.db"
    conn = connect(db_path)
    migrations.migrate(conn)
    conn.close()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "prices.json"
    config_file.write_text(json.dumps({
        "quote_currency": "USD",
        "watchlist": [{"symbol": "AAPL", "quote_currency": "USD"}],
        "manual_quotes": {"AAPL/USD": "225.50"},
    }), encoding="utf-8")

    ret = main([
        "prices", "poll",
        "--db", str(db_path),
        "--ledger-dir", str(tmp_path / "ledger"),
        "--config-dir", str(config_dir),
        "--json",
    ])
    assert ret == 0

