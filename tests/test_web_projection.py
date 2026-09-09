import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.project.activate import rebuild_projection
from ironledger.web.app import create_app
from project_fixtures import seed_successful_compile_run, write_rendered_ledger


@pytest.fixture
def app_client(tmp_path: Path):
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.close()

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir(parents=True)
    write_rendered_ledger(ledger_dir)
    seed_successful_compile_run(db_path, ledger_dir)

    proj_dir = tmp_path / "projection"
    proj_dir.mkdir(parents=True)

    conn = connect(str(db_path))
    rebuild_projection(conn, ledger_dir, proj_dir, now_utc="2026-09-08T12:05:00Z")
    conn.close()

    app = create_app(
        db_path=db_path,
        projection_db_path=proj_dir / "projection.sqlite",
    )
    # also attach ledger_dir and projection_dir to app state for freshness calculations
    app.state.ledger_dir = ledger_dir
    app.state.projection_dir = proj_dir

    client = TestClient(app)
    return client, db_path, proj_dir, ledger_dir


def test_get_balances(app_client):
    client, _, _, _ = app_client
    res = client.get("/api/balances")
    assert res.status_code == 200
    balances = res.json()
    assert isinstance(balances, list)
    assert len(balances) >= 2
    accounts = [b["account"] for b in balances]
    assert "Assets:Checking" in accounts
    assert "Expenses:Food" in accounts
    item = next(b for b in balances if b["account"] == "Expenses:Food")
    assert item["minor_units"] == 1234
    assert item["currency"] == "USD"
    assert item["formatted_amount"] == "12.34"


def test_search_fts(app_client):
    client, _, _, _ = app_client
    res = client.get("/api/search", params={"q": "Latte"})
    assert res.status_code == 200
    hits = res.json()
    assert isinstance(hits, list)
    assert len(hits) >= 1
    assert hits[0]["payee"] == 'Coffee "Shop"\\Cafe'
    assert hits[0]["narration"] == "Latte"


def test_search_empty_query_rejected(app_client):
    client, _, _, _ = app_client
    res = client.get("/api/search", params={"q": "   "})
    assert res.status_code == 400


def test_projection_freshness(app_client):
    client, _, _, _ = app_client
    res = client.get("/api/projection/freshness")
    assert res.status_code == 200
    fresh = res.json()
    assert fresh["is_fresh"] is True
    assert "status" in fresh
    assert fresh["status"] in ("fresh", "stale", "critical")

