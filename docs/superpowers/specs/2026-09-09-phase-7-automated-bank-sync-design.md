# Phase 7 Specification & Technical Design: Automated Bank Synchronization & Secret Store Boundary

**Program:** IronLedger  
**Milestone:** Phase 7 -- Automated Bank Synchronization, Aggregator Polling & Secret Security  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-09  
**Status:** Hardened Specification (Findings 1-12 Resolved)  

---

## 1. Executive Summary & Architectural Mission

Phase 7 integrates network-delivered bank statement synchronization (starting with the SimpleFIN Bridge REST aggregator protocol) directly into IronLedger's immutable staging buffer while isolating network access, credentials, and evidence archives.

### Invariant Guardrails

1. **Plaintext Accounting Authority:** Polled network feeds NEVER mutate `main.beancount` directly. Polled items enter `staged_transactions` with status `PENDING`.
2. **Zero-Float Currency Coercion:** All aggregator decimal representations are transformed to signed integer minor units (cents) via deterministic arithmetic and strict grammar validation.
3. **Hermetic Raw Evidence Integrity:** Exact wire bytes from raw HTTP responses are written to a temp file, flushed and fsynced, verified via SHA-256, and atomically renamed to `evidence/source_documents/<file_sha256>.raw`. Read-only permissions are enforced on Windows via `SetFileAttributesW(FILE_ATTRIBUTE_READONLY)` and POSIX `0o444`.
4. **Isolated Credential Boundary & Safe Ingestion:** Setup tokens are never passed via CLI process arguments (passed via stdin/prompt). Access URLs/passwords are never logged, never stored in SQLite, and held in bounded-lifetime memory accessors.
5. **SSRF Guard & TLS 1.3 Enforcement:** Setup token claim endpoints and aggregator endpoints are restricted to explicit host allowlists (`bridge.simplefin.org`, `beta-bridge.simplefin.org`), must be HTTPS, prohibit private/loopback IP ranges, and disable HTTP redirects. TLS uses explicit `SSLContext` requiring TLS 1.3 or TLS 1.2 minimum with strict cert/hostname validation.
6. **Fail-Closed Execution & Idempotency:** Overlapping poll intervals use account-scoped identity fingerprinting (`simplefin:id:<account_id>:<tx_id>`) backed by a SQLite UNIQUE constraint (`UNIQUE(external_id)`) with `INSERT ... ON CONFLICT DO NOTHING`. Polling while an active lock exists halts immediately.

---

## 2. Architecture & Data Flow

```
+------------------------------------------------------------------------+
|             EXTERNAL NETWORK (OUTBOUND - HTTPS / TLS 1.3)              |
|  SimpleFIN Bridge REST API (Strict Allowlist: bridge.simplefin.org)    |
+-----------------------------------+------------------------------------+
                                    | No-Redirect / TLS 1.3 Context
                                    v
+------------------------------------------------------------------------+
|                TASK 7.1 / 7.2: SECURE AGGREGATOR INGESTION             |
|  [SecretStore] ---> [SimpleFINPoller] ---> [Hermetic Raw Evidence]     |
|  (Keyring / Stdin)  (Masked Auth Header)   (Atomic temp->fsync->rename)|
+-----------------------------------+------------------------------------+
                                    |
                                    v
+------------------------------------------------------------------------+
|             TASK 7.3: STAGING ENGINE & DETERMINISTIC DEDUPE            |
|  Scoped Fingerprint v1 ---> staged_transactions (PENDING)              |
|  (Account-Scoped FITID /    (DB UNIQUE constraint ON CONFLICT IGNORE)  |
|   Canonical JSON Fallback)                                             |
+-----------------------------------+------------------------------------+
                                    |
          +-------------------------+-------------------------+
          v                                                   v
+-------------------------------+   +-----------------------------------+
|     TASK 7.4: SCHEDULER       |   |    TASK 7.5: WORKBENCH HUD / SYNC |
| * cron / Task Scheduler daemon|   | * Auth/CSRF Protected Endpoints   |
| * Lockfile (PID + Stale check)|   | * Manual Trigger / Status Widget  |
| * Safe-Mode Mutation Isolation|   | * Safe Redacted Diagnostics       |
+-------------------------------+   +-----------------------------------+
```

---

## 3. Subsystem Detailed Specifications

