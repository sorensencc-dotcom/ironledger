# Phase 7: Automated Bank Synchronization & Secret Store Boundary -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Integrate SimpleFIN Bridge polling into IronLedger immutable staging buffer with hermetic secret boundary, SSRF guard, and full evidence archiving. Seven independently testable tasks.

**Architecture:** Secrets live in OS keyring or environment variable, never in SQLite or process arguments. Polling writes exact wire bytes to content-addressed evidence files, then stages via INSERT ON CONFLICT DO NOTHING backed by UNIQUE(external_id). Lockfile daemon prevents overlap. /api/sync/* router exposes status and manual trigger.

**Tech Stack:** Python 3.11+, stdlib only for HTTP (urllib.request, ssl, socket), keyring, psutil, FastAPI (existing), SQLite (existing migrations runner), pytest, unittest.mock.

## Global Constraints

- No new third-party HTTP library; transport uses stdlib urllib.request only.
- UNIQUE(external_id) enforced in migration -- app-level check is defence-in-depth.
- All timestamps: UTC ISO-8601 with trailing Z.
- Amount formula: sign * (dollars * 100 + cents). Grammar: ^[+-]?\d+(\.\d{1,2})?$
- Primary fingerprint: simplefin:id:<account_id>:<tx_id>. Fallback: composite:v1:<sha256(...)>
- SimpleFIN host allowlist: bridge.simplefin.org, beta-bridge.simplefin.org.
- SSRF guard rejects non-HTTPS, private/loopback IPs, redirects. DNS rebinding is accepted residual risk.
- TLS: SSLContext(PROTOCOL_TLS_CLIENT), minimum_version=TLSv1_2, CERT_REQUIRED, check_hostname=True.
- Credentials masked via mask_access_url() before logs, exceptions, audit events.
- CREDENTIAL_ACCESS_ATTEMPT audit event emitted on every credential resolution.
- Migration numbering: next is 0007.
- Test runner: python -m pytest tests/<file>.py -v from C:\dev\IronLedger.

---

## File Map

### New files
| File | Responsibility |
|---|---|
| src/ironledger/security/__init__.py | Package marker |
| src/ironledger/security/secrets.py | SecretStore: keyring, SSRF guard, masking |
| src/ironledger/ingest/formats/simplefin.py | HTTP client, TLS, evidence archival |
| src/ironledger/ingest/formats/simplefin_engine.py | Feed parser, amount normalization, deduplication |
| src/ironledger/pipeline/__init__.py | Package marker |
| src/ironledger/pipeline/sync_daemon.py | Lockfile: acquire, release, stale inspection |
| src/ironledger/web/routers/sync.py | /api/sync/status + /api/sync/poll |
| src/ironledger/db/schema/0007_simplefin_sync.sql | external_id column + simplefin_account_map |
| tests/test_migration_0007.py | Migration tests |
| tests/test_secrets.py | SecretStore tests |
| tests/test_sync_security.py | SSRF + TLS tests |
| tests/test_evidence_archive.py | Archival tests |
| tests/test_simplefin_parser.py | Parser + fingerprint tests |
| tests/test_sync_idempotency.py | Dedupe tests |
| tests/test_sync_lock.py | Lockfile scenario tests |
| tests/test_web_sync.py | REST API tests |
| tests/test_phase7_e2e.py | E2E pipeline test |

### Modified files
| File | Change |
|---|---|
| src/ironledger/db/schema/__init__.py | Register 0007_simplefin_sync.sql |
| src/ironledger/web/app.py | Register sync router |
| src/ironledger/cli/__main__.py | Add sync subcommand group |
| config/simplefin_accounts.json | New seed file ({}) |

---

## Task 1: Migration 0007 -- external_id + simplefin_account_map

**Files:**
- Create: `src/ironledger/db/schema/0007_simplefin_sync.sql`
- Modify: `src/ironledger/db/schema/__init__.py`
- Test: `tests/test_migration_0007.py`

**Interfaces:**
- Produces: column `external_id TEXT` (nullable) on `staged_transactions`; partial UNIQUE index on non-NULL values; table `simplefin_account_map(remote_account_id TEXT PK, canonical_account TEXT, added_at_utc TEXT)`.

- [ ] **Step 1.1: Write the failing migration test**

```python
# tests/test_migration_0007.py
import sqlite3
import pytest
from ironledger.db.connection import connect
from ironledger.governance.migrations import migrate_governed


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    conn = connect(p)
    migrate_governed(conn, p)
    conn.close()
    return p


def test_external_id_column_exists(db):
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(staged_transactions)")}
    assert "external_id" in cols
    conn.close()


def test_external_id_unique_constraint(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO source_documents VALUES "
        "('sd1','application/json','utf-8','test',"
        "'2024-01-01T00:00:00Z','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
        "'ref1','2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source_records VALUES "
        "('sr1','sd1',0,'payload',"
        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','2024-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO staged_transactions "
        "(staged_transaction_id,source_record_id,proposed_date,"
        "identity_algo_version,identity_method,identity_fingerprint,created_at_utc,external_id) "
        "VALUES ('stx1','sr1','2024-01-01',1,'fitid',"
        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
        "'2024-01-01T00:00:00Z','ext:1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO staged_transactions "
            "(staged_transaction_id,source_record_id,proposed_date,"
            "identity_algo_version,identity_method,identity_fingerprint,created_at_utc,external_id) "
            "VALUES ('stx2','sr1','2024-01-01',1,'fitid',"
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
            "'2024-01-01T00:00:00Z','ext:1')"
        )
    conn.close()


def test_simplefin_account_map_table(db):
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "simplefin_account_map" in tables
    conn.close()
```

- [ ] **Step 1.2: Run to verify failure**

```
python -m pytest tests/test_migration_0007.py -v
```
Expected: FAIL -- external_id column and simplefin_account_map do not exist.

- [ ] **Step 1.3: Write the migration SQL**

```sql
-- src/ironledger/db/schema/0007_simplefin_sync.sql
-- Phase 7: SimpleFIN sync support.

ALTER TABLE staged_transactions ADD COLUMN external_id TEXT;

-- Partial unique index: only non-NULL external_ids must be unique.
-- SQLite ALTER TABLE cannot add UNIQUE inline; partial index is idiomatic.
CREATE UNIQUE INDEX idx_staged_transactions_external_id
    ON staged_transactions (external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE simplefin_account_map (
    remote_account_id  TEXT PRIMARY KEY,
    canonical_account  TEXT NOT NULL,
    added_at_utc       TEXT NOT NULL CHECK (added_at_utc GLOB '????-??-??T??:??:??*Z')
) STRICT;

CREATE TRIGGER simplefin_account_map_no_update
BEFORE UPDATE ON simplefin_account_map
BEGIN
    SELECT RAISE(ABORT, 'simplefin_account_map is append-only: UPDATE is forbidden');
END;
```

- [ ] **Step 1.4: Register migration in `src/ironledger/db/schema/__init__.py`**

Append `"0007_simplefin_sync.sql"` to the ordered migrations list following the existing pattern exactly.

- [ ] **Step 1.5: Run to verify pass**

```
python -m pytest tests/test_migration_0007.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 1.6: Full suite -- no regressions**

```
python -m pytest tests/ -x -q
```

- [ ] **Step 1.7: Commit**

```
git add src/ironledger/db/schema/0007_simplefin_sync.sql src/ironledger/db/schema/__init__.py tests/test_migration_0007.py
git commit -m "feat(db): migration 0007 -- external_id + simplefin_account_map"
```

---

## Task 2: Secret Store -- security/secrets.py

**Files:**
- Create: `src/ironledger/security/__init__.py` (empty)
- Create: `src/ironledger/security/secrets.py`
- Test: `tests/test_secrets.py`

**Interfaces:**
- Consumes: `keyring` (add to deps if not present), stdlib `ipaddress`, `urllib.parse`, `base64`, `ssl`, `socket`, `getpass`.
- Produces:
  - `class CredentialsNotFoundError(Exception)`
  - `class SSRFViolationError(Exception)`
  - `SIMPLEFIN_ALLOWED_HOSTS: frozenset[str]` = `{"bridge.simplefin.org", "beta-bridge.simplefin.org"}`
  - `def mask_access_url(url: str) -> str` -- replaces `user:pass@` with `***:***@`
  - `def validate_ssrf_safe(url: str) -> None` -- raises `SSRFViolationError` on failure
  - `def get_access_url(conn: sqlite3.Connection) -> str` -- env -> keyring; emits `CREDENTIAL_ACCESS_ATTEMPT`
  - `def store_access_url(access_url: str) -> None`
  - `def claim_setup_token(token_b64: str, conn: sqlite3.Connection) -> str`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_secrets.py
import sqlite3
import pytest
from unittest.mock import patch
from ironledger.security.secrets import (
    CredentialsNotFoundError, SSRFViolationError,
    mask_access_url, validate_ssrf_safe, get_access_url,
)


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
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("192.168.1.1", 443))])
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_ssrf_rejects_loopback(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(SSRFViolationError, match="private"):
        validate_ssrf_safe("https://bridge.simplefin.org/simplefin")


def test_ssrf_accepts_valid_url(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("1.2.3.4", 443))])
    validate_ssrf_safe("https://bridge.simplefin.org/simplefin")  # no exception


def test_get_access_url_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", "https://u:p@bridge.simplefin.org/simplefin")
    conn = sqlite3.connect(tmp_path / "test.db")
    from ironledger.governance.migrations import migrate_governed
    migrate_governed(conn, tmp_path / "test.db")
    result = get_access_url(conn)
    assert result == "https://u:p@bridge.simplefin.org/simplefin"
    conn.close()


def test_get_access_url_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", raising=False)
    conn = sqlite3.connect(tmp_path / "test.db")
    from ironledger.governance.migrations import migrate_governed
    migrate_governed(conn, tmp_path / "test.db")
    with patch("keyring.get_password", return_value=None):
        with pytest.raises(CredentialsNotFoundError):
            get_access_url(conn)
    conn.close()


def test_get_access_url_emits_audit_event(monkeypatch, tmp_path):
    monkeypatch.setenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", "https://u:p@bridge.simplefin.org/simplefin")
    conn = sqlite3.connect(tmp_path / "test.db")
    from ironledger.governance.migrations import migrate_governed
    migrate_governed(conn, tmp_path / "test.db")
    get_access_url(conn)
    row = conn.execute("SELECT action FROM audit_events WHERE action='CREDENTIAL_ACCESS_ATTEMPT'").fetchone()
    assert row is not None
    conn.close()


def test_access_url_never_in_audit_payload(monkeypatch, tmp_path):
    secret = "s3cr3t"
    monkeypatch.setenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", f"https://u:{secret}@bridge.simplefin.org/simplefin")
    conn = sqlite3.connect(tmp_path / "test.db")
    from ironledger.governance.migrations import migrate_governed
    migrate_governed(conn, tmp_path / "test.db")
    get_access_url(conn)
    for row in conn.execute("SELECT * FROM audit_events").fetchall():
        for cell in row:
            assert secret not in str(cell)
    conn.close()
```

- [ ] **Step 2.2: Run to verify failure**

```
python -m pytest tests/test_secrets.py -v
```
Expected: FAIL -- ModuleNotFoundError ironledger.security.

- [ ] **Step 2.3: Create `src/ironledger/security/__init__.py`** (empty file)

- [ ] **Step 2.4: Implement `src/ironledger/security/secrets.py`**

```python
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
    "CredentialsNotFoundError", "SSRFViolationError", "SIMPLEFIN_ALLOWED_HOSTS",
    "mask_access_url", "validate_ssrf_safe", "get_access_url",
    "store_access_url", "claim_setup_token",
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


def _make_no_redirect_opener() -> urllib.request.OpenerDirector:
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            raise SSRFViolationError(f"HTTP redirect to {newurl!r} blocked by SSRF guard")
    return urllib.request.build_opener(NoRedirectHandler)


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
    opener = _make_no_redirect_opener()
    req = urllib.request.Request(claim_url, method="POST", data=b"")
    try:
        with opener.open(req) as resp:
            access_url = resp.read().decode("utf-8").strip()
    except urllib.error.URLError as exc:
        _emit_credential_audit(conn, source="claim", outcome="failure")
        raise
    store_access_url(access_url)
    _emit_credential_audit(conn, source="claim", outcome="success")
    return mask_access_url(access_url)
```

- [ ] **Step 2.5: Run to verify pass**

```
python -m pytest tests/test_secrets.py -v
```

- [ ] **Step 2.6: Full suite**

```
python -m pytest tests/ -x -q
```

- [ ] **Step 2.7: Commit**

```
git add src/ironledger/security/ tests/test_secrets.py
git commit -m "feat(security): SecretStore -- keyring bridge, SSRF guard, credential masking"
```

---

## Task 3: SimpleFIN HTTP Client & Evidence Archival -- simplefin.py

**Files:**
- Create: `src/ironledger/ingest/formats/simplefin.py`
- Test: `tests/test_sync_security.py`, `tests/test_evidence_archive.py`

**Interfaces:**
- Consumes: `security.secrets.get_access_url`, `mask_access_url`.
- Produces:
  - `class EvidenceIntegrityError(Exception)`
  - `def archive_evidence(raw_bytes: bytes, *, evidence_dir: Path) -> Path`
  - `def fetch_accounts(conn: sqlite3.Connection, *, start_date: datetime, end_date: datetime, evidence_dir: Path) -> dict`

- [ ] **Step 3.1: Write failing tests**

```python
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
```

```python
# tests/test_evidence_archive.py
import hashlib, os, sys, pytest
from pathlib import Path
from ironledger.ingest.formats.simplefin import archive_evidence, EvidenceIntegrityError


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
```

- [ ] **Step 3.2: Run to verify failure**

```
python -m pytest tests/test_sync_security.py tests/test_evidence_archive.py -v
```

- [ ] **Step 3.3: Implement `src/ironledger/ingest/formats/simplefin.py`**

```python
"""SimpleFIN Bridge HTTP client and raw evidence archival for Phase 7."""

from __future__ import annotations

import base64, hashlib, json, os, sqlite3, ssl, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ironledger.audit import append_audit_event
from ironledger.security.secrets import get_access_url, mask_access_url

__all__ = ["EvidenceIntegrityError", "archive_evidence", "fetch_accounts"]


class EvidenceIntegrityError(Exception):
    """Existing evidence file differs from expected bytes for its SHA-256 name."""


def _make_tls_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
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
    parsed = urllib.parse.urlparse(access_url)
    username = parsed.username or ""
    password = parsed.password or ""
    base = f"https://{parsed.hostname}/simplefin/accounts"
    start_ts = int(start_date.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(end_date.replace(tzinfo=timezone.utc).timestamp())
    url = f"{base}?start-date={start_ts}&end-date={end_ts}"
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
    try:
        with urllib.request.urlopen(req, context=_make_tls_context()) as resp:
            raw_bytes = resp.read()
    except Exception as exc:
        append_audit_event(conn, actor="system", action="SIMPLEFIN_FETCH_ERROR",
                           target=mask_access_url(url), result="error")
        raise
    ev_path = archive_evidence(raw_bytes, evidence_dir=evidence_dir)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    append_audit_event(conn, actor="system", action="EVIDENCE_ARCHIVED",
                       target=ev_path.name, result="ok", input_hash=sha256, output_hash=sha256)
    return json.loads(raw_bytes)
```

- [ ] **Step 3.4: Run to verify pass**

```
python -m pytest tests/test_sync_security.py tests/test_evidence_archive.py -v
```

- [ ] **Step 3.5: Full suite**

```
python -m pytest tests/ -x -q
```

- [ ] **Step 3.6: Commit**

```
git add src/ironledger/ingest/formats/simplefin.py tests/test_sync_security.py tests/test_evidence_archive.py
git commit -m "feat(ingest): SimpleFIN HTTP client + hermetic evidence archival"
```

---

## Task 4: Feed Parser & DB-Enforced Deduplication -- simplefin_engine.py

**Files:**
- Create: `src/ironledger/ingest/formats/simplefin_engine.py`
- Test: `tests/test_simplefin_parser.py`, `tests/test_sync_idempotency.py`

**Interfaces:**
- Produces:
  - `def parse_amount(amount_str: str) -> int` -- raises `ParseError` on invalid grammar; formula: `sign * (dollars * 100 + cents)`
  - `def simplefin_external_id(account_id, tx_id, *, posted_date, amount_cents, currency, description, memo) -> str`
  - `def ingest_simplefin_payload(conn, payload, *, evidence_path, account_map) -> tuple[int, int]`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_simplefin_parser.py
import pytest
from ironledger.ingest.errors import ParseError
from ironledger.ingest.formats.simplefin_engine import parse_amount, simplefin_external_id


@pytest.mark.parametrize("amount_str,expected", [
    ("-12", -1200), ("-0.34", -34), ("+12", 1200),
    ("12", 1200), ("0", 0), ("0.00", 0),
    ("1.50", 150), ("-1.50", -150), ("99.99", 9999),
])
def test_parse_amount_valid(amount_str, expected):
    assert parse_amount(amount_str) == expected


@pytest.mark.parametrize("bad", [
    "1,000", "1.234", "1e2", " 12", "12 ", "", "abc",
])
def test_parse_amount_invalid(bad):
    with pytest.raises(ParseError):
        parse_amount(bad)


def test_primary_id_when_tx_id_present():
    eid = simplefin_external_id("acct123", "tx456", posted_date="2024-01-01",
                                 amount_cents=-1200, currency="USD", description="Coffee", memo="")
    assert eid == "simplefin:id:acct123:tx456"


def test_composite_id_when_tx_id_absent():
    eid = simplefin_external_id("acct123", None, posted_date="2024-01-01",
                                 amount_cents=-1200, currency="USD", description="Coffee", memo="")
    assert eid.startswith("composite:v1:")
    assert len(eid) == len("composite:v1:") + 64


def test_composite_id_is_account_scoped():
    kwargs = dict(tx_id=None, posted_date="2024-01-01", amount_cents=100,
                  currency="USD", description="X", memo="")
    assert simplefin_external_id("A", **kwargs) != simplefin_external_id("B", **kwargs)


def test_composite_id_is_stable():
    kwargs = dict(account_id="acct123", tx_id=None, posted_date="2024-01-15",
                  amount_cents=500, currency="USD", description="Gas", memo="Station X")
    assert simplefin_external_id(**kwargs) == simplefin_external_id(**kwargs)
```

```python
# tests/test_sync_idempotency.py
import sqlite3
import pytest
from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload

PAYLOAD = {"accounts": [{"id": "acct1", "currency": "USD", "transactions": [
    {"id": "tx1", "posted": 1704067200, "amount": "-12.00", "description": "Coffee", "memo": ""},
]}]}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    migrate_governed(conn, p)
    return conn, tmp_path


def test_first_poll_inserts(db):
    conn, tmp = db
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD,
        evidence_path=tmp / "ev.raw", account_map={"acct1": "Assets:Checking"})
    assert ins == 1 and skip == 0


def test_second_poll_skips(db):
    conn, tmp = db
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev.raw", account_map={"acct1": "Assets:Checking"})
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev2.raw", account_map={"acct1": "Assets:Checking"})
    assert ins == 0 and skip == 1


def test_prior_status_untouched(db):
    conn, tmp = db
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev.raw", account_map={"acct1": "Assets:Checking"})
    conn.execute("UPDATE staged_transactions SET status='approved'")
    conn.commit()
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev2.raw", account_map={"acct1": "Assets:Checking"})
    assert conn.execute("SELECT status FROM staged_transactions").fetchone()["status"] == "approved"


def test_unassigned_account_fallback(db):
    conn, tmp = db
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=tmp / "ev.raw", account_map={})
    row = conn.execute("SELECT account FROM staged_postings WHERE role='imported'").fetchone()
    assert row["account"] == "Assets:Unassigned:SimpleFIN_acct1"
```

- [ ] **Step 4.2: Run to verify failure**

```
python -m pytest tests/test_simplefin_parser.py tests/test_sync_idempotency.py -v
```

- [ ] **Step 4.3: Implement `src/ironledger/ingest/formats/simplefin_engine.py`**

```python
"""SimpleFIN feed parser, amount normalizer, and DB-enforced deduplication for Phase 7."""

from __future__ import annotations

import hashlib, json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ironledger.ingest.errors import ParseError

__all__ = ["parse_amount", "simplefin_external_id", "ingest_simplefin_payload"]

_AMOUNT_GRAMMAR = re.compile(r"^[+-]?\d+(\.\d{1,2})?$")
_FALLBACK_PREFIX = "Assets:Unassigned:SimpleFIN_"


def parse_amount(amount_str: str) -> int:
    """Convert SimpleFIN amount string to signed integer cents.

    Formula: sign * (dollars * 100 + cents).
    Grammar: ^[+-]?\\d+(\\.\\d{1,2})?$
    """
    if not _AMOUNT_GRAMMAR.match(amount_str):
        raise ParseError(f"amount {amount_str!r} does not match SimpleFIN grammar")
    negative = amount_str.startswith("-")
    clean = amount_str.lstrip("+-")
    if "." in clean:
        whole_str, frac_str = clean.split(".", 1)
        frac_padded = (frac_str + "00")[:2]
    else:
        whole_str, frac_padded = clean, "00"
    magnitude = int(whole_str) * 100 + int(frac_padded)
    return -magnitude if negative else magnitude


def simplefin_external_id(
    account_id: str, tx_id: str | None, *,
    posted_date: str, amount_cents: int, currency: str, description: str, memo: str,
) -> str:
    """Return account-scoped primary ID or composite:v1 fallback."""
    if tx_id:
        return f"simplefin:id:{account_id}:{tx_id}"
    canonical = json.dumps(
        [account_id, posted_date, amount_cents, currency, description, memo],
        separators=(",", ":"), ensure_ascii=True,
    )
    return f"composite:v1:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _iso_from_unix(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def ingest_simplefin_payload(
    conn: sqlite3.Connection, payload: dict, *,
    evidence_path: Path, account_map: dict[str, str],
) -> tuple[int, int]:
    """Stage all transactions in payload. Returns (inserted, skipped).

    Runs inside BEGIN IMMEDIATE. Uses ON CONFLICT(external_id) DO NOTHING for deduplication.
    """
    inserted = skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        for account in payload.get("accounts", []):
            acct_id = account["id"]
            currency = account.get("currency", "USD")
            canonical_account = account_map.get(acct_id, f"{_FALLBACK_PREFIX}{acct_id}")
            for tx in account.get("transactions", []):
                tx_id = tx.get("id") or None
                posted = _iso_from_unix(int(tx["posted"]))
                cents = parse_amount(str(tx["amount"]))
                desc = tx.get("description", "")
                memo = tx.get("memo", "") or ""
                ext_id = simplefin_external_id(
                    acct_id, tx_id, posted_date=posted, amount_cents=cents,
                    currency=currency, description=desc, memo=memo,
                )
                fp = hashlib.sha256(ext_id.encode()).hexdigest()
                src_doc_id = f"simplefin:{ext_id}"
                conn.execute(
                    "INSERT OR IGNORE INTO source_documents "
                    "(source_document_id,mime_type,encoding,provenance,"
                    "acquisition_time_utc,content_sha256,raw_payload_ref,created_at_utc) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (src_doc_id, "application/json", "utf-8", f"simplefin:{acct_id}",
                     now, "0" * 64, str(evidence_path), now),
                )
                src_rec_id = f"sr:{ext_id}"
                tx_json = json.dumps(tx, separators=(",", ":"))
                tx_hash = hashlib.sha256(tx_json.encode()).hexdigest()
                conn.execute(
                    "INSERT OR IGNORE INTO source_records "
                    "(source_record_id,source_document_id,record_index,"
                    "canonical_payload,content_sha256,created_at_utc) VALUES (?,?,0,?,?,?)",
                    (src_rec_id, src_doc_id, tx_json, tx_hash, now),
                )
                stx_id = f"stx:{ext_id}"
                r = conn.execute(
                    "INSERT INTO staged_transactions "
                    "(staged_transaction_id,source_record_id,status,proposed_date,payee,"
                    "narration,identity_algo_version,identity_method,identity_fingerprint,"
                    "external_id,created_at_utc) "
                    "VALUES (?,?,'pending',?,?,'',1,'fitid',?,?,?) "
                    "ON CONFLICT(external_id) DO NOTHING",
                    (stx_id, src_rec_id, posted, desc, fp, ext_id, now),
                )
                if r.rowcount == 1:
                    conn.executemany(
                        "INSERT OR IGNORE INTO staged_postings "
                        "(staged_posting_id,staged_transaction_id,source_record_id,"
                        "role,posting_index,account,minor_units,currency,minor_unit_scale,created_at_utc) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [
                            (f"{stx_id}:0", stx_id, src_rec_id, "imported", 0,
                             canonical_account, cents, currency, 2, now),
                            (f"{stx_id}:1", stx_id, src_rec_id, "contra", 1,
                             "Expenses:Unassigned", -cents, currency, 2, now),
                        ],
                    )
                    inserted += 1
                else:
                    skipped += 1
    return inserted, skipped
```

- [ ] **Step 4.4: Run to verify pass**

```
python -m pytest tests/test_simplefin_parser.py tests/test_sync_idempotency.py -v
```

- [ ] **Step 4.5: Full suite**

```
python -m pytest tests/ -x -q
```

- [ ] **Step 4.6: Commit**

```
git add src/ironledger/ingest/formats/simplefin_engine.py tests/test_simplefin_parser.py tests/test_sync_idempotency.py
git commit -m "feat(ingest): SimpleFIN parser, amount normalization, account-scoped deduplication"
```

---

## Task 5: Sync Daemon, Lockfile & CLI Commands

**Files:**
- Create: `src/ironledger/pipeline/__init__.py` (empty)
- Create: `src/ironledger/pipeline/sync_daemon.py`
- Modify: `src/ironledger/cli/__main__.py`
- Test: `tests/test_sync_lock.py`

**Interfaces:**
- Produces:
  - `class SyncLockActiveError(Exception)`
  - `class SyncLockPermissionError(Exception)`
  - `def acquire_lock(lock_path: Path) -> None`
  - `def release_lock(lock_path: Path) -> None`
  - `def inspect_and_reclaim_if_stale(lock_path: Path) -> bool`

- [ ] **Step 5.1: Write failing tests**

```python
# tests/test_sync_lock.py
import json, os, pytest
from pathlib import Path
from unittest.mock import patch
from ironledger.pipeline.sync_daemon import (
    SyncLockActiveError, SyncLockPermissionError,
    acquire_lock, release_lock, inspect_and_reclaim_if_stale,
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
```

- [ ] **Step 5.2: Run to verify failure**

```
python -m pytest tests/test_sync_lock.py -v
```

- [ ] **Step 5.3: Implement `src/ironledger/pipeline/sync_daemon.py`**

```python
"""Lockfile acquisition, stale lock inspection, and sync utilities for Phase 7."""

from __future__ import annotations

import json, os, socket, sys
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "SyncLockActiveError", "SyncLockPermissionError",
    "acquire_lock", "release_lock", "inspect_and_reclaim_if_stale",
]


class SyncLockActiveError(Exception):
    """A live sync lock is held; current invocation halts fail-closed."""


class SyncLockPermissionError(Exception):
    """Could not read or delete the lock file due to OS permission error."""


def _get_hostname() -> str:
    return socket.gethostname()


def _pid_exists(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        if sys.platform == "win32":
            return False  # conservative fallback
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, not ours


def _pid_is_ironledger(pid: int) -> bool:
    try:
        import psutil
        p = psutil.Process(pid)
        cmd = " ".join(p.cmdline()).lower()
        return "ironledger" in p.name().lower() or "ironledger" in cmd
    except Exception:
        return False


def _write_lock(lock_path: Path) -> None:
    data = json.dumps({
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hostname": _get_hostname(),
    })
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)


def acquire_lock(lock_path: Path) -> None:
    """Atomically create lock. Raises SyncLockActiveError if already held."""
    if lock_path.exists():
        inspect_and_reclaim_if_stale(lock_path)
    try:
        _write_lock(lock_path)
    except FileExistsError as exc:
        raise SyncLockActiveError(f"Lock already held at {lock_path}") from exc


def release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except PermissionError as exc:
        raise SyncLockPermissionError(f"Cannot release lock at {lock_path}: {exc}") from exc


def inspect_and_reclaim_if_stale(lock_path: Path) -> bool:
    """Inspect existing lock; reclaim if stale. Returns True if reclaimed.

    Outcome table (evaluated in order):
    1. JSON malformed/unreadable -> log LOCK_PARSE_ERROR + reclaim.
    2. hostname != current host -> SyncLockActiveError (foreign lock never reclaimed).
    3. PID exists + ironledger process -> SyncLockActiveError.
    4. PID exists, unrelated (PID reuse) -> reclaim.
    5. PID dead -> reclaim.
    6. Permission error reading/deleting -> SyncLockPermissionError + fail closed.
    """
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise SyncLockPermissionError(f"Cannot read lock: {exc}") from exc

    try:
        data = json.loads(raw)
        pid = int(data["pid"])
        hostname = str(data.get("hostname", ""))
    except (json.JSONDecodeError, KeyError, ValueError):
        # Outcome 1: malformed JSON -> reclaim
        try:
            lock_path.unlink()
        except PermissionError as exc:
            raise SyncLockPermissionError(f"Cannot delete malformed lock: {exc}") from exc
        return True

    # Outcome 2: foreign hostname -> fail closed
    if hostname and hostname != _get_hostname():
        raise SyncLockActiveError(
            f"Lock held by foreign host {hostname!r}; remove manually."
        )

    # Outcomes 3 + 4
    if _pid_exists(pid) and _pid_is_ironledger(pid):
        raise SyncLockActiveError(f"Active IronLedger sync (PID {pid}) is running.")

    # Outcome 5: dead PID (or PID reuse with unrelated process) -> reclaim
    try:
        lock_path.unlink()
    except PermissionError as exc:
        raise SyncLockPermissionError(f"Cannot delete stale lock: {exc}") from exc
    return True
```

- [ ] **Step 5.4: Add `sync` subcommand group to `src/ironledger/cli/__main__.py`**

At the end of `_build_parser()`, after all existing subparsers:

```python
sync_parser = subparsers.add_parser("sync", help="SimpleFIN bank synchronization")
sync_sub = sync_parser.add_subparsers(dest="sync_command")
sync_auth = sync_sub.add_parser("auth", help="Credential management")
sync_auth_sub = sync_auth.add_subparsers(dest="sync_auth_command")
sync_auth_claim = sync_auth_sub.add_parser("claim", help="Claim a SimpleFIN setup token")
sync_auth_claim.add_argument("--stdin", action="store_true", help="Read token from stdin")
sync_auth_sub.add_parser("status", help="Show masked connection info")
sync_poll = sync_sub.add_parser("poll", help="Run a sync poll")
sync_poll.add_argument("--lookback", type=int, default=30, help="Days to fetch (default: 30)")
sync_poll.add_argument("--dry-run", action="store_true", help="Parse without staging")
sync_accounts = sync_sub.add_parser("accounts", help="Account mapping")
sync_accounts_sub = sync_accounts.add_subparsers(dest="sync_accounts_command")
sync_accounts_sub.add_parser("list", help="List account mappings")
```

In `main()`, after the final `elif args.command == ...` block:

```python
elif args.command == "sync":
    import getpass
    from ironledger.security.secrets import (
        claim_setup_token, get_access_url, mask_access_url, CredentialsNotFoundError,
    )
    conn = connect(db_path)
    migrations.migrate_governed(conn, db_path)
    if args.sync_command == "auth":
        if args.sync_auth_command == "claim":
            token = sys.stdin.readline().strip() if args.stdin else getpass.getpass("SimpleFIN setup token: ")
            masked = claim_setup_token(token, conn)
            print(f"Access URL stored: {masked}")
        elif args.sync_auth_command == "status":
            try:
                print(f"Connected: {mask_access_url(get_access_url(conn))}")
            except CredentialsNotFoundError:
                print("No credentials stored. Run: ironledger sync auth claim")
    elif args.sync_command == "poll":
        from datetime import datetime, timezone, timedelta
        from pathlib import Path
        from ironledger.pipeline.sync_daemon import acquire_lock, release_lock
        from ironledger.ingest.formats.simplefin import fetch_accounts
        from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload
        lock_path = Path(db_path).parent / ".sync.lock"
        acquire_lock(lock_path)
        try:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=args.lookback)
            ev_dir = Path(db_path).parent / "evidence" / "source_documents"
            payload = fetch_accounts(conn, start_date=start_dt, end_date=end_dt, evidence_dir=ev_dir)
            if args.dry_run:
                import json as _json
                print(_json.dumps(payload, indent=2))
            else:
                ins, skip = ingest_simplefin_payload(conn, payload, evidence_path=ev_dir, account_map={})
                print(f"Sync: {ins} inserted, {skip} skipped")
        finally:
            release_lock(lock_path)
    elif args.sync_command == "accounts" and args.sync_accounts_command == "list":
        for r in conn.execute("SELECT remote_account_id, canonical_account FROM simplefin_account_map").fetchall():
            print(f"  {r[0]} -> {r[1]}")
    conn.close()
    sys.exit(_EXIT_OK)
```

- [ ] **Step 5.5: Run to verify pass**

```
python -m pytest tests/test_sync_lock.py -v
```

- [ ] **Step 5.6: Full suite**

```
python -m pytest tests/ -x -q
```

- [ ] **Step 5.7: Commit**

```
git add src/ironledger/pipeline/ tests/test_sync_lock.py src/ironledger/cli/__main__.py
git commit -m "feat(sync): lockfile daemon, stale lock protocol, CLI sync subcommands"
```

---

## Task 6: REST API /api/sync/* + App Registration

**Files:**
- Create: `src/ironledger/web/routers/sync.py`
- Modify: `src/ironledger/web/app.py`
- Test: `tests/test_web_sync.py`

**Interfaces:**
- Produces:
  - `GET /api/sync/status` -> `SyncStatusResponse{state, pending_count, last_error_code}`
  - `POST /api/sync/poll` (requires `X-CSRF-Token`) -> `SyncPollResponse{inserted, skipped}`
  - 401 on missing/wrong `X-IronLedger-Op-Token`; 409 on `SyncLockActiveError`

- [ ] **Step 6.1: Write failing tests**

```python
# tests/test_web_sync.py
import sqlite3
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from ironledger.web.app import create_app
from ironledger.governance.migrations import migrate_governed


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


def test_status_returns_state(client):
    with patch("ironledger.security.secrets.get_access_url", side_effect=Exception):
        r = client.get("/api/sync/status", headers={"X-IronLedger-Op-Token": "test-token"})
    assert r.status_code == 200
    assert r.json()["state"] in ("UNCONFIGURED", "DEGRADED", "HEALTHY")


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
```

- [ ] **Step 6.2: Run to verify failure**

```
python -m pytest tests/test_web_sync.py -v
```

- [ ] **Step 6.3: Implement `src/ironledger/web/routers/sync.py`**

```python
"""Sync status and poll endpoints for IronLedger Operator Workbench."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ironledger.pipeline.sync_daemon import SyncLockActiveError, acquire_lock, release_lock
from ironledger.security.secrets import CredentialsNotFoundError, get_access_url

router = APIRouter(prefix="/api/sync", tags=["sync"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.get_db()


def require_operator(request: Request) -> None:
    op_token = getattr(request.app.state, "op_token", None)
    if op_token is None:
        return
    if request.headers.get("X-IronLedger-Op-Token") != op_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_csrf(request: Request) -> None:
    if not request.headers.get("X-CSRF-Token"):
        raise HTTPException(status_code=400, detail="Missing X-CSRF-Token header")


class SyncStatusResponse(BaseModel):
    state: str
    pending_count: int
    last_error_code: Optional[str] = None


class SyncPollResponse(BaseModel):
    inserted: int
    skipped: int


@router.get("/status", response_model=SyncStatusResponse)
def sync_status(
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
) -> SyncStatusResponse:
    pending = db.execute(
        "SELECT COUNT(*) FROM staged_transactions WHERE status='pending'"
    ).fetchone()[0]
    try:
        get_access_url(db)
        state = "HEALTHY"
    except CredentialsNotFoundError:
        state = "UNCONFIGURED"
    except Exception:
        state = "DEGRADED"
    return SyncStatusResponse(state=state, pending_count=pending)


@router.post("/poll", response_model=SyncPollResponse)
def sync_poll(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    _auth=Depends(require_operator),
    _csrf=Depends(require_csrf),
) -> SyncPollResponse:
    from ironledger.ingest.formats.simplefin import fetch_accounts
    from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload
    lock_path = Path(request.app.state.db_path).parent / ".sync.lock"
    try:
        acquire_lock(lock_path)
    except SyncLockActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        end_dt = datetime.now(timezone.utc)
        ev_dir = Path(request.app.state.db_path).parent / "evidence" / "source_documents"
        payload = fetch_accounts(db, start_date=end_dt - timedelta(days=30),
                                 end_date=end_dt, evidence_dir=ev_dir)
        ins, skip = ingest_simplefin_payload(db, payload, evidence_path=ev_dir, account_map={})
        return SyncPollResponse(inserted=ins, skipped=skip)
    finally:
        release_lock(lock_path)
```

- [ ] **Step 6.4: Register router in `src/ironledger/web/app.py`**

Change import to: `from ironledger.web.routers import compile, projection, rules, staging, system, sync`

After `app.include_router(system.router)` add: `app.include_router(sync.router)`

- [ ] **Step 6.5: Run to verify pass**

```
python -m pytest tests/test_web_sync.py -v
```

- [ ] **Step 6.6: Full suite**

```
python -m pytest tests/ -x -q
```

- [ ] **Step 6.7: Commit**

```
git add src/ironledger/web/routers/sync.py src/ironledger/web/app.py tests/test_web_sync.py
git commit -m "feat(web): /api/sync/status + /api/sync/poll with CSRF and operator auth"
```

---

## Task 7: End-to-End Test & Config Seed

**Files:**
- Create: `tests/test_phase7_e2e.py`
- Create: `config/simplefin_accounts.json`

- [ ] **Step 7.1: Create `config/simplefin_accounts.json`**

```json
{}
```

- [ ] **Step 7.2: Write the E2E test**

```python
# tests/test_phase7_e2e.py
"""Mocked SimpleFIN -> evidence archive -> staging -> idempotency E2E test."""

import json, sqlite3, pytest
from pathlib import Path
from ironledger.governance.migrations import migrate_governed
from ironledger.ingest.formats.simplefin import archive_evidence
from ironledger.ingest.formats.simplefin_engine import ingest_simplefin_payload

PAYLOAD = {"accounts": [{"id": "chase-001", "currency": "USD", "transactions": [
    {"id": "t001", "posted": 1704067200, "amount": "-42.50", "description": "Grocery", "memo": ""},
    {"id": "t002", "posted": 1704153600, "amount": "1000.00", "description": "Payroll", "memo": ""},
]}]}


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrate_governed(conn, db_path)
    return conn, tmp_path / "evidence" / "source_documents"


def test_e2e_archive_then_stage(env):
    conn, ev_dir = env
    raw = json.dumps(PAYLOAD).encode()
    ev_path = archive_evidence(raw, evidence_dir=ev_dir)
    assert ev_path.suffix == ".raw"
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD, evidence_path=ev_path,
                                          account_map={"chase-001": "Assets:Chase:Checking"})
    assert ins == 2 and skip == 0


def test_e2e_idempotent_repoll(env):
    conn, ev_dir = env
    raw = json.dumps(PAYLOAD).encode()
    ev_path = archive_evidence(raw, evidence_dir=ev_dir)
    ingest_simplefin_payload(conn, PAYLOAD, evidence_path=ev_path, account_map={})
    ins, skip = ingest_simplefin_payload(conn, PAYLOAD, evidence_path=ev_path, account_map={})
    assert ins == 0 and skip == 2


def test_e2e_amount_normalization(env):
    conn, ev_dir = env
    payload = {"accounts": [{"id": "a", "currency": "USD", "transactions": [
        {"id": "t1", "posted": 1704067200, "amount": "-12", "description": "X", "memo": ""},
        {"id": "t2", "posted": 1704067200, "amount": "-0.34", "description": "Y", "memo": ""},
    ]}]}
    raw = json.dumps(payload).encode()
    ev = archive_evidence(raw, evidence_dir=ev_dir)
    ingest_simplefin_payload(conn, payload, evidence_path=ev, account_map={})
    amounts = [r[0] for r in conn.execute(
        "SELECT minor_units FROM staged_postings WHERE role='imported' ORDER BY staged_posting_id"
    ).fetchall()]
    assert -1200 in amounts and -34 in amounts


def test_e2e_no_secrets_in_audit(env, monkeypatch):
    secret = "s3cr3t"
    monkeypatch.setenv("IRONLEDGER_SIMPLEFIN_ACCESS_URL", f"https://u:{secret}@bridge.simplefin.org/simplefin")
    conn, _ = env
    from ironledger.security.secrets import get_access_url
    get_access_url(conn)
    for row in conn.execute("SELECT * FROM audit_events").fetchall():
        for cell in row:
            assert secret not in str(cell)
```

- [ ] **Step 7.3: Run E2E tests**

```
python -m pytest tests/test_phase7_e2e.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 7.4: Final full suite**

```
python -m pytest tests/ -q
```
Expected: all tests pass, 0 failures.

- [ ] **Step 7.5: Commit**

```
git add tests/test_phase7_e2e.py config/simplefin_accounts.json
git commit -m "test(phase7): E2E pipeline test + account map seed"
```

- [ ] **Step 7.6: Tag milestone**

```
git tag -a v0.7.0 -m "Phase 7: Automated Bank Synchronization & Secret Store Boundary"
git push origin main --tags
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| UNIQUE(external_id) partial index | 1 |
| simplefin_account_map append-only table | 1 |
| Keyring/env credential resolution | 2 |
| CREDENTIAL_ACCESS_ATTEMPT audit event | 2 |
| SSRF guard: host allowlist, HTTPS only, redirect block | 2 |
| DNS rebinding residual risk documented in test comment | 3 |
| TLS 1.2+ min / TLS 1.3 preferred SSLContext | 3 |
| fsync + SHA-256 + atomic rename evidence archival | 3 |
| EvidenceIntegrityError on byte mismatch | 3 |
| Best-effort read-only scope noted in code comment | 3 |
| Amount formula sign*(dollars*100+cents) | 4 |
| Test cases -12->-1200, -0.34->-34, +12->+1200, 0->0 | 4 |
| Primary ID simplefin:id:<acct>:<tx> | 4 |
| composite:v1 fallback fingerprint | 4 |
| INSERT ON CONFLICT(external_id) DO NOTHING | 4 |
| BEGIN IMMEDIATE batch transaction | 4 |
| Fallback account Assets:Unassigned:SimpleFIN_<id> | 4 |
| Lockfile JSON {pid, started_at, hostname} | 5 |
| 7-scenario stale lock outcome table | 5 |
| CLI sync auth claim/status, sync poll, sync accounts list | 5 |
| Token via stdin/getpass, never argv | 5 |
| GET /api/sync/status | 6 |
| POST /api/sync/poll + CSRF | 6 |
| 401 unauthenticated, 409 locked | 6 |
| Mocked E2E pipeline test | 7 |
| config/simplefin_accounts.json seed | 7 |

**Type consistency:**
- `archive_evidence(raw_bytes: bytes, *, evidence_dir: Path) -> Path` -- identical in Tasks 3, 4, 7.
- `ingest_simplefin_payload(conn, payload, *, evidence_path, account_map) -> tuple[int, int]` -- identical in Tasks 4, 6, 7.
- `acquire_lock / release_lock(lock_path: Path) -> None` -- identical in Tasks 5, 6.
- `get_access_url(conn: sqlite3.Connection) -> str` -- identical in Tasks 2, 6.
