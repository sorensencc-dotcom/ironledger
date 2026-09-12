"""Tests for connector governance and circuit breaker endpoints."""

import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from ironledger.db.connection import connect
from ironledger.db.migrations import migrate
from ironledger.web.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "test_connectors.db"
    conn = connect(db_path)
    migrate(conn)

    # Insert test ledger and provider
    conn.execute("INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('test-ledger', 'Test', 'USD');")
    conn.execute(
        """
        INSERT OR IGNORE INTO connector_providers (provider_id, name, protocol_type, base_url, rate_limit_rpm, burst_capacity)
        VALUES ('PLAID', 'Plaid Financial', 'PLAID', 'https://api.plaid.com', 120, 20);
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO connector_circuit_breakers (ledger_id, provider_id, state, failure_count)
        VALUES ('test-ledger', 'PLAID', 'CLOSED', 0);
        """
    )
    conn.commit()
    conn.close()

    app = create_app(db_path=db_path)
    return TestClient(app)


def test_list_connector_providers(client: TestClient):
    response = client.get("/api/connectors", headers={"X-IronLedger-Ledger-Id": "test-ledger"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    plaid = next((p for p in data if p["provider_id"] == "PLAID"), None)
    assert plaid is not None
    assert plaid["circuit_breaker_state"] == "CLOSED"
    assert plaid["rate_limit_rpm"] == 120


def test_get_connector_credentials_status(client: TestClient):
    response = client.get("/api/connectors/credentials", headers={"X-IronLedger-Ledger-Id": "test-ledger"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["provider_id"] == "PLAID"
    assert data[0]["has_credentials"] is False


def test_trigger_connector_sync(client: TestClient):
    response = client.post(
        "/api/connectors/PLAID/trigger",
        headers={"X-IronLedger-Ledger-Id": "test-ledger", "Idempotency-Key": "idemp-test-123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider_id"] == "PLAID"
    assert data["status"] == "SUCCESS"

    # Verify sync runs
    runs_res = client.get("/api/connectors/sync-runs", headers={"X-IronLedger-Ledger-Id": "test-ledger"})
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == data["run_id"]

    # Verify timeline
    tl_res = client.get("/api/connectors/timeline", headers={"X-IronLedger-Ledger-Id": "test-ledger"})
    assert tl_res.status_code == 200
    assert len(tl_res.json()) >= 1
