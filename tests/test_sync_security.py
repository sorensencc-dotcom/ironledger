# tests/test_sync_security.py
# NOTE: DNS rebinding residual risk -- IP validation resolves hostname before request;
# urllib re-resolves independently. Mitigated by host allowlist + TLS cert binding.
# Custom socket pinning deferred to Phase 8.
from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.simplefin import fetch_accounts
from ironledger.security.secrets import SSRFViolationError, validate_ssrf_safe


def test_rejects_http():
    with pytest.raises(SSRFViolationError):
        validate_ssrf_safe("http://bridge.simplefin.org/simplefin")


def test_rejects_non_allowlist_host():
    with pytest.raises(SSRFViolationError):
        validate_ssrf_safe("https://attacker.com/simplefin")


def test_rejects_private_ip(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("10.0.0.1", 443))])
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_rejects_loopback(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_rejects_link_local(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("169.254.0.1", 443))])
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(tmp_path / "test.db")
    migrate_governed(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_fetch_accounts_aware_non_utc_datetimes(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org/simplefin",
    )
    raw_payload = b'{"accounts": []}'
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_payload
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    tz_est = timezone(timedelta(hours=-5))
    start_dt = datetime(2026, 3, 1, 10, 0, 0, tzinfo=tz_est)
    end_dt = datetime(2026, 3, 15, 18, 30, 0, tzinfo=tz_est)

    expected_start_ts = int(start_dt.astimezone(timezone.utc).timestamp())
    expected_end_ts = int(end_dt.astimezone(timezone.utc).timestamp())

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_resp

    with patch("ironledger.ingest.formats.simplefin.make_no_redirect_opener", return_value=mock_opener):
        result = fetch_accounts(
            conn,
            start_date=start_dt,
            end_date=end_dt,
            evidence_dir=tmp_path,
        )

    assert result == {"accounts": []}
    mock_opener.open.assert_called_once()
    req = mock_opener.open.call_args[0][0]
    assert f"start-date={expected_start_ts}&end-date={expected_end_ts}" in req.full_url
    naive_replacement_ts = int(start_dt.replace(tzinfo=timezone.utc).timestamp())
    assert expected_start_ts != naive_replacement_ts
    assert expected_start_ts - naive_replacement_ts == 5 * 3600


def test_fetch_accounts_ssrf_validation(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://evil-attacker.com/simplefin",
    )
    with pytest.raises(SSRFViolationError):
        fetch_accounts(
            conn,
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
            evidence_dir=tmp_path,
        )


def test_fetch_accounts_retains_custom_port(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org:8443/simplefin",
    )
    raw_payload = b'{"accounts": []}'
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_payload
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_resp

    with patch("ironledger.security.secrets.validate_ssrf_safe"), \
         patch("ironledger.ingest.formats.simplefin.validate_ssrf_safe"), \
         patch("ironledger.ingest.formats.simplefin.make_no_redirect_opener", return_value=mock_opener):
        fetch_accounts(
            conn,
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
            evidence_dir=tmp_path,
        )

    req = mock_opener.open.call_args[0][0]
    assert req.full_url.startswith("https://bridge.simplefin.org:8443/simplefin/accounts?")


def test_fetch_accounts_blocks_http_redirect(conn, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        "https://testuser:testpass@bridge.simplefin.org/simplefin",
    )
    # The real opener should block redirects
    from ironledger.security.secrets import make_no_redirect_opener
    opener = make_no_redirect_opener()
    
    # Test that opening a redirect raises SSRFViolationError
    req = MagicMock()
    handler = [h for h in opener.handlers if hasattr(h, "redirect_request")][0]
    with pytest.raises(SSRFViolationError, match="HTTP redirect to .* blocked by SSRF guard"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.com/leak")
