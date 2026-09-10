"""SimpleFIN Bridge HTTP client and raw evidence archival for Phase 7."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import ssl
import sys
import urllib.parse
import urllib.request

from ironledger.audit import append_audit_event
from ironledger.security.secrets import (
    get_access_url,
    mask_access_url,
    validate_ssrf_safe,
)

__all__ = ["EvidenceIntegrityError", "archive_evidence", "fetch_accounts"]


class EvidenceIntegrityError(Exception):
    """Existing evidence file differs from expected bytes for its SHA-256 name."""


def _make_tls_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    ctx.load_default_certs()
    return ctx


def _apply_readonly(path: Path) -> None:
    # Best-effort. rename->chmod is non-atomic; SHA-256 in audit log is the authoritative anchor.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x01)  # type: ignore[attr-defined]
    else:
        os.chmod(path, 0o444)


def archive_evidence(raw_bytes: bytes, *, evidence_dir: Path) -> Path:
    """Write raw wire bytes to content-addressed .raw file. Idempotent."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    target = evidence_dir / f"{file_sha256}.raw"
    if target.exists():
        if target.read_bytes() != raw_bytes:
            raise EvidenceIntegrityError(f"Existing {target.name} has different bytes")
        return target
    tmp = evidence_dir / f"{file_sha256}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(raw_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        _apply_readonly(target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target


def fetch_accounts(
    conn: sqlite3.Connection,
    *,
    start_date: datetime,
    end_date: datetime,
    evidence_dir: Path,
) -> dict:
    """Fetch /simplefin/accounts, archive wire bytes, return parsed JSON."""
    access_url = get_access_url(conn)
    validate_ssrf_safe(access_url)
    parsed = urllib.parse.urlparse(access_url)
    username = parsed.username or ""
    password = parsed.password or ""
    host = (
        f"{parsed.hostname}:{parsed.port}"
        if parsed.port and parsed.port != 443
        else parsed.hostname
    )
    base = f"https://{host}/simplefin/accounts"
    start_dt = (
        start_date.replace(tzinfo=timezone.utc)
        if start_date.tzinfo is None
        else start_date.astimezone(timezone.utc)
    )
    end_dt = (
        end_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None
        else end_date.astimezone(timezone.utc)
    )
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    url = f"{base}?start-date={start_ts}&end-date={end_ts}"
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
    try:
        with urllib.request.urlopen(req, context=_make_tls_context(), timeout=30.0) as resp:
            raw_bytes = resp.read()
    except Exception:
        append_audit_event(
            conn,
            actor="system",
            action="SIMPLEFIN_FETCH_ERROR",
            target=mask_access_url(url),
            result="error",
        )
        conn.commit()
        raise
    ev_path = archive_evidence(raw_bytes, evidence_dir=evidence_dir)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    append_audit_event(
        conn,
        actor="system",
        action="EVIDENCE_ARCHIVED",
        target=ev_path.name,
        result="ok",
        input_hash=sha256,
        output_hash=sha256,
    )
    conn.commit()
    return json.loads(raw_bytes)
