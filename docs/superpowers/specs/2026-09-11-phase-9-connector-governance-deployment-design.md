# Phase 9 specification and technical design: Connector governance and enterprise deployment pipeline

**Program:** IronLedger  
**Milestone:** Phase 9 — Connector Governance & Enterprise Deployment Pipeline  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-11  
**Version:** 1.0.0 (Canonical Specification)  
**Specification Role:** Canonical Implementation Specification & Governed Mirror  
**Change Identifier:** `IL-SPEC-PHASE-9-v1.0`  
**Decision Record:** `IL-DECISION-PHASE-9-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Pre-Implementation Architectural Specification & Design Contract (Gate 1)  

---

## 1. Executive summary and core invariants

Phase 9 expands IronLedger from local and single-tenant environments into a production-grade multi-institution engine with governed financial data connectors, envelope secret encryption, real-time webhook dispatching, Prometheus observability, and containerized deployment infrastructure.

### Upstream invariants inherited and enforced

1. **Exact rational integer arithmetic & zero float drift:** All monetary conversions, token bucket calculations, and rate limits operate strictly with integer math and rational proportions ($N / D$). AST scanners forbid float division (`/`) in core financial and rate-limiting modules.
2. **Zero runtime `import beancount`:** Plaintext Beancount emission remains purely string-templated and AST-audited.
3. **Tenant & entity domain isolation:** Every connector credential, synchronization run, webhook subscription, outbox event, and log stream carries a mandatory `ledger_id` composite foreign key with strict SQLite foreign key enforcement (`PRAGMA foreign_keys = ON;`).
4. **Envelope encryption with zero plaintext leakage:** All provider access tokens, client secrets, and banking certificates are encrypted at rest using AES-256-GCM Data Encryption Keys (DEKs) wrapped by Key Encryption Keys (KEKs). In-memory credentials are zeroed on garbage collection and scrubbed from exceptions, logs, and database errors.
5. **Fail-closed rate limiting and circuit breaking:** External bank API integrations must route through a token bucket rate limiter and three-state circuit breaker (`CLOSED`, `OPEN`, `HALF_OPEN`) with exponential backoff and randomized jitter to prevent rate-limit bans and cascading upstream failure.
6. **Guaranteed delivery event outbox & HMAC webhooks:** Mutations and staging operations publish immutable events to an append-only transactional outbox. The webhook dispatcher delivers signed HTTP requests with SHA-256 HMAC headers and anti-replay timestamps ($t_{req} \pm 300\text{s}$), dead-lettering unrecoverable deliveries after bounded retries.
7. **Observable containerized runtime:** The application packages into distroless OCI container images with non-root security context (`USER 10001:10001`), exposing `/healthz`, `/readyz`, and Prometheus `/metrics` endpoints.

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

Phase 9 introduces migration `0012_connectors_governance.sql` using SQLite `STRICT` tables and covered indexes.

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
    credential_id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    key_id TEXT NOT NULL,
    encrypted_dek_blob BLOB NOT NULL,
    encrypted_payload_blob BLOB NOT NULL,
    iv_hex TEXT NOT NULL CHECK(length(iv_hex) = 24),
    auth_tag_hex TEXT NOT NULL CHECK(length(auth_tag_hex) = 32),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    UNIQUE (ledger_id, provider_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_connector_credentials_lookup ON connector_credentials(ledger_id, provider_id);

-- 3. Connector Synchronization Execution History
CREATE TABLE IF NOT EXISTS connector_sync_runs (
    run_id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CIRCUIT_BROKEN')),
    records_fetched INTEGER NOT NULL DEFAULT 0 CHECK(records_fetched >= 0),
    records_staged INTEGER NOT NULL DEFAULT 0 CHECK(records_staged >= 0),
    error_code TEXT,
    error_details TEXT,
    started_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT,
    CHECK(completed_at_utc IS NULL OR (completed_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND completed_at_utc NOT GLOB '*[^0-9T:.Z-]*'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_connector_sync_runs_ledger ON connector_sync_runs(ledger_id, started_at_utc);

-- 4. Webhook Subscriptions Registry
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    target_url TEXT NOT NULL CHECK(target_url GLOB 'https://*' OR target_url GLOB 'http://localhost:*' OR target_url GLOB 'http://127.0.0.1:*'),
    secret_hash TEXT NOT NULL CHECK(length(secret_hash) = 64),
    event_types_json TEXT NOT NULL CHECK(json_valid(event_types_json) = 1 AND json_type(event_types_json) = 'array'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_ledger ON webhook_subscriptions(ledger_id, is_active);

-- 5. Transactional Event Outbox
CREATE TABLE IF NOT EXISTS event_outbox (
    event_id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED', 'DEAD_LETTERED')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    next_retry_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_event_outbox_queue ON event_outbox(status, next_retry_at_utc);
CREATE INDEX IF NOT EXISTS idx_event_outbox_ledger ON event_outbox(ledger_id, event_id);

-- 6. Webhook Delivery Dead-Letter Queue (DLQ)
CREATE TABLE IF NOT EXISTS webhook_delivery_dlq (
    delivery_id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions(subscription_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES event_outbox(event_id) ON DELETE CASCADE,
    status_code INTEGER,
    last_error TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
    failed_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_webhook_dlq_sub ON webhook_delivery_dlq(subscription_id, failed_at_utc);
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
   $$	ext{refilled\_tokens} = \left\lfloor rac{\Delta t \cdot r}{60{,}000} ightfloor$$
   $$	ext{current\_tokens} = \min(C, 	ext{prior\_tokens} + 	ext{refilled\_tokens})$$
   A request consumes 1 token if $	ext{current\_tokens} \ge 1$; otherwise, it returns a wait duration:
   $$	ext{wait\_ms} = \left\lceil rac{(1 - 	ext{current\_tokens}) \cdot 60{,}000}{r} ightceil$$

2. **Circuit Breaker State Machine:**
   - **CLOSED:** Normal operation. Consecutive failures increment failure counter. If failures $\ge 	ext{failure\_threshold}$, transition to **OPEN** and set $	au_{	ext{cooldown}}$.
   - **OPEN:** Fast-fail all requests immediately with `CircuitBreakerOpenError`. After cooldown $	au_{	ext{cooldown}}$ elapses, transition to **HALF_OPEN**.
   - **HALF_OPEN:** Permit single trial probe. If probe succeeds, reset failure counter and transition to **CLOSED**. If probe fails, increment cooldown exponentially ($\min(2 \cdot 	au, 	au_{\max})$) and return to **OPEN**.

---

### Task 9.2: Secret management, hardware token / HSM and envelope encryption

#### 1. Architecture & Layout
- **Module:** `src/ironledger/security/`
  - `envelope.py`: Envelope encryption engine using AES-256-GCM.
  - `key_provider.py`: Key provider abstract interface and concrete providers:
    - `EnvironmentKeyProvider`: Reads KEK from protected runtime environment variable.
    - `WindowsDpapiProvider`: Uses Windows Data Protection API (`CryptProtectData`) on Windows hosts.
    - `Pkcs11HsmProvider`: Interface for hardware security module tokens.
  - `scrubbing.py`: Automated regex secret scrubber for logs, exceptions, and audit records.

#### 2. Envelope encryption specification
1. **Encryption Flow:**
   - Generate ephemeral 256-bit Data Encryption Key: $	ext{DEK} \leftarrow 	ext{CSPRNG}(32)$.
   - Generate 96-bit Initialization Vector: $	ext{IV} \leftarrow 	ext{CSPRNG}(12)$.
   - Encrypt credential payload using AES-256-GCM:
     $$(	ext{Ciphertext}, 	ext{Tag}) = 	ext{AES-256-GCM}_{	ext{DEK}}(	ext{IV}, 	ext{Payload}, 	ext{AAD}=	ext{ledger\_id} \parallel 	ext{provider\_id})$$
   - Encrypt DEK using Key Encryption Key from Key Provider:
     $$	ext{WrappedDEK} = 	ext{AES-256-GCM}_{	ext{KEK}}(	ext{IV}_{	ext{kek}}, 	ext{DEK}, 	ext{AAD}=	ext{key\_id})$$
   - Persist $	ext{WrappedDEK}$, $	ext{Ciphertext}$, $	ext{IV}$, $	ext{Tag}$, and $	ext{key\_id}$ to database.
   - Zero DEK memory buffers immediately after operation.

2. **Decryption Flow:**
   - Retrieve wrapped DEK and payload from `connector_credentials`.
   - Unwrap DEK using KEK from active Key Provider.
   - Decrypt payload and verify authentication tag with matching AAD. If tag mismatch, raise `TamperDetectedError`.

---

### Task 9.3: Real-time webhook dispatcher and event notification fabric

#### 1. Architecture & Layout
- **Module:** `src/ironledger/events/`
  - `models.py`: `OutboxEvent`, `WebhookSubscription`, `DeliveryResult`.
  - `outbox.py`: Transactional event publisher attaching to SQLite write transactions.
  - `dispatcher.py`: Concurrent async/worker dispatcher delivering signed webhooks.
  - `signer.py`: HMAC-SHA256 signature generator emitting `X-IronLedger-Signature` and `X-IronLedger-Timestamp` headers.

#### 2. Webhook delivery security contract
- **Header format:**
  - `X-IronLedger-Timestamp: <unix_epoch_seconds>`
  - `X-IronLedger-Signature: t=<unix_epoch_seconds>,v1=<hmac_sha256_hex>`
- **Signature input:**
  $$	ext{SignInput} = 	ext{timestamp} \mathbin{\Vert} 	ext{"."} \mathbin{\Vert} 	ext{payload\_json}$$
  $$	ext{Signature} = 	ext{HMAC-SHA256}(	ext{subscription\_secret}, 	ext{SignInput})$$
- **Replay Protection:** Receiver rejects any request where $|t_{	ext{current}} - t_{	ext{header}}| > 300	ext{ seconds}$.

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
- `tests/test_envelope_encryption.py`: Envelope encryption, DPAPI and Environment key providers, AAD tamper detection, and key rotation.
- `tests/test_webhooks.py`: Transactional outbox, concurrent delivery, retry backoff, HMAC anti-replay signatures, and dead-letter queue routing.
- `tests/test_observability.py`: Prometheus metrics exposition, histogram bucketing, structured JSON log formatting, and secret scrubbing assertions.
- `tests/test_phase9_exit_contract.py`: Comprehensive end-to-end integration across connectors, secrets, webhooks, metrics, and AST zero-beancount / zero-float verification.
- `docs/meta/phases/ironledger-phase-9-evidence.md`: Sealed exit evidence document.

---

## 5. Security, cryptography and threat modeling

| Threat Scenario | Mitigation Strategy | Verification Mechanism |
|---|---|---|
| **Plaintext Credential Theft** | AES-256-GCM envelope encryption with hardware/OS-backed KEKs; memory buffers scrubbed immediately. | `test_envelope_encryption.py` verifies zero plaintext in SQLite tables. |
| **API Provider Throttling / IP Ban** | Token bucket rate limiting combined with circuit breaker fast-fail and randomized backoff. | `test_connectors.py` simulates burst load and asserts request queuing. |
| **Webhook Spoofing & Replay** | SHA-256 HMAC payload signatures and strict 300-second timestamp freshness window. | `test_webhooks.py` rejects modified payloads and expired timestamps. |
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
