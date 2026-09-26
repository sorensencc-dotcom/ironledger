"""Tests for the compliance-bundle web endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.web.app import create_app


def test_docker_runtime_installs_multipart_parser():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert '"python-multipart>=0.0.9"' in dockerfile

OP_TOKEN = "test-operator-token"


@pytest.fixture
def compliance_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IRONLEDGER_OP_TOKEN", OP_TOKEN)
    db_path = tmp_path / "ironledger.db"
    conn = connect(str(db_path))
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO ledgers (ledger_id, name, base_currency) VALUES (?, ?, ?)",
        ("corp", "Corporate", "USD"),
    )
    conn.execute(
        """
        INSERT INTO governance_audit_events (ledger_id, actor, action, target, before_state_json, after_state_json, envelope_hash, timestamp_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("corp", "operator", "TEST_ACTION", "target:1", "{}", "{}", "0" * 64, "2026-06-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()
    app = create_app(db_path=db_path)
    return TestClient(app), db_path


def _headers():
    return {"X-IronLedger-Op-Token": OP_TOKEN}


def test_generate_bundle_happy_path(compliance_client):
    client, _ = compliance_client
    response = client.post(
        "/api/compliance/bundles",
        headers=_headers(),
        json={
            "ledger_id": "corp",
            "framework": "SOC2_TYPE2",
            "period_start_utc": "2026-01-01T00:00:00Z",
            "period_end_utc": "2026-12-31T23:59:59Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ledger_id"] == "corp"
    assert body["framework"] == "SOC2_TYPE2"
    assert body["record_count"] == 1
    assert len(body["merkle_root_hex"]) == 64
    assert len(body["sealed_archive_sha256"]) == 64


def test_generate_bundle_invalid_framework(compliance_client):
    client, _ = compliance_client
    response = client.post(
        "/api/compliance/bundles",
        headers=_headers(),
        json={
            "ledger_id": "corp",
            "framework": "NOT_A_FRAMEWORK",
            "period_start_utc": "2026-01-01T00:00:00Z",
            "period_end_utc": "2026-12-31T23:59:59Z",
        },
    )
    assert response.status_code == 422


def test_generate_bundle_invalid_period(compliance_client):
    client, _ = compliance_client
    response = client.post(
        "/api/compliance/bundles",
        headers=_headers(),
        json={
            "ledger_id": "corp",
            "framework": "SOC2_TYPE2",
            "period_start_utc": "2026-12-31T23:59:59Z",
            "period_end_utc": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


def test_generate_bundle_missing_operator_token(compliance_client):
    client, _ = compliance_client
    response = client.post(
        "/api/compliance/bundles",
        json={
            "ledger_id": "corp",
            "framework": "SOC2_TYPE2",
            "period_start_utc": "2026-01-01T00:00:00Z",
            "period_end_utc": "2026-12-31T23:59:59Z",
        },
    )
    assert response.status_code == 401


def test_verify_bundle_happy_path(compliance_client):
    client, _ = compliance_client
    generated = client.post(
        "/api/compliance/bundles",
        headers=_headers(),
        json={
            "ledger_id": "corp",
            "framework": "SOX",
            "period_start_utc": "2026-01-01T00:00:00Z",
            "period_end_utc": "2026-12-31T23:59:59Z",
        },
    ).json()

    archives = list(Path(generated_archive_dir(client)).glob(f"compliance_bundle_corp_{generated['bundle_id']}.tar"))
    assert len(archives) == 1
    archive_bytes = archives[0].read_bytes()

    verify_response = client.post(
        "/api/compliance/bundles/verify",
        files={"archive": ("bundle.tar", archive_bytes, "application/x-tar")},
    )
    assert verify_response.status_code == 200
    body = verify_response.json()
    assert body["is_valid"] is True
    assert body["merkle_root_hex"] == generated["merkle_root_hex"]


def test_verify_bundle_tampered_archive_rejected(compliance_client):
    client, _ = compliance_client
    generated = client.post(
        "/api/compliance/bundles",
        headers=_headers(),
        json={
            "ledger_id": "corp",
            "framework": "ISO27001",
            "period_start_utc": "2026-01-01T00:00:00Z",
            "period_end_utc": "2026-12-31T23:59:59Z",
        },
    ).json()
    archives = list(Path(generated_archive_dir(client)).glob(f"compliance_bundle_corp_{generated['bundle_id']}.tar"))
    tampered = bytearray(archives[0].read_bytes())
    tampered[-1] ^= 0xFF

    verify_response = client.post(
        "/api/compliance/bundles/verify",
        params={"expected_sha256": generated["sealed_archive_sha256"]},
        files={"archive": ("bundle.tar", bytes(tampered), "application/x-tar")},
    )
    assert verify_response.status_code == 422


def test_verify_bundle_oversized_archive_rejected(compliance_client, monkeypatch):
    import ironledger.web.routers.compliance as compliance_router

    monkeypatch.setattr(compliance_router, "MAX_ARCHIVE_BYTES", 10)
    client, _ = compliance_client
    response = client.post(
        "/api/compliance/bundles/verify",
        files={"archive": ("bundle.tar", b"0" * 100, "application/x-tar")},
    )
    assert response.status_code == 413


def generated_archive_dir(client: TestClient) -> Path:
    return client.app.state.compliance_bundle_dir


def test_web_compliance_router_has_no_float_division():
    import ast

    tree = ast.parse(Path("src/ironledger/web/routers/compliance.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Div) for node in ast.walk(tree))
