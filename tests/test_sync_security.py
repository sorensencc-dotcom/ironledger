# tests/test_sync_security.py
# NOTE: DNS rebinding residual risk -- IP validation resolves hostname before request;
# urllib re-resolves independently. Mitigated by host allowlist + TLS cert binding.
# Custom socket pinning deferred to Phase 8.
import pytest
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
