"""Tests for webhook governance, delivery monitoring, and DLQ endpoints."""

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from ironledger.db.connection import connect
from ironledger.db.migrations import migrate
from ironledger.web.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "test_webhooks.db"
    conn = connect(db_path)
    migrate(conn)

    # Insert test ledger
    conn.execute("INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('test-ledger', 'Test', 'USD');")
    conn.commit()
    conn.close()

    app = create_app(db_path=db_path)
    app.state.op_token = "test-token"
    client = TestClient(app)
    client.headers.update({"X-IronLedger-Op-Token": "test-token"})
    return client


def test_webhook_subscription_lifecycle(client: TestClient):
    # 1. Create subscription
    res = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-IronLedger-Ledger-Id": "test-ledger"},
        json={"target_url": "http://localhost:9000/webhook", "event_types": ["TRANSACTION_STAGED"]},
    )
    assert res.status_code == 200
    sub = res.json()
    assert sub["target_url"] == "http://localhost:9000/webhook"
    assert sub["is_active"] is True
    assert len(sub["secret_fingerprint_hex"]) == 64

    # 2. List subscriptions
    list_res = client.get("/api/webhooks/subscriptions", headers={"X-IronLedger-Ledger-Id": "test-ledger"})
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1


def test_webhook_ssrf_blocked(client: TestClient):
    res = client.post(
        "/api/webhooks/subscriptions",
        headers={"X-IronLedger-Ledger-Id": "test-ledger"},
        json={"target_url": "http://169.254.169.254/latest/meta-data", "event_types": ["ALL"]},
    )
    assert res.status_code == 400
    data = res.json()
    assert data["error_code"] == "GOVERNANCE_VALIDATION_ERROR"
    assert "SSRF" in data["message"]
