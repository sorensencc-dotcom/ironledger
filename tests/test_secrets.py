# tests/test_secrets.py
from __future__ import annotations

import base64
import sqlite3
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from ironledger.governance.migrations import migrate_governed
from ironledger.security.secrets import (
    SIMPLEFIN_ALLOWED_HOSTS,
    CredentialsNotFoundError,
    SSRFViolationError,
    claim_setup_token,
    get_access_url,
    mask_access_url,
    store_access_url,
    validate_ssrf_safe,
)


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(tmp_path / "test.db")
    migrate_governed(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_mask_replaces_credentials():
    url = "https://alice:s3cr3t@bridge.simplefin.org/simplefin"
    assert mask_access_url(url) == "https://***:***@bridge.simplefin.org/simplefin"


def test_mask_no_credentials_passthrough():
    url = "https://bridge.simplefin.org/simplefin"
    assert mask_access_url(url) == url


def test_mask_empty_string():
    assert mask_access_url("") == ""


def test_ssrf_rejects_http():
    with pytest.raises(SSRFViolationError, match="https"):
        validate_ssrf_safe("http://bridge.simplefin.org/simplefin")


def test_ssrf_rejects_unknown_host():
    with pytest.raises(SSRFViolationError, match="allowlist"):
        validate_ssrf_safe("https://evil.com/simplefin")


def test_ssrf_rejects_private_ip(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("192.168.1.1", 443))],
    )
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_ssrf_rejects_loopback(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_ssrf_rejects_link_local(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("169.254.1.1", 443))],
    )
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_ssrf_rejects_dns_failure(monkeypatch):
    import socket

    def _fail_dns(*args, **kwargs):
        raise OSError("DNS failure")

    monkeypatch.setattr(socket, "getaddrinfo", _fail_dns)
    with pytest.raises(SSRFViolationError, match="DNS resolution failed"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_ssrf_accepts_valid_url(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))],
    )
    validate_ssrf_safe("https://bridge.simplefin.org/simplefin")  # no exception


def test_ssrf_accepts_beta_bridge_host(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))],
    )
    validate_ssrf_safe("https://beta-bridge.simplefin.org/simplefin")


def test_ssrf_rejects_non_standard_port():
    with pytest.raises(SSRFViolationError, match="Non-standard port blocked"):
        validate_ssrf_safe("https://bridge.simplefin.org:8443/simplefin")


def test_ssrf_rejects_http_port():
    with pytest.raises(SSRFViolationError, match="Non-standard port blocked"):
        validate_ssrf_safe("https://bridge.simplefin.org:80/simplefin")


def test_ssrf_accepts_explicit_port_443(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))],
    )
    validate_ssrf_safe("https://bridge.simplefin.org:443/simplefin")


def test_get_access_url_reads_env(monkeypatch, conn):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL", "https://u:p@bridge.simplefin.org/simplefin"
    )
    result = get_access_url(conn)
    assert result == "https://u:p@bridge.simplefin.org/simplefin"


def test_get_access_url_reads_keyring(monkeypatch, conn):
    monkeypatch.delenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", raising=False)
    with patch("keyring.get_password", return_value="https://keyring_u:keyring_p@bridge.simplefin.org/simplefin"):
        result = get_access_url(conn)
        assert result == "https://keyring_u:keyring_p@bridge.simplefin.org/simplefin"


def test_get_access_url_raises_when_missing(monkeypatch, conn):
    monkeypatch.delenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", raising=False)
    with patch("keyring.get_password", return_value=None):
        with pytest.raises(CredentialsNotFoundError):
            get_access_url(conn)


def test_get_access_url_emits_audit_event(monkeypatch, conn):
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL", "https://u:p@bridge.simplefin.org/simplefin"
    )
    get_access_url(conn)
    row = conn.execute(
        "SELECT action, result FROM audit_events WHERE action='CREDENTIAL_ACCESS_ATTEMPT'"
    ).fetchone()
    assert row is not None
    assert row[0] == "CREDENTIAL_ACCESS_ATTEMPT"
    assert row[1] == "ok"


def test_get_access_url_emits_audit_error_on_missing(monkeypatch, conn):
    monkeypatch.delenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", raising=False)
    with patch("keyring.get_password", return_value=None):
        with pytest.raises(CredentialsNotFoundError):
            get_access_url(conn)
    row = conn.execute(
        "SELECT action, result FROM audit_events WHERE action='CREDENTIAL_ACCESS_ATTEMPT'"
    ).fetchone()
    assert row is not None
    assert row[1] == "error"


