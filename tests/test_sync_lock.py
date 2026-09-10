# tests/test_sync_lock.py
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from ironledger.pipeline.sync_daemon import (
    SyncLockActiveError,
    SyncLockPermissionError,
    acquire_lock,
    release_lock,
    inspect_and_reclaim_if_stale,
)


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / ".sync.lock"


def test_acquire_creates_lock(lock_path):
    acquire_lock(lock_path)
    assert lock_path.exists()
    data = json.loads(lock_path.read_text())
    assert data["pid"] == os.getpid()
    release_lock(lock_path)


def test_live_pid_fails_closed(lock_path):
    import socket
    hn = socket.gethostname()
    lock_path.write_text(json.dumps({
        "pid": os.getpid(), "started_at": "2024-01-01T00:00:00Z", "hostname": hn
    }))
    with pytest.raises(SyncLockActiveError):
        inspect_and_reclaim_if_stale(lock_path)


def test_dead_pid_reclaimed(lock_path):
    lock_path.write_text(json.dumps({
        "pid": 9999999, "started_at": "2024-01-01T00:00:00Z", "hostname": "localhost"
    }))
    assert inspect_and_reclaim_if_stale(lock_path) is True
    assert not lock_path.exists()


def test_malformed_json_reclaimed(lock_path):
    lock_path.write_text("NOT JSON")
    assert inspect_and_reclaim_if_stale(lock_path) is True


def test_foreign_hostname_fails_closed(lock_path):
    lock_path.write_text(json.dumps({
        "pid": 9999999, "started_at": "2024-01-01T00:00:00Z", "hostname": "other-machine"
    }))
    with patch("ironledger.pipeline.sync_daemon._get_hostname", return_value="my-machine"):
        with pytest.raises(SyncLockActiveError):
            inspect_and_reclaim_if_stale(lock_path)


def test_release_removes_lock(lock_path):
    acquire_lock(lock_path)
    release_lock(lock_path)
    assert not lock_path.exists()


def test_release_lock_missing_ok(lock_path):
    assert not lock_path.exists()
    release_lock(lock_path)  # Should not raise


def test_release_permission_error(lock_path):
    lock_path.write_text("data")
    with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
        with pytest.raises(SyncLockPermissionError, match="Cannot release lock"):
            release_lock(lock_path)


def test_inspect_permission_error_reading(lock_path):
    lock_path.write_text("data")
    with patch.object(Path, "read_text", side_effect=PermissionError("access denied")):
        with pytest.raises(SyncLockPermissionError, match="Cannot read lock"):
            inspect_and_reclaim_if_stale(lock_path)


def test_inspect_permission_error_deleting_malformed(lock_path):
    lock_path.write_text("NOT JSON")
    with patch.object(Path, "unlink", side_effect=PermissionError("access denied")):
        with pytest.raises(SyncLockPermissionError, match="Cannot delete malformed lock"):
            inspect_and_reclaim_if_stale(lock_path)


def test_inspect_permission_error_deleting_stale(lock_path):
    lock_path.write_text(json.dumps({
        "pid": 9999999, "started_at": "2024-01-01T00:00:00Z", "hostname": "localhost"
    }))
    with patch.object(Path, "unlink", side_effect=PermissionError("access denied")):
        with pytest.raises(SyncLockPermissionError, match="Cannot delete stale lock"):
            inspect_and_reclaim_if_stale(lock_path)


def test_pid_reuse_unrelated_process_reclaimed(lock_path):
    lock_path.write_text(json.dumps({
        "pid": 12345, "started_at": "2024-01-01T00:00:00Z", "hostname": "localhost"
    }))
    with patch("ironledger.pipeline.sync_daemon._pid_exists", return_value=True), \
         patch("ironledger.pipeline.sync_daemon._pid_is_ironledger", return_value=False):
        assert inspect_and_reclaim_if_stale(lock_path) is True
        assert not lock_path.exists()


def test_acquire_already_held_live_process_raises(lock_path):
    import socket
    hn = socket.gethostname()
    lock_path.write_text(json.dumps({
        "pid": os.getpid(), "started_at": "2024-01-01T00:00:00Z", "hostname": hn
    }))
    with pytest.raises(SyncLockActiveError):
        acquire_lock(lock_path)


def test_acquire_reclaims_stale_lock_and_succeeds(lock_path):
    lock_path.write_text(json.dumps({
        "pid": 9999999, "started_at": "2024-01-01T00:00:00Z", "hostname": "localhost"
    }))
    acquire_lock(lock_path)
    assert lock_path.exists()
    data = json.loads(lock_path.read_text())
    assert data["pid"] == os.getpid()
    release_lock(lock_path)


