"""Native secret store bridge, SSRF guard, and credential masking for Phase 7."""

from __future__ import annotations

import base64
import http.client
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
    "make_no_redirect_opener",
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


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        pinned_ip: str | None = None,
        context: ssl.SSLContext | None = None,
        **kwargs,
    ) -> None:
        super().__init__(host, port, context=context, **kwargs)
        self._pinned_ip = pinned_ip
        self._server_hostname = host

    def connect(self) -> None:
        target_host = self._pinned_ip if self._pinned_ip else self.host
        self.sock = socket.create_connection(
            (target_host, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        if self._context:
            self.sock = self._context.wrap_socket(
                self.sock,
                server_hostname=self._server_hostname,
            )


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(
        self,
        pinned_ip: str | None = None,
        context: ssl.SSLContext | None = None,
        **kwargs,
    ) -> None:
        super().__init__(context=context, **kwargs)
        self._pinned_ip = pinned_ip

    def https_open(self, req: urllib.request.Request):  # type: ignore[override]
        return self.do_open(
            lambda host, **kw: _PinnedHTTPSConnection(
                host, pinned_ip=self._pinned_ip, context=self._context, **kw
            ),
            req,
        )


def make_no_redirect_opener(
    ssl_context: ssl.SSLContext | None = None,
    pinned_ip: str | None = None,
) -> urllib.request.OpenerDirector:
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            raise SSRFViolationError(
                f"HTTP redirect to {mask_access_url(newurl)!r} blocked by SSRF guard"
            )

    handlers: list[type[urllib.request.BaseHandler] | urllib.request.BaseHandler] = [
        NoRedirectHandler
    ]
    if ssl_context is not None or pinned_ip is not None:
        handlers.append(_PinnedHTTPSHandler(pinned_ip=pinned_ip, context=ssl_context))
    return urllib.request.build_opener(*handlers)


_make_no_redirect_opener = make_no_redirect_opener


def validate_ssrf_safe(url: str) -> str:
    """Raise SSRFViolationError if url fails the SSRF guard. Returns validated pinned IP."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SSRFViolationError(f"URL must use https scheme; got {parsed.scheme!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SSRFViolationError("Non-standard port blocked") from exc
    if port is not None and port != 443:
        raise SSRFViolationError("Non-standard port blocked")
    host = parsed.hostname or ""
    if host not in SIMPLEFIN_ALLOWED_HOSTS:
        raise SSRFViolationError(f"Host {host!r} is not in the allowlist {SIMPLEFIN_ALLOWED_HOSTS}")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SSRFViolationError(f"DNS resolution failed for {host!r}: {exc}") from exc
    if not infos:
        raise SSRFViolationError(f"DNS resolution returned no addresses for {host!r}")

    validated_ips: list[str] = []
    for *_, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise SSRFViolationError(f"Resolved IP {ip_str!r} is private/loopback/reserved")
        validated_ips.append(ip_str)

    if not validated_ips:
        raise SSRFViolationError(f"No valid public IP addresses resolved for {host!r}")
    return validated_ips[0]


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
        try:
            validate_ssrf_safe(env_val)
        except Exception:
            try:
                _emit_credential_audit(conn, source="env", outcome="failure")
            except Exception:
                pass
            raise
        _emit_credential_audit(conn, source="env", outcome="success")
        return env_val
    keyring_val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    if keyring_val:
        try:
            validate_ssrf_safe(keyring_val)
        except Exception:
            try:
                _emit_credential_audit(conn, source="keyring", outcome="failure")
            except Exception:
                pass
            raise
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
        try:
            claim_url = base64.b64decode(token_b64.strip()).decode("utf-8").strip()
        except Exception as exc:
            raise SSRFViolationError(f"Setup token is not valid base64: {exc}") from exc
        pinned_ip = validate_ssrf_safe(claim_url)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        opener = _make_no_redirect_opener(ssl_context=ctx, pinned_ip=pinned_ip)
        req = urllib.request.Request(claim_url, method="POST", data=b"")
        with opener.open(req, timeout=30.0) as resp:
            access_url = resp.read().decode("utf-8").strip()
        store_access_url(access_url)
        _emit_credential_audit(conn, source="claim", outcome="success")
        return mask_access_url(access_url)
    except Exception as orig_exc:
        try:
            _emit_credential_audit(conn, source="claim", outcome="failure")
        except Exception:
            pass
        raise orig_exc
