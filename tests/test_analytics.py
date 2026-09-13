import json
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.mcp.tools import call_tool, list_tools
from ironledger.project.activate import rebuild_projection
from ironledger.web.app import create_app
from tests.project_fixtures import make_sample_set, seed_successful_compile_run, write_rendered_ledger


def setup_analytics_db(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    write_rendered_ledger(ledger_dir, make_sample_set())
    db_path = tmp_path / "ironledger.db"
    seed_successful_compile_run(db_path, ledger_dir)
    conn = connect(str(db_path))
    migrations.migrate(conn)

    # Execute views
    sankey_view_sql = Path("sql/views/0014_cash_flow_sankey.sql").read_text(encoding="utf-8")
    portfolio_view_sql = Path("sql/views/0015_investment_portfolio.sql").read_text(encoding="utf-8")
    conn.executescript(sankey_view_sql)
    conn.executescript(portfolio_view_sql)
    conn.commit()

    projection_dir = tmp_path / "projection"
    rebuild_projection(conn, ledger_dir, projection_dir, now_utc="2026-09-08T12:00:00Z")
    conn.close()
    return ledger_dir, projection_dir, str(db_path)


def test_analytics_sankey_and_portfolio_mcp(tmp_path: Path):
    ledger_dir, projection_dir, db_path = setup_analytics_db(tmp_path)

    # 1. Test tools list
    all_tools = list_tools(include_analytics=True)
    tool_names = [t["name"] for t in all_tools]
    assert "get_cash_flow_sankey" in tool_names
    assert "get_portfolio_holdings" in tool_names

    # 2. Call Sankey MCP tool
    sankey_res = call_tool(
        "get_cash_flow_sankey",
        {"period": "2026-09"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db_path,
    )
    assert sankey_res["isError"] is False
    sankey_data = json.loads(sankey_res["content"][0]["text"])
    assert "flows" in sankey_data

    # 3. Call Portfolio MCP tool
    portfolio_res = call_tool(
        "get_portfolio_holdings",
        {},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db_path,
    )
    assert portfolio_res["isError"] is False
    portfolio_data = json.loads(portfolio_res["content"][0]["text"])
    assert "holdings" in portfolio_data


def test_analytics_api_endpoints(tmp_path: Path):
    ledger_dir, projection_dir, db_path = setup_analytics_db(tmp_path)

    app = create_app(db_path=db_path, projection_db_path=projection_dir / "projection.sqlite")
    client = TestClient(app)

    # Test /api/analytics/sankey endpoint
    res = client.get("/api/analytics/sankey?period=2026-09")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    res = client.get("/api/analytics/portfolio")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Test /api/analytics/watchlist endpoint
    res = client.get("/api/analytics/watchlist")
    assert res.status_code == 200
    wdata = res.json()
    assert "items" in wdata
    assert "recent_audit" in wdata

    # Test /api/analytics/watchlist/add endpoint
    res = client.post("/api/analytics/watchlist/add", json={"symbol": "NVDA", "quote_currency": "USD", "manual_quote": "120.00"})
    assert res.status_code == 200
    assert res.json()["symbol"] == "NVDA"

    # Test /api/analytics/prices/sync endpoint
    res = client.post("/api/analytics/prices/sync", json={"symbols": ["NVDA"]})
    assert res.status_code == 200
    sdata = res.json()
    assert "status" in sdata


def test_mcp_trigger_price_sync(tmp_path):
    ledger_dir, projection_dir, db_path = setup_analytics_db(tmp_path)
    res = call_tool(
        "trigger_price_sync",
        {"symbols": ["AAPL", "BTC"], "quote_currency": "USD"},
        ledger_dir=ledger_dir,
        projection_dir=projection_dir,
        db=db_path,
    )
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert data["status"] in ("success", "failed", "partial_failure")



