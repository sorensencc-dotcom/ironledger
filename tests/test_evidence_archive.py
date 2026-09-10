# tests/test_evidence_archive.py
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import ssl
import sys
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.simplefin import (
    EvidenceIntegrityError,
    _make_tls_context,
    archive_evidence,
    fetch_accounts,
)


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(tmp_path / "test.db")
    migrate_governed(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_archive_writes_file(tmp_path):
    data = b'{"accounts": []}'
    p = archive_evidence(data, evidence_dir=tmp_path)
    assert p.exists() and p.suffix == ".raw"
    assert p.read_bytes() == data


def test_archive_idempotent(tmp_path):
    data = b'{"accounts": []}'
    p1 = archive_evidence(data, evidence_dir=tmp_path)
    p2 = archive_evidence(data, evidence_dir=tmp_path)
    assert p1 == p2


def test_archive_content_addressed(tmp_path):
    data = b"test"
    sha = hashlib.sha256(data).hexdigest()
    p = archive_evidence(data, evidence_dir=tmp_path)
    assert p.name == f"{sha}.raw"


def test_archive_creates_parent_dirs(tmp_path):
    nested_dir = tmp_path / "nested" / "evidence" / "source_documents"
    data = b"nested test"
    p = archive_evidence(data, evidence_dir=nested_dir)
    assert p.exists()
    assert p.read_bytes() == data


def test_archive_corruption_raises(tmp_path):
    data = b'{"accounts": []}'
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / f"{sha}.raw").write_bytes(b"corrupted")
    with pytest.raises(EvidenceIntegrityError):
        archive_evidence(data, evidence_dir=tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_archive_windows_readonly(tmp_path):
    data = b"readonly test"
    p = archive_evidence(data, evidence_dir=tmp_path)
    with pytest.raises((PermissionError, OSError)):
        p.write_bytes(b"modified")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_archive_posix_readonly(tmp_path):
    data = b"readonly test"
    p = archive_evidence(data, evidence_dir=tmp_path)
    assert oct(os.stat(p).st_mode)[-3:] == "444"


def test_tls_context_invariants():
    ctx = _make_tls_context()
    assert ctx.protocol == ssl.PROTOCOL_TLS_CLIENT
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_fetch_accounts_success(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org/simplefin",
    )
    raw_payload = b'{"accounts": [{"id": "acc-1", "name": "Checking"}]}'
    sha256 = hashlib.sha256(raw_payload).hexdigest()

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_payload
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = fetch_accounts(
            conn,
            start_date=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc),
            evidence_dir=tmp_path,
        )

    assert result == {"accounts": [{"id": "acc-1", "name": "Checking"}]}
    ev_file = tmp_path / f"{sha256}.raw"
    assert ev_file.exists()
    assert ev_file.read_bytes() == raw_payload

    # Verify urlopen called with correct timeout and context
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    kwargs = mock_urlopen.call_args[1]
    assert kwargs.get("timeout") == 30.0
    assert "context" in kwargs

    # Verify request URL and Authorization header
    expected_start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    expected_end = int(datetime(2026, 1, 31, tzinfo=timezone.utc).timestamp())
    assert (
        req.full_url
        == f"https://bridge.simplefin.org/simplefin/accounts?start-date={expected_start}&end-date={expected_end}"
    )
    assert "testpass" not in req.full_url
    assert req.headers.get("Authorization") == "Basic dGVzdHVzZXI6dGVzdHBhc3M="

    # Verify EVIDENCE_ARCHIVED audit event
    rows = conn.execute(
        "SELECT action, target, result, input_hash, output_hash FROM audit_events WHERE action='EVIDENCE_ARCHIVED'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("EVIDENCE_ARCHIVED", f"{sha256}.raw", "ok", sha256, sha256)


def test_fetch_accounts_naive_datetimes(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org/simplefin",
    )
    raw_payload = b'{"accounts": []}'
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_payload
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = fetch_accounts(
            conn,
            start_date=datetime(2026, 2, 1, 0, 0, 0),
            end_date=datetime(2026, 2, 28, 23, 59, 59),
            evidence_dir=tmp_path,
        )

    assert result == {"accounts": []}
    req = mock_urlopen.call_args[0][0]
    start_ts = int(datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    assert f"start-date={start_ts}&end-date={end_ts}" in req.full_url


def test_fetch_accounts_network_error(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org/simplefin",
    )
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")
    ):
        with pytest.raises(urllib.error.URLError):
            fetch_accounts(
                conn,
                start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
                evidence_dir=tmp_path,
            )

    rows = conn.execute(
        "SELECT action, target, result FROM audit_events WHERE action='SIMPLEFIN_FETCH_ERROR'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "SIMPLEFIN_FETCH_ERROR"
    assert rows[0][2] == "error"
    assert "testpass" not in rows[0][1]


def test_fetch_accounts_never_leaks_secret_in_audit(conn, tmp_path, monkeypatch):
    secret = "super_secret_token"
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        f"https://operator:{secret}@bridge.simplefin.org/simplefin",
    )
    raw_payload = b'{"accounts": []}'
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_payload
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_resp):
        fetch_accounts(
            conn,
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
            evidence_dir=tmp_path,
        )

    for row in conn.execute("SELECT * FROM audit_events").fetchall():
        for col in row:
            assert secret not in str(col)
