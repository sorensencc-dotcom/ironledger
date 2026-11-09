"""Test suite for /healthz and /readyz probes."""

import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from ironledger.db.migrations import migrate_governed
from ironledger.web.app import create_app


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "test_health.db"
    conn = sqlite3.connect(db)
    migrate_governed(conn, db)
    conn.close()
    app = create_app(db_path=db)
    return TestClient(app)


def test_liveness_probe(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ironledger"
    assert data["version"] == Path("VERSION").read_text(encoding="utf-8").strip()


def test_readiness_probe_healthy(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert data["service"] == "ironledger"


def test_readiness_probe_rejects_corrupt_database_page(client):
    conn = client.app.state.get_db()
    conn.execute("CREATE TABLE health_corruption_probe (value TEXT)")
    conn.execute("INSERT INTO health_corruption_probe VALUES ('retained')")
    conn.commit()
    page = conn.execute("SELECT rootpage FROM sqlite_master WHERE name='health_corruption_probe'").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    with open(db_path, "r+b") as damaged:
        damaged.seek((page - 1) * page_size)
        damaged.write(b"\x00")
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
