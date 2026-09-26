"""Tests for the anomaly-flag web endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.web.app import create_app

OP_TOKEN = "test-operator-token"


@pytest.fixture
def anomaly_client(tmp_path: Path, monkeypatch):
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
        INSERT INTO source_documents (source_document_id, mime_type, encoding, provenance, acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc)
        VALUES ('doc_1', 'text/csv', 'utf-8', 'manual', '2026-06-01T10:00:00Z', ?, 'evidence/doc_1.raw', '2026-06-01T10:00:00Z')
        """,
        ("0" * 64,),
    )
    conn.execute(
        """
        INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc)
        VALUES ('rec_1', 'doc_1', 0, '{}', ?, '2026-06-01T10:00:00Z')
        """,
        ("1" * 64,),
    )
    conn.execute(
        """
        INSERT INTO source_records (source_record_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc)
        VALUES ('rec_2', 'doc_1', 1, '{}', ?, '2026-06-01T10:00:00Z')
        """,
        ("2" * 64,),
    )
    conn.execute(
        """
        INSERT INTO staged_transactions (
            staged_transaction_id, source_record_id, status, proposed_date, payee, narration,
            identity_algo_version, identity_method, identity_fingerprint, created_at_utc
        ) VALUES ('stg_1', 'rec_1', 'pending', '2026-06-01', 'Luxury Vendor', 'Diamond Watch', 1, 'sha256_fallback', ?, '2026-06-01T12:00:00Z')
        """,
        ("3" * 64,),
    )
    conn.execute(
        """
        INSERT INTO staged_transactions (
            staged_transaction_id, source_record_id, status, proposed_date, payee, narration,
            identity_algo_version, identity_method, identity_fingerprint, created_at_utc
        ) VALUES ('stg_2', 'rec_2', 'pending', '2026-06-01', 'Luxury Vendor', 'Diamond Watch', 1, 'sha256_fallback', ?, '2026-06-01T12:05:00Z')
        """,
        ("4" * 64,),
    )
    conn.execute(
        """
        INSERT INTO staged_postings (
            staged_posting_id, staged_transaction_id, source_record_id, role, posting_index,
            account, minor_units, currency, minor_unit_scale, created_at_utc
        ) VALUES ('post_1', 'stg_1', 'rec_1', 'imported', 0, 'Assets:Checking', 500000, 'USD', 2, '2026-06-01T12:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO staged_postings (
            staged_posting_id, staged_transaction_id, source_record_id, role, posting_index,
            account, minor_units, currency, minor_unit_scale, created_at_utc
        ) VALUES ('post_2', 'stg_2', 'rec_2', 'imported', 0, 'Assets:Checking', 500000, 'USD', 2, '2026-06-01T12:05:00Z')
        """
    )
    conn.commit()
    conn.close()
    app = create_app(db_path=db_path)
    return TestClient(app), db_path


def _headers():
    return {"X-IronLedger-Op-Token": OP_TOKEN}


def test_scan_happy_path_persists_flags(anomaly_client):
    client, db_path = anomaly_client
    response = client.post("/api/anomaly/scan", headers=_headers(), json={"ledger_id": "corp"})
    assert response.status_code == 200
    body = response.json()
    assert body["scanned_count"] == 2
    assert len(body["findings"]) >= 1
    assert any(f["rule_type"] == "DUPLICATE_CHARGE" for f in body["findings"])

    conn = connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM anomaly_flags WHERE ledger_id = 'corp'").fetchone()[0]
    conn.close()
    assert count == len(body["findings"])


def test_scan_missing_operator_token(anomaly_client):
    client, _ = anomaly_client
    response = client.post("/api/anomaly/scan", json={"ledger_id": "corp"})
    assert response.status_code == 401


def test_list_flags_with_and_without_status_filter(anomaly_client):
    client, _ = anomaly_client
    client.post("/api/anomaly/scan", headers=_headers(), json={"ledger_id": "corp"})

    all_flags = client.get("/api/anomaly/flags", params={"ledger_id": "corp"})
    assert all_flags.status_code == 200
    assert all_flags.json()["count"] >= 1

    open_flags = client.get("/api/anomaly/flags", params={"ledger_id": "corp", "status": "OPEN"})
    assert open_flags.status_code == 200
    assert open_flags.json()["count"] == all_flags.json()["count"]

    resolved_flags = client.get("/api/anomaly/flags", params={"ledger_id": "corp", "status": "RESOLVED"})
    assert resolved_flags.status_code == 200
    assert resolved_flags.json()["count"] == 0


def test_resolve_happy_path_appends_governance_event(anomaly_client):
    client, db_path = anomaly_client
    scan_body = client.post("/api/anomaly/scan", headers=_headers(), json={"ledger_id": "corp"}).json()
    flag_id = scan_body["findings"][0]["flag_id"]

    response = client.post(
        f"/api/anomaly/flags/{flag_id}/resolve",
        headers=_headers(),
        params={"ledger_id": "corp"},
        json={"resolution_status": "DISMISSED", "actor": "operator", "reason": "false positive"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    conn = connect(str(db_path))
    status = conn.execute(
        "SELECT resolution_status FROM anomaly_flags WHERE ledger_id = 'corp' AND flag_id = ?", (flag_id,)
    ).fetchone()[0]
    gov_count = conn.execute(
        "SELECT COUNT(*) FROM governance_audit_events WHERE action = 'RESOLVE_ANOMALY_FLAG'"
    ).fetchone()[0]
    conn.close()
    assert status == "DISMISSED"
    assert gov_count == 1


def test_resolve_already_resolved_flag_errors(anomaly_client):
    client, _ = anomaly_client
    scan_body = client.post("/api/anomaly/scan", headers=_headers(), json={"ledger_id": "corp"}).json()
    flag_id = scan_body["findings"][0]["flag_id"]

    client.post(
        f"/api/anomaly/flags/{flag_id}/resolve",
        headers=_headers(),
        params={"ledger_id": "corp"},
        json={"resolution_status": "DISMISSED", "actor": "operator"},
    )
    second = client.post(
        f"/api/anomaly/flags/{flag_id}/resolve",
        headers=_headers(),
        params={"ledger_id": "corp"},
        json={"resolution_status": "DISMISSED", "actor": "operator"},
    )
    assert second.status_code == 422


def test_resolve_missing_flag_404(anomaly_client):
    client, _ = anomaly_client
    response = client.post(
        "/api/anomaly/flags/does-not-exist/resolve",
        headers=_headers(),
        params={"ledger_id": "corp"},
        json={"resolution_status": "DISMISSED", "actor": "operator"},
    )
    assert response.status_code == 404


def test_resolve_missing_operator_token(anomaly_client):
    client, _ = anomaly_client
    scan_body = client.post("/api/anomaly/scan", headers=_headers(), json={"ledger_id": "corp"}).json()
    flag_id = scan_body["findings"][0]["flag_id"]
    response = client.post(
        f"/api/anomaly/flags/{flag_id}/resolve",
        params={"ledger_id": "corp"},
        json={"resolution_status": "DISMISSED", "actor": "operator"},
    )
    assert response.status_code == 401


def test_web_anomaly_router_has_no_float_division():
    import ast

    tree = ast.parse(Path("src/ironledger/web/routers/anomaly.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Div) for node in ast.walk(tree))
