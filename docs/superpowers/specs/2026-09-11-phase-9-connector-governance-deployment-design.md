# Phase 9 specification and technical design: Connector governance and enterprise deployment pipeline

**Program:** IronLedger  
**Milestone:** Phase 9 — Connector Governance & Enterprise Deployment Pipeline  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-11  
**Version:** 1.1.0 (Hardened Canonical Specification - Gate 1 Codex Review Remediation)  
**Specification Role:** Canonical Implementation Specification & Governed Mirror  
**Change Identifier:** `IL-SPEC-PHASE-9-v1.1`  
**Decision Record:** `IL-DECISION-PHASE-9-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Pre-Implementation Architectural Specification & Design Contract (Gate 1)  

---

## 1. Executive summary and core invariants

Phase 9 expands IronLedger from local and single-tenant environments into a production-grade multi-institution engine with governed financial data connectors, envelope secret encryption, real-time webhook dispatching, Prometheus observability, and containerized deployment infrastructure.

### Upstream invariants inherited and enforced

1. **Exact rational integer arithmetic & zero float drift:** All monetary conversions, token bucket calculations, and rate limits operate strictly with integer math and rational proportions ($N / D$). AST scanners forbid float division (`/`) in core financial and rate-limiting modules.
2. **Zero runtime `import beancount`:** Plaintext Beancount emission remains purely string-templated and AST-audited.
3. **Tenant & entity domain isolation:** Every connector credential, synchronization run, webhook subscription, outbox event, per-subscription delivery record, dead-letter entry, and log stream carries a mandatory `ledger_id` composite foreign key with strict SQLite foreign key enforcement (`PRAGMA foreign_keys = ON;`). Cross-tenant pairing between subscriptions and events is blocked by composite schema constraints.
4. **Envelope encryption with zero plaintext leakage:** All provider access tokens, client secrets, and banking certificates are encrypted at rest using AES-256-GCM Data Encryption Keys (DEKs) wrapped by Key Encryption Keys (KEKs). In-memory credentials are zeroed on garbage collection and scrubbed from exceptions, logs, and database errors. Distinct IVs and authentication tags are maintained for both wrapped DEKs and encrypted payloads.
5. **Fail-closed rate limiting and circuit breaking:** External bank API integrations route through a token bucket rate limiter and three-state circuit breaker (`CLOSED`, `OPEN`, `HALF_OPEN`) with exponential backoff and randomized jitter to prevent rate-limit bans and cascading upstream failure.
6. **Guaranteed delivery event outbox & per-subscription tracking:** Mutations and staging operations publish immutable events to an append-only transactional outbox guarded by triggers against payload alteration. A dedicated `webhook_deliveries` table tracks delivery state per subscription with worker lease timeouts, automated abandoned-task recovery, and dead-letter queue (DLQ) routing.
7. **HMAC webhook signatures with comprehensive anti-replay protection:** The webhook dispatcher delivers signed HTTP requests with SHA-256 HMAC headers binding the timestamp, event ID, delivery ID, and payload body. Replay protection enforces a strict 300-second freshness window and receiver-side delivery deduplication.
8. **Observable containerized runtime:** The application packages into distroless OCI container images with non-root security context (`USER 10001:10001`), exposing `/healthz`, `/readyz`, and Prometheus `/metrics` endpoints.

---

## 2. Work breakdown structure (WBS)

```
Phase 9: Connector Governance & Enterprise Deployment Pipeline
├── [Task 9.1] Multi-Protocol Connector Governance & Ingestion Rate Limiter
├── [Task 9.2] Secret Management, Hardware Token / HSM & Envelope Encryption
├── [Task 9.3] Real-Time Webhook Dispatcher & Event Notification Fabric
├── [Task 9.4] Enterprise Deployment Pipeline & Container Infrastructure
├── [Task 9.5] System Observability & Prometheus Metrics Exporter
└── [Task 9.6] Acceptance Regression Suite & Phase 9 Exit Evidence
```

---

## 3. Database schema architecture and migration contract

Phase 9 introduces migration `0012_connectors_governance.sql` using SQLite `STRICT` tables, covered indexes, and append-only trigger protections.

### Migration `0012_connectors_governance.sql`

```sql
-- Migration 0012: Connector Governance, Envelope Credentials, Webhook Outbox & DLQ

