# Phase 7 Specification & Technical Design: Automated Bank Synchronization & Secret Store Boundary

**Program:** IronLedger
**Milestone:** Phase 7 -- Automated Bank Synchronization, Aggregator Polling & Secret Security
**Governed Repo:** C:\dev\IronLedger
**Governed Docs:** C:\dev\docs\meta\
**Date:** 2026-09-09
**Status:** Approved for Implementation Planning

---

## 1. Executive Summary & Architectural Mission

Phase 7 integrates network-delivered bank statement synchronization (starting with the SimpleFIN Bridge REST aggregator protocol) directly into IronLedger staging buffer while isolating network access, credentials, and evidence archives.

### Invariant Guardrails

1. **Plaintext Accounting Authority:** Polled network feeds NEVER mutate main.beancount directly. Polled items enter staged_transactions with status PENDING.
2. **Zero-Float Currency Coercion:** All aggregator decimal representations are transformed to signed integer minor units (cents) via deterministic arithmetic.
3. **Hermetic Raw Evidence Archive:** Every polled raw JSON feed payload is hashed and permanently archived under evidence/source_documents/<file_sha256>.raw with read-only permissions (0o444).
4. **Isolated Credential Boundary:** SimpleFIN access URLs and setup tokens are never stored in plaintext configuration files or committed to Git. They reside exclusively in the host-native secure keyring (Windows Credential Manager / DPAPI / SecretService) or ephemeral environment variables.
5. **Fail-Closed Execution & Idempotency:** Overlapping poll intervals use two-tier identity fingerprinting to achieve identical deduplication with 0 duplicate staging rows. Polling while an unapplied lock exists halts immediately.

---

## 2. Architecture & Data Flow

```
+------------------------------------------------------------------------+
|                        EXTERNAL NETWORK (OUTBOUND)                     |
|  SimpleFIN Bridge REST API (Read-Only Transacted Feeds)                |
+-----------------------------------+------------------------------------+
                                    | TLS 1.3 / Basic Auth
                                    v
+------------------------------------------------------------------------+
|                TASK 7.1 / 7.2: SECURE AGGREGATOR INGESTION             |
|  [SecretStore] ---> [SimpleFINPoller] ---> raw_evidence archive        |
|  (Isolated Keyring/DPAPI)                evidence/source_documents/    |
+-----------------------------------+------------------------------------+
                                    |
                                    v
+------------------------------------------------------------------------+
|             TASK 7.3: STAGING ENGINE & DETERMINISTIC DEDUPE            |
|  Canonical Identity v1 ---> staged_transactions (PENDING)              |
|  (FITID / SHA-256 Composite Fallback)                                  |
+-----------------------------------+------------------------------------+
                                    |
          +-------------------------+-------------------------+
          v                                                   v
+-------------------------------+   +-----------------------------------+
|     TASK 7.4: SCHEDULER       |   |    TASK 7.5: WORKBENCH HUD / SYNC |
| * cron / Task Scheduler daemon|   | * Manual Trigger / Status Widget  |
| * Lockfile acquisition        |   | * Sync Latency & Token Expiry     |
| * Non-zero exit code on drift |   | * Safe-Mode Mutation Isolation    |
+-------------------------------+   +-----------------------------------+
```

---

## 3. Subsystem Detailed Specifications