### Task 7.1: Native Secret Store Bridge & SSRF Protection
- **Target Module:** `src/ironledger/security/secrets.py`
- **Keyring Namespace:** Service `ironledger`, username `simplefin_access_url`.
- **SSRF Boundary & Setup Token Claim:**
  1. Operator provides setup token through `stdin` or interactive prompt (`getpass`), never command-line arguments.
  2. Setup token base64-decoded into claim URL. Claim URL parsed and validated:
     - Scheme must be `https`.
     - Host must match allowlist: `bridge.simplefin.org` or `beta-bridge.simplefin.org`.
     - Resolved IP must not be private/loopback/link-local (`ipaddress.is_private`, `is_loopback`, `is_link_local`, `is_reserved`).
     - HTTP redirects disabled (`urllib.request.HTTPRedirectHandler` overridden to raise on 3xx).
  3. POST request dispatched; response parsed to extract Access URL (`https://<username>:<password>@bridge.simplefin.org/simplefin`).
  4. Access URL credentials parsed once into isolated username/password pair and stored in host keyring (`keyring.set_password('ironledger', 'simplefin_access_url', access_url)`).
  5. Masking utility `mask_access_url(url)` ensures all logs, errors, exceptions, and audit events render as `https://***:***@bridge.simplefin.org/simplefin`.
- **Bounded In-Memory Lifetime:** Secrets are read on demand and kept in ephemeral local variables; mutable byte arrays are zeroed where possible; exceptions never encapsulate raw secret strings.
- **Resolution Priority:**
  1. `IRONLEDGER_SIMPLEFIN_ACCESS_URL` (Environment Variable)
  2. OS Keyring (`keyring.get_password('ironledger', 'simplefin_access_url')`)
  3. If missing: raise audited `CredentialsNotFoundError`.

### Task 7.2: SimpleFIN Bridge Client Engine & Raw Evidence Archiving
- **Target Module:** `src/ironledger/ingest/simplefin.py`
- **Transport & TLS Policy:**
  - Standard library `urllib.request` using an explicit `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`.
  - Enforce `context.minimum_version = ssl.TLSVersion.TLSv1_2` (negotiating TLS 1.3 when supported by server).
  - Explicit `context.verify_mode = ssl.CERT_REQUIRED`, `context.check_hostname = True`.
  - HTTP `Authorization: Basic <base64(user:pass)>` header constructed directly without embedding user:pass in the target URL string.
- **Date Range Query:** `GET https://bridge.simplefin.org/simplefin/accounts?start-date=<unix_utc>&end-date=<unix_utc>` with timestamps strictly as UTC integers (`int(datetime.now(timezone.utc).timestamp())`).
- **Hermetic Raw Evidence Archival Protocol:**
  1. Read exact wire bytes into memory.
  2. Calculate `file_sha256 = hashlib.sha256(raw_bytes).hexdigest()`.
  3. Write bytes to temporary file `evidence/source_documents/<file_sha256>.tmp`.
  4. Flush and `os.fsync(f.fileno())` to guarantee physical disk persistence.
  5. Check if target `evidence/source_documents/<file_sha256>.raw` exists:
     - If exists, verify exact byte equality. If hash matches but bytes mismatch (corruption), raise `EvidenceIntegrityError`. If identical, unlink tmp file (idempotent).
     - If not exists, atomically rename `.tmp` to `.raw` (`os.replace`).
  6. Apply read-only attributes: Windows `win32api.SetFileAttributes` / `ctypes` (`FILE_ATTRIBUTE_READONLY = 0x01`); POSIX `os.chmod(0o444)`.
  7. Emit append-only audit event `EVIDENCE_ARCHIVED` with raw wire hash and byte count before database staging begins.

### Task 7.3: Feed Parsing, Grammar Normalization & DB-Enforced Deduplication
- **Target Module:** `src/ironledger/ingest/parsers/simplefin_engine.py`
- **Account Mapping:** Config-driven via `config/simplefin_accounts.json` with fallback to `Assets:Unassigned:SimpleFIN_<account_id>`.
- **Strict Amount Normalization & Grammar:**
  - Input grammar: `^[+-]?\d+(\.\d{1,2})?$` (rejects spaces, thousands commas, exponent notations, >2 decimal places).
  - Explicit sign extraction (`-1` if leading `-` else `+1`).
  - Integer dollars and padded cents calculation: `dollars * 100 + cents * sign`. Zero floats.
- **Account-Scoped Identity Fingerprinting (v1 Algorithm):**
  - Primary Identity: `simplefin:id:<account_id>:<tx_id>` when `tx_id` is present.
  - Composite Fallback: `composite:v1:<sha256(canonical_json([account_id, posted_date, amount_cents, currency, description, memo]))>` ensuring zero delimiter collision and currency isolation.
- **Database-Level Uniqueness Invariant:**
  - `staged_transactions` schema contains `UNIQUE(external_id)`.
  - Ingestion executes `INSERT INTO staged_transactions (...) VALUES (...) ON CONFLICT(external_id) DO NOTHING`.
  - `BEGIN IMMEDIATE` transaction wraps batch insertion and `statement_imports` registration. Existing rows with statuses `APPROVED`, `REJECTED`, or `PENDING` remain untouched.

