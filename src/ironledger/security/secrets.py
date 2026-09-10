"""Native secret store bridge, SSRF guard, and credential masking for Phase 7."""

from __future__ import annotations

import base64
import ipaddress
import os
import re
import socket
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request

import keyring

from ironledger.audit import append_audit_event

__all__ = [
    "CredentialsNotFoundError",
    "SSRFViolationError",
    "SIMPLEFIN_ALLOWED_HOSTS",
    "mask_access_url",
    "validate_ssrf_safe",
    "get_access_url",
    "store_access_url",
    "claim_setup_token",
]

_KEYRING_SERVICE = "ironledger"
_KEYRING_USERNAME = "simplefin_access_url"
_ENV_VAR = "IRONLEDGER_SIMPLEFIN_ACCESS_URL"
SIMPLEFIN_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {"bridge.simplefin.org", "beta-bridge.simplefin.org"}
)
_CREDENTIALS_RE = re.compile(r"(https?://)([^:@/]+:[^@/]+@)")


class CredentialsNotFoundError(Exception):
    """No SimpleFIN access URL found in environment or keyring."""


class SSRFViolationError(Exception):
    """A URL failed the SSRF allowlist or IP guard."""


def mask_access_url(url: str) -> str:
    """Replace user:pass@ with ***:***@ in a SimpleFIN access URL."""
    return _CREDENTIALS_RE.sub(r"\1***:***@", url)


def _make_no_redirect_opener(
    ssl_context: ssl.SSLContext | None = None,
) -> urllib.request.OpenerDirector:
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            raise SSRFViolationError(f"HTTP redirect to {newurl!r} blocked by SSRF guard")

    handlers: list[type[urllib.request.BaseHandler] | urllib.request.BaseHandler] = [
        NoRedirectHandler
    ]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    return urllib.request.build_opener(*handlers)


def validate_ssrf_safe(url: str) -> None:
    """Raise SSRFViolationError if url fails the SSRF guard."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SSRFViolationError(f"URL must use https scheme; got {parsed.scheme!r}")
    host = parsed.hostname or ""
    if host not in SIMPLEFIN_ALLOWED_HOSTS:
        raise SSRFViolationError(f"Host {host!r} is not in the allowlist {SIMPLEFIN_ALLOWED_HOSTS}")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SSRFViolationError(f"DNS resolution failed for {host!r}: {exc}") from exc
    if not infos:
        raise SSRFViolationError(f"DNS resolution returned no addresses for {host!r}")
    for *_, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise SSRFViolationError(f"Resolved IP {ip_str!r} is private/loopback/reserved")


def _emit_credential_audit(conn: sqlite3.Connection, *, source: str, outcome: str) -> None:
    append_audit_event(
        conn,
        actor="system",
        action="CREDENTIAL_ACCESS_ATTEMPT",
        target=_KEYRING_USERNAME,
        result="ok" if outcome == "success" else "error",
    )
    conn.commit()


def get_access_url(conn: sqlite3.Connection) -> str:
    """Resolve SimpleFIN access URL from env -> keyring. Emits CREDENTIAL_ACCESS_ATTEMPT."""
    env_val = os.environ.get(_ENV_VAR)
    if env_val:
        _emit_credential_audit(conn, source="env", outcome="success")
        return env_val
    keyring_val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    if keyring_val:
        _emit_credential_audit(conn, source="keyring", outcome="success")
        return keyring_val
    _emit_credential_audit(conn, source="missing", outcome="failure")
    raise CredentialsNotFoundError("No SimpleFIN access URL. Run: ironledger sync auth claim")


def store_access_url(access_url: str) -> None:
    """Validate and write access URL to the OS keyring."""
    validate_ssrf_safe(access_url)
    keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, access_url)


def claim_setup_token(token_b64: str, conn: sqlite3.Connection) -> str:
    """Decode a SimpleFIN setup token, claim the access URL, store it, return masked URL."""
    try:
        claim_url = base64.b64decode(token_b64.strip()).decode("utf-8").strip()
    except Exception as exc:
        raise SSRFViolationError(f"Setup token is not valid base64: {exc}") from exc
    validate_ssrf_safe(claim_url)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    opener = _make_no_redirect_opener(ssl_context=ctx)
    req = urllib.request.Request(claim_url, method="POST", data=b"")
    try:
        with opener.open(req) as resp:
            access_url = resp.read().decode("utf-8").strip()
    except urllib.error.URLError:
        _emit_credential_audit(conn, source="claim", outcome="failure")
        raise
    store_access_url(access_url)
    _emit_credential_audit(conn, source="claim", outcome="success")
    return mask_access_url(access_url)
