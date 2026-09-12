"""Test suite for /healthz and /readyz probes."""

import sqlite3
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


def test_readiness_probe_healthy(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert data["service"] == "ironledger"
