"""Regression coverage for operator authentication and rebuild boundaries."""

from pathlib import Path

from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.web.app import create_app


def _client(tmp_path: Path, token: str | None) -> TestClient:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.close()
    app = create_app(
        db_path=db_path,
        projection_db_path=tmp_path / "projection" / "projection.sqlite",
        config_dir=tmp_path / "config",
    )
    app.state.op_token = token
    return TestClient(app)


def test_mutation_endpoints_fail_closed_without_or_with_wrong_token(tmp_path: Path):
    endpoints = [
        ("post", "/api/rules", {"pattern": "coffee", "target_account": "Expenses:Coffee"}),
        ("post", "/api/rules/rule-missing/disable", None),
        ("post", "/api/staging/stx-missing/categorize", {"target_account": "Expenses:Coffee"}),
        ("post", "/api/staging/stx-missing/approve", None),
        ("post", "/api/staging/stx-missing/reject", None),
        ("post", "/api/staging/stx-missing/reopen", None),
        ("post", "/api/staging/stx-missing/split", {"postings": []}),
        ("post", "/api/v1/failover/heartbeat", {"node_id": "node-1"}),
        ("post", "/api/v1/failover/promote", {"cluster_id": "default", "candidate_node_id": "node-1"}),
        ("post", "/api/v1/security/rotate-key", {"tenant_id": "tenant-1", "new_kek_key_id": "kek-2"}),
        ("post", "/api/project/rebuild", {}),
    ]

    for token, expected in ((None, 401), ("wrong", 401)):
        client = _client(tmp_path / ("none" if token is None else "wrong"), "expected")
        headers = {} if token is None else {"X-IronLedger-Op-Token": token}
        for method, path, payload in endpoints:
            response = getattr(client, method)(path, json=payload, headers=headers)
            assert response.status_code == expected, (path, response.status_code, response.text)


def test_correct_token_allows_rule_mutation(tmp_path: Path):
    client = _client(tmp_path, "expected")
    response = client.post(
        "/api/rules",
        json={"pattern": "coffee", "target_account": "Expenses:Coffee"},
        headers={"X-IronLedger-Op-Token": "expected"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_project_rebuild_rejects_paths_outside_configured_directories(tmp_path: Path):
    client = _client(tmp_path, "expected")
    response = client.post(
        "/api/project/rebuild",
        json={"ledger_dir": str(tmp_path.parent / "outside-ledger")},
        headers={"X-IronLedger-Op-Token": "expected"},
    )
    assert response.status_code == 400
    assert "inside the configured ledger directory" in response.text
