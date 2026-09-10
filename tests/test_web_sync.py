# tests/test_web_sync.py
import sqlite3
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from ironledger.web.app import create_app
from ironledger.governance.migrations import migrate_governed
from ironledger.security.secrets import CredentialsNotFoundError


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    migrate_governed(conn, db)
    conn.close()
    app = create_app(db_path=db)
    app.state.op_token = "test-token"
    return TestClient(app)


def test_status_requires_auth(client):
    assert client.get("/api/sync/status").status_code == 401


def test_status_allows_request_when_no_op_token_configured(tmp_path):
    db = tmp_path / "test_no_auth.db"
    conn = sqlite3.connect(db)
    migrate_governed(conn, db)
    conn.close()
    app = create_app(db_path=db)
    # op_token not set on app.state
    c = TestClient(app)
    with patch("ironledger.security.secrets.get_access_url", side_effect=Exception):
        r = c.get("/api/sync/status")
    assert r.status_code == 200


def test_status_returns_state(client):
    with patch("ironledger.security.secrets.get_access_url", side_effect=Exception):
        r = client.get("/api/sync/status", headers={"X-IronLedger-Op-Token": "test-token"})
    assert r.status_code == 200
    assert r.json()["state"] in ("UNCONFIGURED", "DEGRADED", "HEALTHY")


def test_status_states_and_pending_count(tmp_path):
    db = tmp_path / "test2.db"
    conn = sqlite3.connect(db)
    migrate_governed(conn, db)
    conn.execute(
        "INSERT INTO source_documents VALUES "
        "('sd1','text/csv','utf-8','bank','2026-09-09T00:00:00Z',"
        "'1111111111111111111111111111111111111111111111111111111111111111',"
        "'ref1','2026-09-09T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records VALUES "
        "('sr1','sd1',0,'payload',"
        "'2222222222222222222222222222222222222222222222222222222222222222','2026-09-09T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions "
        "(staged_transaction_id, source_record_id, status, proposed_date, payee, narration, "
        "identity_algo_version, identity_method, identity_fingerprint, created_at_utc, external_id) "
        "VALUES ('stx1','sr1','pending','2026-09-09','Payee','Desc',1,'fitid',"
        "'3333333333333333333333333333333333333333333333333333333333333333',"
        "'2026-09-09T00:00:00Z','ext:1')"
    )
    conn.commit()
    conn.close()

    app = create_app(db_path=db)
    app.state.op_token = "test-token"
    c = TestClient(app)

    # UNCONFIGURED when CredentialsNotFoundError
    with patch("ironledger.security.secrets.get_access_url", side_effect=CredentialsNotFoundError("no creds")):
        r = c.get("/api/sync/status", headers={"X-IronLedger-Op-Token": "test-token"})
    assert r.status_code == 200
    assert r.json()["state"] == "UNCONFIGURED"
    assert r.json()["pending_count"] == 1

    # HEALTHY when credentials found
    with patch("ironledger.security.secrets.get_access_url", return_value="https://user:pass@bridge.simplefin.org/simplefin"):
        r = c.get("/api/sync/status", headers={"X-IronLedger-Op-Token": "test-token"})
    assert r.status_code == 200
    assert r.json()["state"] == "HEALTHY"
    assert r.json()["pending_count"] == 1


def test_poll_requires_auth(client):
    r = client.post("/api/sync/poll", headers={"X-CSRF-Token": "x"})
    assert r.status_code == 401


def test_poll_requires_csrf(client):
    r = client.post("/api/sync/poll", headers={"X-IronLedger-Op-Token": "test-token"})
    assert r.status_code in (400, 422)


def test_poll_409_when_locked(client):
    from ironledger.pipeline.sync_daemon import SyncLockActiveError
    with patch("ironledger.pipeline.sync_daemon.acquire_lock", side_effect=SyncLockActiveError("locked")):
        r = client.post("/api/sync/poll",
                        headers={"X-IronLedger-Op-Token": "test-token", "X-CSRF-Token": "x"})
    assert r.status_code == 409


def test_poll_returns_counts(client):
    with patch("ironledger.ingest.formats.simplefin.fetch_accounts", return_value={"accounts": []}), \
         patch("ironledger.ingest.formats.simplefin_engine.ingest_simplefin_payload", return_value=(3, 1)), \
         patch("ironledger.pipeline.sync_daemon.acquire_lock"), \
         patch("ironledger.pipeline.sync_daemon.release_lock"):
        r = client.post("/api/sync/poll",
                        headers={"X-IronLedger-Op-Token": "test-token", "X-CSRF-Token": "x"})
    assert r.status_code == 200
    assert r.json() == {"inserted": 3, "skipped": 1}


def test_poll_loads_account_map(tmp_path):
    db = tmp_path / "test3.db"
    conn = sqlite3.connect(db)
    migrate_governed(conn, db)
    conn.execute(
        "INSERT INTO simplefin_account_map (remote_account_id, canonical_account, added_at_utc) "
        "VALUES ('remote_1', 'Assets:Bank:Checking', '2026-09-09T10:00:00Z')"
    )
    conn.commit()
    conn.close()

    app = create_app(db_path=db)
    app.state.op_token = "test-token"
    c = TestClient(app)

    captured_map = {}
    def fake_ingest(conn, payload, *, evidence_path, account_map):
        nonlocal captured_map
        captured_map = account_map
        return 1, 0

    with patch("ironledger.ingest.formats.simplefin.fetch_accounts", return_value={"accounts": []}), \
         patch("ironledger.ingest.formats.simplefin_engine.ingest_simplefin_payload", side_effect=fake_ingest), \
         patch("ironledger.pipeline.sync_daemon.acquire_lock"), \
         patch("ironledger.pipeline.sync_daemon.release_lock"):
        r = c.post("/api/sync/poll",
                   headers={"X-IronLedger-Op-Token": "test-token", "X-CSRF-Token": "x"})
    assert r.status_code == 200
    assert r.json() == {"inserted": 1, "skipped": 0}
    assert captured_map == {"remote_1": "Assets:Bank:Checking"}