def test_access_url_never_in_audit_payload(monkeypatch, conn):
    secret = "s3cr3t"
    monkeypatch.setenv(
        "IRONLEDGER_SIMPLEFIN_ACCESS_URL",
        f"https://u:{secret}@bridge.simplefin.org/simplefin",
    )
    get_access_url(conn)
    for row in conn.execute("SELECT * FROM audit_events").fetchall():
        for cell in row:
            assert secret not in str(cell)


def test_store_access_url_writes_to_keyring(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))],
    )
    target_url = "https://user:pass@bridge.simplefin.org/simplefin"
    with patch("keyring.set_password") as mock_set:
        store_access_url(target_url)
        mock_set.assert_called_once_with("ironledger", "simplefin_access_url", target_url)


def test_store_access_url_rejects_ssrf():
    with pytest.raises(SSRFViolationError):
        store_access_url("http://evil.com/simplefin")


def test_claim_setup_token_invalid_base64(conn):
    with pytest.raises(SSRFViolationError, match="base64"):
        claim_setup_token("not_valid_base64!@#$%", conn)


def test_claim_setup_token_rejects_ssrf_claim_url(conn):
    evil_token = base64.b64encode(b"http://evil.com/claim").decode("utf-8")
    with pytest.raises(SSRFViolationError):
        claim_setup_token(evil_token, conn)


def test_claim_setup_token_success(monkeypatch, conn):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))],
    )
    claim_url = "https://bridge.simplefin.org/claim/xyz"
    token_b64 = base64.b64encode(claim_url.encode("utf-8")).decode("utf-8")
    returned_access_url = "https://alice:secretpassword@bridge.simplefin.org/simplefin"

    mock_resp = MagicMock()
    mock_resp.read.return_value = returned_access_url.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("ironledger.security.secrets._make_no_redirect_opener") as mock_opener_factory, \
         patch("keyring.set_password") as mock_set_keyring:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_factory.return_value = mock_opener

        masked = claim_setup_token(token_b64, conn)

        assert masked == "https://***:***@bridge.simplefin.org/simplefin"
        assert mock_opener.open.call_args[1].get("timeout") == 30.0
        mock_set_keyring.assert_called_once_with(
            "ironledger", "simplefin_access_url", returned_access_url
        )

    rows = conn.execute(
        "SELECT action, result FROM audit_events WHERE action='CREDENTIAL_ACCESS_ATTEMPT'"
    ).fetchall()
    assert len(rows) >= 1
    assert rows[-1][1] == "ok"


def test_claim_setup_token_network_error(monkeypatch, conn):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))],
    )
    claim_url = "https://bridge.simplefin.org/claim/xyz"
    token_b64 = base64.b64encode(claim_url.encode("utf-8")).decode("utf-8")

    with patch("ironledger.security.secrets._make_no_redirect_opener") as mock_opener_factory:
        mock_opener = MagicMock()
        mock_opener.open.side_effect = urllib.error.URLError("Network unreachable")
        mock_opener_factory.return_value = mock_opener

        with pytest.raises(urllib.error.URLError):
            claim_setup_token(token_b64, conn)
        assert mock_opener.open.call_args[1].get("timeout") == 30.0

    rows = conn.execute(
        "SELECT action, result FROM audit_events WHERE action='CREDENTIAL_ACCESS_ATTEMPT'"
    ).fetchall()
    assert len(rows) >= 1
    assert rows[-1][1] == "error"


def test_redirect_handler_blocks_redirect():
    from ironledger.security.secrets import _make_no_redirect_opener

    opener = _make_no_redirect_opener()
    redirect_handlers = [
        h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
    ]
    assert len(redirect_handlers) == 1
    handler = redirect_handlers[0]

    with pytest.raises(SSRFViolationError, match="blocked by SSRF guard"):
        handler.redirect_request(
            req=MagicMock(),
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="https://evil.com/leak",
        )


def test_redirect_handler_masks_credentials_in_message():
    from ironledger.security.secrets import _make_no_redirect_opener

    opener = _make_no_redirect_opener()
    redirect_handlers = [
        h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
    ]
    assert len(redirect_handlers) == 1
    handler = redirect_handlers[0]

    with pytest.raises(SSRFViolationError) as excinfo:
        handler.redirect_request(
            req=MagicMock(),
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="https://leaked_user:leaked_pass@evil.com/leak",
        )
    err_msg = str(excinfo.value)
    assert "https://***:***@evil.com/leak" in err_msg
    assert "leaked_user" not in err_msg
    assert "leaked_pass" not in err_msg