def test_cli_sync_auth_status_no_creds(tmp_path, capsys, monkeypatch):
    from ironledger.cli.__main__ import main
    monkeypatch.delenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", raising=False)
    with patch("keyring.get_password", return_value=None):
        code = main(["--db", str(tmp_path / "test.db"), "sync", "auth", "status"])
        assert code == 0
        captured = capsys.readouterr()
        assert "No credentials stored. Run: ironledger sync auth claim" in captured.out


def test_cli_sync_auth_status_connected(tmp_path, capsys, monkeypatch):
    from ironledger.cli.__main__ import main
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org/simplefin",
    )
    code = main(["--db", str(tmp_path / "test.db"), "sync", "auth", "status"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Connected: https://***:***@bridge.simplefin.org/simplefin" in captured.out


def test_cli_sync_auth_claim_stdin(tmp_path, capsys):
    from ironledger.cli.__main__ import main
    with patch("sys.stdin.readline", return_value="claim-token-123\n"), \
         patch("ironledger.security.secrets.claim_setup_token", return_value="https://***:***@bridge.simplefin.org/simplefin") as mock_claim:
        code = main(["--db", str(tmp_path / "test.db"), "sync", "auth", "claim", "--stdin"])
        assert code == 0
        mock_claim.assert_called_once()
        captured = capsys.readouterr()
        assert "Access URL stored: https://***:***@bridge.simplefin.org/simplefin" in captured.out


def test_cli_sync_accounts_list(tmp_path, capsys):
    from ironledger.cli.__main__ import main
    from ironledger.db.connection import connect
    from ironledger.governance.migrations import migrate_governed
    db_file = tmp_path / "test.db"
    conn = connect(str(db_file))
    migrate_governed(conn)
    conn.execute(
        "INSERT INTO simplefin_account_map (remote_account_id, canonical_account, added_at_utc) "
        "VALUES ('acct-1', 'Assets:Bank:Checking', '2026-09-01T12:00:00Z')"
    )
    conn.commit()
    conn.close()

    code = main(["--db", str(db_file), "sync", "accounts", "list"])
    assert code == 0
    captured = capsys.readouterr()
    assert "acct-1 -> Assets:Bank:Checking" in captured.out


def test_cli_sync_poll_dry_run(tmp_path, capsys):
    from ironledger.cli.__main__ import main
    db_file = tmp_path / "test.db"
    sample_payload = {"accounts": [{"id": "acct1", "currency": "USD"}]}
    with patch("ironledger.ingest.formats.simplefin.fetch_accounts", return_value=sample_payload):
        code = main(["--db", str(db_file), "sync", "poll", "--dry-run"])
        assert code == 0
        captured = capsys.readouterr()
        assert '"id": "acct1"' in captured.out
        # Lock should be released
        assert not (tmp_path / ".sync.lock").exists()


def test_cli_sync_poll_normal(tmp_path, capsys):
    from ironledger.cli.__main__ import main
    db_file = tmp_path / "test.db"
    sample_payload = {
        "accounts": [{
            "id": "acct1",
            "currency": "USD",
            "transactions": [{
                "id": "tx1",
                "posted": 1704067200,
                "amount": "-15.00",
                "description": "Coffee",
                "memo": "Morning",
            }],
        }]
    }
    with patch("ironledger.ingest.formats.simplefin.fetch_accounts", return_value=sample_payload):
        code = main(["--db", str(db_file), "sync", "poll", "--lookback", "14"])
        assert code == 0
        captured = capsys.readouterr()
        assert "Sync: 1 inserted, 0 skipped" in captured.out
        assert not (tmp_path / ".sync.lock").exists()


def test_cli_sync_poll_locked_raises(tmp_path):
    import socket
    from ironledger.cli.__main__ import main
    db_file = tmp_path / "test.db"
    lock_file = tmp_path / ".sync.lock"
    hn = socket.gethostname()
    lock_file.write_text(json.dumps({
        "pid": os.getpid(), "started_at": "2024-01-01T00:00:00Z", "hostname": hn,
    }))
    with pytest.raises(SyncLockActiveError):
        main(["--db", str(db_file), "sync", "poll"])


def test_simplefin_engine_none_description(tmp_path):
    from ironledger.db.connection import connect
    from ironledger.governance.migrations import migrate_governed
    from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload
    db_file = tmp_path / "test.db"
    conn = connect(str(db_file))
    migrate_governed(conn)
    payload = {
        "accounts": [{
            "id": "acct1",
            "currency": "USD",
            "transactions": [{
                "id": "tx1",
                "posted": 1704067200,
                "amount": "-10.00",
                "description": None,
                "memo": None,
            }],
        }]
    }
    ins, skip = ingest_simplefin_payload(conn, payload, evidence_path=tmp_path / "ev.raw", account_map={})
    assert ins == 1 and skip == 0
    row = conn.execute("SELECT payee, narration FROM staged_transactions").fetchone()
    assert row[0] == ""
    assert row[1] == ""
    conn.close()

