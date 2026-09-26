from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.web.app import create_app
from tests.test_mcp_tax_tools import mcp_tax_env


@pytest.fixture
def tax_client(mcp_tax_env):
    ledger_dir, projection_dir, db_path = mcp_tax_env
    app = create_app(db_path=db_path, projection_db_path=projection_dir / "projection.sqlite")
    app.state.ledger_dir = ledger_dir
    app.state.projection_dir = projection_dir
    return TestClient(app), Path(db_path)


@pytest.fixture
def empty_tax_client(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    conn = connect(db_path)
    migrations.migrate(conn)
    conn.close()
    return TestClient(create_app(db_path=db_path))


def test_capital_gains_summary_endpoint(tax_client):
    client, _ = tax_client
    response = client.get("/api/tax/capital-gains-summary", params={"tax_year": 2026, "term": "LONG_TERM"})
    assert response.status_code == 200
    assert response.json()["total_realized_gain_minor"] == 150000


def test_open_tax_lots_endpoint(tax_client):
    client, _ = tax_client
    response = client.get("/api/tax/open-lots", params={"commodity": "MSFT"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["lots"][0]["remaining_units_minor"] == 80000


def test_unrealized_gains_endpoint(tax_client):
    client, _ = tax_client
    response = client.get("/api/tax/unrealized-gains")
    assert response.status_code == 200
    assert response.json()["total_unrealized_gain_minor"] == 105000


def test_preview_disposal_endpoint_is_read_only(tax_client):
    client, db_path = tax_client
    conn = sqlite3.connect(db_path)
    before = (
        conn.execute("SELECT COUNT(*), SUM(remaining_units_minor) FROM open_lots").fetchone(),
        conn.execute("SELECT COUNT(*) FROM lot_disposal_allocations").fetchone(),
    )
    conn.close()

    response = client.post(
        "/api/tax/preview-disposal",
        json={"commodity": "MSFT", "quantity": "4", "proceeds_rate": "600", "strategy": "FIFO", "disposal_date": "2026-09-10"},
    )
    assert response.status_code == 200
    assert response.json()["total_realized_gain_minor"] == 80000

    conn = sqlite3.connect(db_path)
    after = (
        conn.execute("SELECT COUNT(*), SUM(remaining_units_minor) FROM open_lots").fetchone(),
        conn.execute("SELECT COUNT(*) FROM lot_disposal_allocations").fetchone(),
    )
    conn.close()
    assert after == before


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("/api/tax/capital-gains-summary", "disposal_count"),
        ("/api/tax/open-lots", "count"),
        ("/api/tax/unrealized-gains", "positions"),
    ],
)
def test_tax_get_endpoints_handle_empty_ledger(empty_tax_client, path, key):
    response = empty_tax_client.get(path)
    assert response.status_code == 200
    assert response.json()[key] in (0, [])


def test_preview_disposal_handles_empty_ledger(empty_tax_client):
    response = empty_tax_client.post(
        "/api/tax/preview-disposal",
        json={"commodity": "MSFT", "quantity": "1", "proceeds_rate": "600"},
    )
    assert response.status_code == 404


def test_tax_endpoints_reject_invalid_filters(tax_client):
    client, _ = tax_client
    assert client.get("/api/tax/capital-gains-summary", params={"tax_year": "26", "term": "WASH"}).status_code == 422
    assert client.get("/api/tax/open-lots", params={"account": ""}).status_code == 422
    assert client.get("/api/tax/unrealized-gains", params={"commodity": ""}).status_code == 422
    assert client.post("/api/tax/preview-disposal", json={"commodity": "MSFT", "quantity": "4", "proceeds_rate": "600", "strategy": "AVERAGE"}).status_code == 422
    assert client.post("/api/tax/preview-disposal", json={"commodity": "MSFT", "quantity": "0.00001", "proceeds_rate": "600"}).status_code == 422


def test_web_tax_router_has_no_float_division_or_beancount_import():
    tree = ast.parse(Path("src/ironledger/web/routers/tax.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Div) for node in ast.walk(tree))
    assert not any(
        (isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "beancount" for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "beancount")
        for node in ast.walk(tree)
    )