### Task 7.1: Native Secret Store Bridge
- **Target Module:** src/ironledger/security/secrets.py
- **Keyring Namespace:** Service ironledger, username simplefin_access_url.
- **Token Claim Workflow:**
  1. Operator provides a SimpleFIN Setup Token (base64-encoded URL containing claim endpoint).
  2. SecretStore.claim_setup_token(token) decodes the URL, makes a single POST request, and receives the persistent Access URL (https://<username>:<password>@bridge.simplefin.org/simplefin).
  3. The Access URL is stored in host keyring.
  4. URL credentials are never written to unencrypted logs or SQLite tables. Masking helper formats URL as https://***:***@bridge.simplefin.org/simplefin.
- **Resolution Priority:**
  1. IRONLEDGER_SIMPLEFIN_ACCESS_URL (Environment Variable)
  2. OS Keyring (keyring.get_password('ironledger', 'simplefin_access_url'))
  3. If missing: raise audited CredentialsNotFoundError.

### Task 7.2: SimpleFIN Bridge Client Engine & Raw Evidence Archiving
- **Target Module:** src/ironledger/ingest/simplefin.py
- **Transport:** Standard library HTTP Basic Authentication client parsed from stored Access URL. Zero third-party network libraries.
- **Date Range Query:** GET <access_url>/accounts?start-date=<unix_timestamp>&end-date=<unix_timestamp> with timestamps calculated strictly as UTC integers (`int(datetime.now(timezone.utc).timestamp())`).
- **Evidence Archival:**
  - Raw HTTP response payload (JSON bytes) is computed with SHA-256 immediately upon receipt.
  - Stored under evidence/source_documents/<file_sha256>.raw with permissions 0o444.
  - If the file already exists, storage is idempotent.
  - Audit trail emits EVIDENCE_ARCHIVED event with file hash, byte count, and source metadata simplefin_rest_poll.

### Task 7.3: Feed Parsing, Account Routing & Deterministic Deduplication
- **Target Module:** src/ironledger/ingest/parsers/simplefin_engine.py
- **Account Mapping:** Config-driven via config/simplefin_accounts.json with fallback to Assets:Unassigned:SimpleFIN_<account_id>.
- **Zero-Float Currency Coercion:** Uses StatementNormalizer.parse_amount_to_cents(amount_str) with deterministic string splitting.
- **Identity Fingerprinting (v1 Algorithm):**
  - Primary Identity: simplefin:id:<tx_id> when id is present.
  - Composite Fallback: composite:v1:<sha256(canonical_json([account_id, posted_date, amount_cents, description, memo]))> to guarantee zero delimiter collision.
- **Atomic Staging:**
  - BEGIN IMMEDIATE transaction block.
  - Inserts into statement_imports (source simplefin, raw evidence hash).
  - Inserts into staged_transactions with status PENDING.
  - Duplicate identity fingerprints are safely ignored, preserving prior status (APPROVED, REJECTED, PENDING).

### Task 7.4: Headless Synchronization Daemon & CLI Command Tree
- **Target Modules:** src/ironledger/cli/sync.py, src/ironledger/pipeline/sync_daemon.py
- **Lockfile Protocol:** .sync.lock containing JSON payload {"pid": <pid>, "started_at": "<iso8601_utc>"} acquired using atomic exclusive file creation. If lock exists, inspect PID liveness and stale age (>30m); if active, fail closed with non-zero exit code (SyncLockActiveError).
- **CLI Commands:**
  - ironledger sync auth claim <setup_token>
  - ironledger sync auth status
  - ironledger sync poll [--lookback <days>] [--dry-run]
  - ironledger sync accounts [list | map <remote_id> <canonical_account>]

### Task 7.5: Operator Workbench Sync Integration & Top HUD Status
- **Target Modules:** src/ironledger/web/routers/sync.py, web/src/components/TopHUD.tsx
- **REST API Endpoints:**
  - GET /api/sync/status -> Sync latency, connection health, total pending items, token status.
  - POST /api/sync/poll -> Trigger manual synchronization run (409 Conflict if locked).
- **UI Integration:**
  - Top HUD status indicator badge with active status and Sync Now button.

### Task 7.6: Acceptance Test Suite & Ratification Evidence
- **Target Modules:** tests/test_secrets.py, tests/test_simplefin_parser.py, tests/test_sync_idempotency.py, tests/test_sync_lock.py, tests/test_phase7_e2e.py
- **Exit Criteria:**
  - Re-polling identical payloads yields 0 new rows and retains prior staging statuses.
  - Corrupted network streams abort cleanly with atomic rollback.
  - Secret access attempts are captured in the cryptographic mutation and audit chain.

---

## 4. Phase 7 Acceptance Test Matrix

| Suite | Target Focus | Asserted Invariant Contract |
|---|---|---|
| tests/test_secrets.py | secrets.py | Access tokens stored securely; memory cleared post-execution; env-fallback validated. |
| tests/test_simplefin_parser.py | simplefin_engine.py | Zero-float parsing across positive/negative amounts; missing fields handled; ISO-8601 normalization. |
| tests/test_sync_idempotency.py | simplefin.py | Re-fetching same date range causes zero duplicate insertions in staged_transactions. |
| tests/test_sync_lock.py | sync_daemon.py | Concurrent invocations fail-closed when .sync.lock is present; stale lock (>30m / dead PID) reclaimed safely. |
| tests/test_phase7_e2e.py | Complete E2E | Mocked SimpleFIN server -> payload archive -> staging -> review -> compilation pipeline. |
