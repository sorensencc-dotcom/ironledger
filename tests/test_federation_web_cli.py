"""Tests for FastAPI federation router and CLI commands."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient

import pytest

from ironledger.cli.__main__ import main
from ironledger.governance.migrations import migrate_governed
from ironledger.web.app import create_app


@pytest.fixture
def app_and_db(tmp_path: Path):
    db_file = tmp_path / "web_fed.db"
    conn = sqlite3.connect(db_file)
    migrate_governed(conn, db_file)
    conn.execute(
        "INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default', 'Default Ledger', 'USD')"
    )
    conn.commit()
    conn.close()

    app = create_app(db_path=db_file)
    client = TestClient(app)
    return client, db_file


def test_web_federation_tenants(app_and_db):
    client, _ = app_and_db

    # List default tenants
    res = client.get("/api/federation/tenants")
    assert res.status_code == 200
    tenants = res.json()
    assert any(t["tenant_id"] == "default" for t in tenants)

    # Create new tenant
    create_res = client.post(
        "/api/federation/tenants",
        json={"tenant_id": "tenant_test", "name": "Test Tenant", "default_ledger_id": "default"},
    )
    assert create_res.status_code == 201
    assert create_res.json()["tenant_id"] == "tenant_test"

    # Duplicate create returns 409
    dup_res = client.post(
        "/api/federation/tenants",
        json={"tenant_id": "tenant_test", "name": "Duplicate Tenant"},
    )
    assert dup_res.status_code == 409


def test_web_federation_nodes_and_events(app_and_db):
    client, _ = app_and_db

    # Register node
    reg_res = client.post(
        "/api/federation/nodes",
        json={
            "node_id": "node_us_east_1",
            "cluster_id": "cluster_us",
            "endpoint_url": "https://node1.example.com",
            "role": "PRIMARY",
        },
    )
    assert reg_res.status_code == 200
    assert reg_res.json()["status"] == "REGISTERED"

    # Ingest peer event
    ingest_res = client.post(
        "/api/federation/events/ingest",
        json={
            "cluster_id": "cluster_us",
            "event": {
                "event_id": "ev_peer_001",
                "event_type": "CONNECTOR_STATE_CHANGED",
                "occurred_at": "2026-06-01T12:00:00Z",
                "recorded_at": "2026-06-01T12:00:00Z",
                "tenant_id": "default",
                "ledger_id": "default",
                "source": "connector",
                "severity": "INFO",
                "payload": {"provider_id": "PLAID", "new_state": "ACTIVE"},
            },
        },
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] == "ACCEPTED"


def test_cli_federation_commands(app_and_db, capsys):
    _, db_file = app_and_db

    # CLI nodes list
    ret_nodes = main(["--db", str(db_file), "federation", "nodes", "list"])
    assert ret_nodes == 0
    captured_nodes = capsys.readouterr()
    assert "Registered Cluster Nodes" in captured_nodes.out

    # CLI outbox list
    ret_outbox = main(["--db", str(db_file), "federation", "outbox", "list"])
    assert ret_outbox == 0
    captured_outbox = capsys.readouterr()
    assert "Pending Federated Outbox Events" in captured_outbox.out

    # CLI outbox dispatch
    ret_disp = main(["--db", str(db_file), "federation", "outbox", "dispatch"])
    assert ret_disp == 0
    captured_disp = capsys.readouterr()
    assert "No pending outbox events" in captured_disp.out or "Claimed" in captured_disp.out