### Task 7.4: Headless Synchronization Daemon & Stale Lock Protocol
- **Target Modules:** `src/ironledger/cli/sync.py`, `src/ironledger/pipeline/sync_daemon.py`
- **Lockfile Contract (`.sync.lock`):**
  - Lock content: JSON `{"pid": <pid>, "started_at": "<iso8601_utc>", "hostname": "<host>"}`.
  - Acquisition: Exclusive atomic file creation (`os.open(..., os.O_CREAT | os.O_EXCL | os.O_WRONLY)`).
  - Stale Lock Inspection: If file exists, parse PID and started_at timestamp:
    - Check PID liveness (`psutil.pid_exists(pid)` or `os.kill(pid, 0)`).
    - If PID is dead, or if age > 30 minutes with dead process, safely reclaim and log `STALE_LOCK_RECLAIMED`.
    - If PID is active and running IronLedger sync, fail closed with `SyncLockActiveError`.
- **CLI Commands (Zero Secret Leakage):**
  - `ironledger sync auth claim` (Prompts interactively or reads from stdin `--stdin`).
  - `ironledger sync auth status` (Outputs masked connection info and token validity).
  - `ironledger sync poll [--lookback <days>] [--dry-run]`
  - `ironledger sync accounts [list | map <remote_id> <canonical_account>]`

### Task 7.5: Operator Workbench Sync Integration & Protected REST API
- **Target Modules:** `src/ironledger/web/routers/sync.py`, `web/src/components/TopHUD.tsx`
- **Authentication & Authorization Policy:**
  - All `/api/sync/*` endpoints require authenticated operator session (`Depends(get_current_operator)`).
  - State-mutating `POST /api/sync/poll` requires valid CSRF header token.
  - Unauthenticated requests return `401 Unauthorized` with zero diagnostic metadata leakage.
- **REST API Endpoints:**
  - `GET /api/sync/status` -> Redacted sync latency, connection state (`HEALTHY`/`DEGRADED`/`EXPIRED`), total pending items, last error code (masked).
  - `POST /api/sync/poll` -> Trigger manual synchronization run (returns `409 Conflict` if locked).
- **UI Integration:**
  - Top HUD status indicator badge with active sync status, latency warning (>24h), and 'Sync Now' action.

### Task 7.6: Acceptance Test Suite & Ratification Evidence
- **Target Modules:** `tests/test_secrets.py`, `tests/test_simplefin_parser.py`, `tests/test_sync_idempotency.py`, `tests/test_sync_lock.py`, `tests/test_sync_security.py`, `tests/test_phase7_e2e.py`
- **Exit Criteria & Assertions:**
  - Re-polling identical payloads yields 0 new rows and retains prior staging statuses.
  - Corrupted network streams abort cleanly with atomic rollback.
  - Secret access attempts are captured in the cryptographic mutation and audit chain.
  - No secret tokens or passwords appear in logs, error objects, exceptions, or SQLite.
  - SSRF test verifies rejection of private IPs, HTTP schemes, and invalid hosts.
  - Windows file read-only attribute test asserts writes to `.raw` fail with `PermissionError`.

---

## 4. Phase 7 Acceptance Test Matrix

| Suite | Target Focus | Asserted Invariant Contract |
|---|---|---|
| `tests/test_secrets.py` | `secrets.py` | Tokens stored in keyring; stdin/prompt ingestion; masking verified; memory minimized. |
| `tests/test_sync_security.py` | `simplefin.py` | SSRF private IP rejection; HTTPS enforce; redirect blocking; TLS 1.3 SSLContext verification. |
| `tests/test_simplefin_parser.py` | `simplefin_engine.py` | Zero-float parsing across strict grammar; account-scoped identity `simplefin:id:<account_id>:<tx_id>`; currency in composite fallback. |
| `tests/test_sync_idempotency.py` | `simplefin.py` / DB | SQLite `UNIQUE(external_id)` + `ON CONFLICT DO NOTHING`; re-polling yields 0 duplicate rows. |
| `tests/test_sync_lock.py` | `sync_daemon.py` | Concurrent invocations fail-closed; dead PID / stale lock (>30m) reclaimed safely. |
| `tests/test_evidence_archive.py` | `evidence.py` | Wire-byte hashing, atomic temp-to-fsync-to-rename, Windows `FILE_ATTRIBUTE_READONLY` write-protection. |
| `tests/test_phase7_e2e.py` | Complete E2E | Mocked SimpleFIN server -> payload archive -> staging -> review -> compilation pipeline. |