-- 1. Connector Provider Registry
CREATE TABLE IF NOT EXISTS connector_providers (
    provider_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protocol_type TEXT NOT NULL CHECK(protocol_type IN ('PLAID', 'SIMPLEFIN', 'OFX', 'REST_JSON')),
    base_url TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    rate_limit_rpm INTEGER NOT NULL DEFAULT 60 CHECK(rate_limit_rpm > 0),
    burst_capacity INTEGER NOT NULL DEFAULT 10 CHECK(burst_capacity > 0),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

-- 2. Envelope-Encrypted Connector Credentials
CREATE TABLE IF NOT EXISTS connector_credentials (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    credential_id TEXT NOT NULL,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    kek_key_id TEXT NOT NULL,
    encrypted_dek_blob BLOB NOT NULL,
    dek_iv_hex TEXT NOT NULL CHECK(length(dek_iv_hex) = 24),
    dek_auth_tag_hex TEXT NOT NULL CHECK(length(dek_auth_tag_hex) = 32),
    encrypted_payload_blob BLOB NOT NULL,
    payload_iv_hex TEXT NOT NULL CHECK(length(payload_iv_hex) = 24),
    payload_auth_tag_hex TEXT NOT NULL CHECK(length(payload_auth_tag_hex) = 32),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, credential_id),
    UNIQUE (ledger_id, provider_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_connector_credentials_lookup ON connector_credentials(ledger_id, provider_id);

-- 3. Connector Synchronization Execution History
CREATE TABLE IF NOT EXISTS connector_sync_runs (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CIRCUIT_BROKEN')),
    records_fetched INTEGER NOT NULL DEFAULT 0 CHECK(records_fetched >= 0),
    records_staged INTEGER NOT NULL DEFAULT 0 CHECK(records_staged >= 0),
    error_code TEXT,
    error_details TEXT,
    started_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT,
    PRIMARY KEY (ledger_id, run_id),
    CHECK(completed_at_utc IS NULL OR (completed_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND completed_at_utc NOT GLOB '*[^0-9T:.Z-]*'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_connector_sync_runs_ledger ON connector_sync_runs(ledger_id, started_at_utc);

-- 4. Webhook Subscriptions Registry with Envelope-Encrypted Secrets
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    subscription_id TEXT NOT NULL,
    target_url TEXT NOT NULL CHECK(target_url GLOB 'https://*' OR target_url GLOB 'http://localhost:*' OR target_url GLOB 'http://127.0.0.1:*'),
    kek_key_id TEXT NOT NULL,
    encrypted_dek_blob BLOB NOT NULL,
    dek_iv_hex TEXT NOT NULL CHECK(length(dek_iv_hex) = 24),
    dek_auth_tag_hex TEXT NOT NULL CHECK(length(dek_auth_tag_hex) = 32),
    encrypted_secret_blob BLOB NOT NULL,
    secret_iv_hex TEXT NOT NULL CHECK(length(secret_iv_hex) = 24),
    secret_auth_tag_hex TEXT NOT NULL CHECK(length(secret_auth_tag_hex) = 32),
    secret_fingerprint_hex TEXT NOT NULL CHECK(length(secret_fingerprint_hex) = 64),
    event_types_json TEXT NOT NULL CHECK(json_valid(event_types_json) = 1 AND json_type(event_types_json) = 'array'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, subscription_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_ledger ON webhook_subscriptions(ledger_id, is_active);

-- 5. Append-Only Transactional Event Outbox
CREATE TABLE IF NOT EXISTS event_outbox (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, event_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_event_outbox_ledger ON event_outbox(ledger_id, created_at_utc);

-- Triggers enforcing immutable event_outbox
CREATE TRIGGER IF NOT EXISTS event_outbox_no_update
BEFORE UPDATE ON event_outbox
BEGIN
    SELECT RAISE(ABORT, 'event_outbox is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS event_outbox_no_delete
BEFORE DELETE ON event_outbox
BEGIN
    SELECT RAISE(ABORT, 'event_outbox is append-only: DELETE is forbidden');
END;

-- 6. Per-Subscription Webhook Delivery State
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    ledger_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED', 'DEAD_LETTERED')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    next_retry_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    leased_by TEXT,
    leased_until_utc TEXT,
    last_status_code INTEGER,
    last_error TEXT,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT,
    PRIMARY KEY (ledger_id, delivery_id),
    FOREIGN KEY (ledger_id, event_id) REFERENCES event_outbox(ledger_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id, subscription_id) REFERENCES webhook_subscriptions(ledger_id, subscription_id) ON DELETE CASCADE,
    UNIQUE (ledger_id, event_id, subscription_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_queue ON webhook_deliveries(status, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_lease ON webhook_deliveries(status, leased_until_utc);

-- 7. Webhook Delivery Dead-Letter Queue (DLQ) with Strict Composite Tenant Isolation
CREATE TABLE IF NOT EXISTS webhook_delivery_dlq (
    ledger_id TEXT NOT NULL,
    dlq_entry_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    status_code INTEGER,
    last_error TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
    failed_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, dlq_entry_id),
    FOREIGN KEY (ledger_id, delivery_id) REFERENCES webhook_deliveries(ledger_id, delivery_id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id, event_id) REFERENCES event_outbox(ledger_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id, subscription_id) REFERENCES webhook_subscriptions(ledger_id, subscription_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_dlq_lookup ON webhook_delivery_dlq(ledger_id, subscription_id, failed_at_utc);
```

---

## 4. Subsystem technical specifications

### Task 9.1: Multi-protocol connector governance and ingestion rate limiter

#### 1. Architecture & Layout
- **Module:** `src/ironledger/connectors/`
  - `models.py`: Provider dataclasses, SyncResult, ProtocolType enum.
  - `base.py`: `BaseConnector` abstract interface.
  - `rate_limiter.py`: Integer-based token bucket rate limiter with millisecond timestamps.
  - `circuit_breaker.py`: Three-state circuit breaker with configurable failure thresholds.
  - `registry.py`: Dynamic connector registry and execution dispatcher.
  - `plaid.py`, `simplefin.py`, `ofx.py`: Protocol-specific connector adapters.

#### 2. Token bucket and circuit breaker mathematical specification
1. **Token Bucket Rate Limiting:**
   Let $C$ be burst capacity (integer tokens), $r$ be refill rate in tokens per minute ($rpm$), and $\Delta t$ be elapsed milliseconds since last refill:
   $$\text{refilled\_tokens} = \left\lfloor \frac{\Delta t \cdot r}{60{,}000} \right\rfloor$$
   $$\text{current\_tokens} = \min(C, \text{prior\_tokens} + \text{refilled\_tokens})$$
   A request consumes 1 token if $\text{current\_tokens} \ge 1$; otherwise, it returns a wait duration:
   $$\text{wait\_ms} = \left\lceil \frac{(1 - \text{current\_tokens}) \cdot 60{,}000}{r} \right\rceil$$

2. **Circuit Breaker State Machine:**
   - **CLOSED:** Normal operation. Consecutive failures increment failure counter. If failures $\ge \text{failure\_threshold}$, transition to **OPEN** and set $\tau_{\text{cooldown}}$.
   - **OPEN:** Fast-fail all requests immediately with `CircuitBreakerOpenError`. After cooldown $\tau_{\text{cooldown}}$ elapses, transition to **HALF_OPEN**.
   - **HALF_OPEN:** Permit single trial probe. If probe succeeds, reset failure counter and transition to **CLOSED**. If probe fails, increment cooldown exponentially ($\min(2 \cdot \tau, \tau_{\max})$) and return to **OPEN**.

---

### Task 9.2: Secret management, hardware token / HSM and envelope encryption

#### 1. Architecture & Layout
- **Module:** `src/ironledger/security/`
  - `envelope.py`: Envelope encryption engine using AES-256-GCM with separate IV and Tag storage.
  - `key_provider.py`: Key provider abstract interface and concrete providers:
    - `EnvironmentKeyProvider`: Reads KEK from protected runtime environment variable.
    - `WindowsDpapiProvider`: Uses Windows Data Protection API (`CryptProtectData`) on Windows hosts.
    - `Pkcs11HsmProvider`: Interface for hardware security module tokens.
  - `scrubbing.py`: Automated regex secret scrubber for logs, exceptions, and audit records.

#### 2. Envelope encryption specification
1. **Encryption Flow:**
   - Generate ephemeral 256-bit Data Encryption Key: $\text{DEK} \leftarrow \text{CSPRNG}(32)$.
   - Generate 96-bit Payload Initialization Vector: $\text{IV}_{\text{payload}} \leftarrow \text{CSPRNG}(12)$.
   - Generate 96-bit KEK Initialization Vector: $\text{IV}_{\text{dek}} \leftarrow \text{CSPRNG}(12)$.
   - Encrypt credential payload using AES-256-GCM:
     $$(\text{Ciphertext}, \text{Tag}_{\text{payload}}) = \text{AES-256-GCM}_{\text{DEK}}(\text{IV}_{\text{payload}}, \text{Payload}, \text{AAD}=\text{ledger\_id} \parallel \text{provider\_id})$$
   - Encrypt DEK using Key Encryption Key from Key Provider:
     $$(\text{WrappedDEK}, \text{Tag}_{\text{dek}}) = \text{AES-256-GCM}_{\text{KEK}}(\text{IV}_{\text{dek}}, \text{DEK}, \text{AAD}=\text{kek\_key\_id})$$
   - Persist $\text{WrappedDEK}$, $\text{IV}_{\text{dek}}$, $\text{Tag}_{\text{dek}}$, $\text{Ciphertext}$, $\text{IV}_{\text{payload}}$, $\text{Tag}_{\text{payload}}$, and $\text{kek\_key\_id}$ to database.
   - Zero DEK memory buffers immediately after operation.

2. **Decryption Flow:**
   - Retrieve wrapped DEK and payload record from `connector_credentials`.
   - Unwrap DEK using KEK from active Key Provider and verify $\text{Tag}_{\text{dek}}$.
   - Decrypt payload and verify authentication tag $\text{Tag}_{\text{payload}}$ with matching AAD. If tag mismatch, raise `TamperDetectedError`.

---

### Task 9.3: Real-time webhook dispatcher and event notification fabric

#### 1. Architecture & Layout
- **Module:** `src/ironledger/events/`
  - `models.py`: `OutboxEvent`, `WebhookSubscription`, `WebhookDelivery`, `DeliveryResult`.
  - `outbox.py`: Transactional event publisher attaching to SQLite write transactions.
  - `dispatcher.py`: Concurrent async/worker dispatcher with lease claiming and retry backoff.
  - `signer.py`: HMAC-SHA256 signature generator emitting tamper-evident headers.
  - `reconciliation.py`: Startup lease recovery requeueing expired `PROCESSING` deliveries.

#### 2. Webhook delivery security and replay protection contract
- **Header format:**
  - `X-IronLedger-Timestamp: <unix_epoch_seconds>`
  - `X-IronLedger-Event-Id: <event_id>`
  - `X-IronLedger-Delivery-Id: <delivery_id>`
  - `X-IronLedger-Signature: t=<unix_epoch_seconds>,e=<event_id>,d=<delivery_id>,v1=<hmac_sha256_hex>`
- **Signature input:**
  $$\text{SignInput} = \text{timestamp} \mathbin{\Vert} \text{"."} \mathbin{\Vert} \text{event\_id} \mathbin{\Vert} \text{"."} \mathbin{\Vert} \text{delivery\_id} \mathbin{\Vert} \text{"."} \mathbin{\Vert} \text{payload\_json}$$
  $$\text{Signature} = \text{HMAC-SHA256}(\text{subscription\_secret}, \text{SignInput})$$
- **Replay Protection Contract:**
  1. Receiver checks timestamp freshness: $|t_{\text{current}} - t_{\text{header}}| \le 300\text{ seconds}$.
  2. Receiver verifies HMAC-SHA256 signature using the shared secret.
  3. Receiver performs duplicate check against local delivered idempotency cache: if `(event_id, delivery_id)` was processed within the active freshness window, return HTTP 200 without duplicate execution.

#### 3. Worker Lease & Abandoned Event Recovery
- Workers claim pending deliveries using atomic database updates:
  ```sql
  UPDATE webhook_deliveries
  SET status = 'PROCESSING',
      leased_by = :worker_id,
      leased_until_utc = strftime('%Y-%m-%d %H:%M:%fZ', 'now', '+60 seconds')
  WHERE ledger_id = :ledger_id
    AND delivery_id = (
        SELECT delivery_id FROM webhook_deliveries
        WHERE ledger_id = :ledger_id AND status = 'PENDING' AND next_retry_at_utc <= strftime('%Y-%m-%d %H:%M:%fZ', 'now')
        ORDER BY next_retry_at_utc ASC LIMIT 1
    );
  ```
- **Startup Lease Reconciliation:**
  On application or worker initialization, `reconcile_abandoned_deliveries()` executes:
  ```sql
  UPDATE webhook_deliveries
  SET status = 'PENDING',
      leased_by = NULL,
      leased_until_utc = NULL
  WHERE status = 'PROCESSING'
    AND leased_until_utc < strftime('%Y-%m-%d %H:%M:%fZ', 'now');
  ```

---

### Task 9.4: Enterprise deployment pipeline and container infrastructure

#### 1. Architecture & Layout
- **Path:** `deploy/`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`
  - `Dockerfile`: Multi-stage build producing distroless / minimal non-root image.
  - `deploy/docker-compose.yml`: Production-ready stack with IronLedger API, volume mounts, and health checks.
  - `src/ironledger/web/routers/health.py`: `/healthz` (liveness) and `/readyz` (readiness) endpoints.

#### 2. Container security invariants
1. Run as non-privileged non-root user `ironledger:ironledger` (UID 10001, GID 10001).
2. Read-only root filesystem with explicit writable volume mounts for `data/` and `.ironledger/`.
3. Drop all Linux capabilities (`ALL`), forbid privilege escalation (`no-new-privileges:true`).
4. Automated preflight database migration `migrate_governed()` on startup before opening listening ports.

---

### Task 9.5: System observability and Prometheus metrics exporter

#### 1. Architecture & Layout
- **Module:** `src/ironledger/observability/`
  - `metrics.py`: Pure-Python Prometheus/OpenMetrics formatted registry (zero external dependencies).
  - `middleware.py`: FastAPI / ASGI HTTP request duration and status counter middleware.
  - `logging.py`: Structured JSON log formatter with correlation ID, tenant ID, and secret scrubbing.
  - `src/ironledger/web/routers/metrics.py`: `/metrics` scrape endpoint.

#### 2. Monitored metrics specification
- `ironledger_http_requests_total{method, path, status}` (Counter)
- `ironledger_http_request_duration_seconds{method, path}` (Histogram)
- `ironledger_connector_sync_duration_seconds{provider_id, status}` (Histogram)
- `ironledger_connector_records_staged_total{provider_id, ledger_id}` (Counter)
- `ironledger_rate_limiter_tokens_available{provider_id}` (Gauge)
- `ironledger_circuit_breaker_state{provider_id}` (Gauge: 0=Closed, 1=Half-Open, 2=Open)
- `ironledger_event_outbox_queue_depth{status}` (Gauge)
- `ironledger_webhook_delivery_failures_total{subscription_id}` (Counter)
- `ironledger_token_auth_failures_total{reason}` (Counter)

---

### Task 9.6: Acceptance regression suite and Phase 9 exit evidence

#### 1. Test Suite Layout
- `tests/test_connectors.py`: Multi-protocol connector registry, Plaid/SimpleFIN/OFX parsers, rate-limiting token bucket, and circuit breaker recovery.
- `tests/test_envelope_encryption.py`: Envelope encryption, DPAPI and Environment key providers, distinct DEK/Payload IV/Tag storage, AAD tamper detection, and key rotation.
- `tests/test_webhooks.py`: Transactional append-only outbox triggers, per-subscription deliveries, worker lease expiration, startup reconciliation, HMAC anti-replay signatures, and dead-letter queue routing.
- `tests/test_observability.py`: Prometheus metrics exposition, histogram bucketing, structured JSON log formatting, and secret scrubbing assertions.
- `tests/test_phase9_exit_contract.py`: Comprehensive end-to-end integration across connectors, secrets, webhooks, metrics, and AST zero-beancount / zero-float verification.
- `docs/meta/phases/ironledger-phase-9-evidence.md`: Sealed exit evidence document.

---

## 5. Security, cryptography and threat modeling

| Threat Scenario | Mitigation Strategy | Verification Mechanism |
|---|---|---|
| **Plaintext Credential Theft** | AES-256-GCM envelope encryption with hardware/OS-backed KEKs; distinct IVs and Auth Tags; memory buffers scrubbed immediately. | `test_envelope_encryption.py` verifies zero plaintext in SQLite tables. |
| **API Provider Throttling / IP Ban** | Token bucket rate limiting combined with circuit breaker fast-fail and randomized backoff. | `test_connectors.py` simulates burst load and asserts request queuing. |
| **Webhook Spoofing & Replay** | SHA-256 HMAC payload signatures binding timestamp, event ID, and delivery ID with strict 300-second window and receiver duplicate detection. | `test_webhooks.py` rejects modified payloads, expired timestamps, and replayed requests. |
| **Cross-Tenant DLQ Leakage** | Composite primary and foreign keys (`PRIMARY KEY(ledger_id, dlq_entry_id)`) enforcing exact tenant parity across deliveries, events, and subscriptions. | `test_webhooks.py` asserts database foreign key rejection on cross-tenant DLQ inserts. |
| **Stranded Webhook Deliveries on Crash** | Leased worker delivery claims with automatic startup lease reconciliation resetting abandoned deliveries to `PENDING`. | `test_webhooks.py` validates recovery of expired in-flight deliveries. |
| **Tampering with Outbox Records** | Immutable `event_outbox` protected by SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers. | `test_webhooks.py` asserts trigger abort on outbox modification or deletion. |
| **Container Privilege Escalation** | Distroless minimal image, non-root UID 10001, read-only rootfs, dropped capabilities. | Container manifest and security scan audit. |
| **Log Leakage of Financial Data** | Automated regex secret scrubber filtering PANs, tokens, and authorization headers from stdout/stderr. | `test_observability.py` asserts token redaction in log output. |

---

## 6. Acceptance and exit criteria

To satisfy Phase 9 Gate 2 exit sign-off:
1. All migrations up to `0012_connectors_governance.sql` apply cleanly in order with validated SHA-256 checksums.
2. All new modules under `connectors/`, `security/`, `events/`, and `observability/` achieve 100% unit and integration test pass rates.
3. Static AST analysis confirms zero runtime `beancount` imports and zero floating-point division across the entire codebase.
4. Total test suite passes with zero regressions across Phases 1 through 8.
5. `STATUS.md` and `docs/meta/phases/ironledger-phase-9-evidence.md` are updated and sealed.
