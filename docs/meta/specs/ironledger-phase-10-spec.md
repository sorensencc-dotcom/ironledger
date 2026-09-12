# Phase 10 specification and technical design: Enterprise production hardening, compliance auditing, and operational governance

**Program:** IronLedger  
**Milestone:** Phase 10 — Enterprise Production Hardening, Compliance Auditing & Operational Governance  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-11  
**Version:** 1.0.0 (Canonical Implementation Specification - Remediated Post-Codex Review)  
**Specification Role:** Canonical Implementation Specification & Governed Mirror  
**Change Identifier:** `IL-SPEC-PHASE-10-v1.0`  
**Decision Record:** `IL-DECISION-PHASE-10-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Approved Specification & Implementation Contract (Gate 1 Passed)  

---

## 1. Executive summary and core invariants

Phase 10 establishes enterprise production hardening, compliance auditing capabilities (automated SOC2 Type II and ISO27001 evidence bundles), high-availability replication state tracking, pure integer rational anomaly detection, fenced worker lease delivery protocols, and Operator Workbench modernization for multi-protocol connector governance, webhook outbox monitoring, and OpenMetrics telemetry.

### Upstream invariants inherited and enforced

1. **Exact rational integer arithmetic & zero float drift:** Monetary computations, outlier standard deviations, and rate-limit capacities execute exclusively via pure integer arithmetic and exact rational fractions ($N / D$). AST scanners strictly forbid floating-point division (`/`) across all anomaly detection, rate-limiting, and core financial algorithms.
2. **Zero runtime `import beancount`:** Beancount emission remains strictly string-templated and AST-verified.
3. **Tenant & entity domain isolation:** Every database record, replication stream, audit bundle, and webhook payload maintains strict composite foreign keys bound to `ledger_id`. Every governance API route derives tenant scope from authenticated capability tokens and operator context.
4. **Envelope encryption with zero secret leakage:** All credentials, keys, and tokens remain envelope-encrypted (AES-256-GCM) with distinct IV and authentication tag records. Secret payloads never appear in log streams, exception messages, or audit files.
5. **Fail-closed rate limiting and persistent circuit breaking:** External bank connectors route through token buckets and persistent three-state circuit breakers (`CLOSED`, `OPEN`, `HALF_OPEN`) with exponential backoff and randomized jitter.
6. **Append-only compliance audit ledger:** Compliance evidence bundles, mutation records, and ledger snapshots form tamper-evident Merkle trees with SHA-256 hash chaining and cryptographic archive sealing.
7. **Fenced worker lease delivery:** Webhook delivery leases employ randomized fencing tokens (`lease_fence_token`) preventing expired workers from corrupting re-assigned deliveries.
8. **Deterministic idempotency & anti-replay protection:** All mutating governance actions enforce server-validated idempotency keys bound to `(ledger_id, method, path, body_sha256)` within the mutation transaction.
9. **SSRF and egress protection:** Webhook endpoints and connector base URLs forbid private, local, and metadata network address ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.169.254`).

---

## 2. Work breakdown structure (WBS)

```
Phase 10: Enterprise Production Hardening & Compliance Governance
├── [Task 10.1] Database Schema Migration 0013 (Compliance, Governance, Nonces, Fenced Leases)
├── [Task 10.2] Governance Router Hardening & Unified Error Taxonomy
│   ├── Unified Error Response Envelope & Whitelist Audit Scrubbing
│   ├── Connector Governance & Persistent Circuit Breaker API
│   └── Webhooks Subscriptions, Delivery Monitor & DLQ Atomic Redrive API
├── [Task 10.3] Operator Workbench UI Modernization (Option B)
│   ├── Typed API Client with Idempotency Key Headers
│   ├── Connectors Governance, Timeline & Credential Vault View
│   ├── Webhook Subscriptions, Delivery Monitor & DLQ Redrive Panel
│   ├── OpenMetrics Telemetry & Health Probe Dashboard
│   └── Production Static Asset Bundling
└── [Task 10.4] Acceptance Regression Suite & Phase 10 Exit Evidence
```

---

## 3. Database schema architecture (`0013_compliance_and_governance.sql`)

```sql
-- Migration 0013: Compliance Audit Bundles, Governance Logs, Nonces, and Fenced Leases

-- 1. Compliance Audit Archive Bundles
CREATE TABLE IF NOT EXISTS compliance_audit_bundles (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    bundle_id TEXT NOT NULL,
    framework TEXT NOT NULL CHECK(framework IN ('SOC2_TYPE2', 'ISO27001', 'SOX', 'CUSTOM')),
    period_start_utc TEXT NOT NULL,
    period_end_utc TEXT NOT NULL,
    merkle_root_hex TEXT NOT NULL CHECK(length(merkle_root_hex) = 64),
    sealed_archive_sha256 TEXT NOT NULL CHECK(length(sealed_archive_sha256) = 64),
    record_count INTEGER NOT NULL CHECK(record_count >= 0),
    manifest_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(manifest_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, bundle_id)
) STRICT;

-- 2. Append-Only Governance Audit Events Table
CREATE TABLE IF NOT EXISTS governance_audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    before_state_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(before_state_json) = 1),
    after_state_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(after_state_json) = 1),
    envelope_hash TEXT NOT NULL CHECK(length(envelope_hash) = 64),
    timestamp_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER IF NOT EXISTS governance_audit_no_update
BEFORE UPDATE ON governance_audit_events
BEGIN
    SELECT RAISE(ABORT, 'governance_audit_events is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS governance_audit_no_delete
BEFORE DELETE ON governance_audit_events
BEGIN
    SELECT RAISE(ABORT, 'governance_audit_events is append-only: DELETE is forbidden');
END;

-- 3. Idempotency & Anti-Replay Registry Table
CREATE TABLE IF NOT EXISTS governance_nonce_registry (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
    response_status INTEGER,
    response_body_json TEXT,
    issued_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    expires_at_utc TEXT NOT NULL,
    PRIMARY KEY (ledger_id, idempotency_key)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_nonce_expiry ON governance_nonce_registry(expires_at_utc);

-- 4. Persistent Connector Circuit Breakers Table
CREATE TABLE IF NOT EXISTS connector_circuit_breakers (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES connector_providers(provider_id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'CLOSED' CHECK(state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
    last_failure_utc TEXT,
    opened_at_utc TEXT,
    half_open_probes INTEGER NOT NULL DEFAULT 0 CHECK(half_open_probes >= 0),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (ledger_id, provider_id)
) STRICT;

-- 5. Anomaly & Fraud Detection Flags Table
CREATE TABLE IF NOT EXISTS anomaly_flags (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    flag_id TEXT NOT NULL,
    staged_transaction_id TEXT,
    rule_type TEXT NOT NULL CHECK(rule_type IN ('DUPLICATE_CHARGE', 'VELOCITY_SPIKE', 'RATIONAL_OUTLIER', 'UNUSUAL_PAYEE')),
    severity TEXT NOT NULL CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    score_numerator INTEGER NOT NULL,
    score_denominator INTEGER NOT NULL CHECK(score_denominator > 0),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json) = 1),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    resolved_at_utc TEXT,
    resolution_status TEXT CHECK(resolution_status IN ('DISMISSED', 'CONFIRMED_FRAUD', 'RESOLVED_VALID')),
    PRIMARY KEY (ledger_id, flag_id)
) STRICT;
```

---

## 4. Governance error taxonomy & frontend mapping

### 4.1 Error envelope mapping table

| Error Code | HTTP Status | Operator Meaning | Frontend Action |
|---|---|---|---|
| `GOVERNANCE_CIRCUIT_OPEN` | 409 | Provider circuit breaker is in OPEN state | Show breaker pill (OPEN), disable trigger |
| `GOVERNANCE_DLQ_REDRIVE_DENIED` | 403 / 400 | Redrive blocked (poison message limit $>10$) | Show governance toast (error) |
| `GOVERNANCE_VALIDATION_ERROR` | 400 / 422 | Bad operator input or SSRF violation | Highlight invalid input form fields |
| `GOVERNANCE_REPLAY_WINDOW_EXCEEDED` | 409 | Anti-replay timestamp exceeded 30s window | Display replay warning notification |
| `GOVERNANCE_STATE_CONFLICT` | 409 | Concurrent mutation or active sync lock | Prompt operator to retry after release |
| `GOVERNANCE_ENVELOPE_INVALID` | 500 | KEK/DEK integrity or tag verification failure | Flag credential vault status as EXPIRED |
| `GOVERNANCE_LEASE_CONFLICT` | 409 | Delivery worker lease held by another process | Defer redrive until lease expiry |

### 4.2 Replay protection parameters

- **Replay Validity Window:** 30 seconds.
- **Nonce Registry Retention:** 90 seconds.
- **Replay Denial Code:** `GOVERNANCE_REPLAY_WINDOW_EXCEEDED`.

---

## 5. Connector federation pre-model (Phase 11 foundation)

To establish seamless continuity into Phase 11 federation:
1. **Provider Identity**: External bank providers maintain global identifiers (`PLAID`, `SIMPLEFIN`, `OFX`, `REST_JSON`) with immutable protocol declarations.
2. **Connector Lineage**: All staged documents reference parent provider run IDs, preserving cryptographic lineage from bank acquisition to Beancount compilation.
3. **Governance Scope**: Tenant ledgers isolate connector execution; cross-ledger credentials or run executions are forbidden by foreign-key relational constraints.
4. **Envelope Key Scope**: Each ledger uses isolated KEK references with distinct DEK encryption payloads.
5. **Circuit Breaker Inheritance**: Global provider health informs default backoff, while per-ledger circuit breaker instances track tenant-specific failure isolation.

---

## 6. Frontend governance toast categories

The Operator Workbench UI implements five standardized toast categories:
- `SUCCESS_GOVERNANCE_ACTION`: Emitted on successful compiles, sync completions, and rule mutations.
- `ERROR_GOVERNANCE_ACTION`: Emitted on validation errors, network failures, or auth rejections.
- `CIRCUIT_BREAKER_OPEN`: Emitted when an action targets a connector whose circuit breaker has tripped.
- `DLQ_REDRIVE_COMPLETE`: Emitted when a dead-letter delivery is successfully re-enqueued.
- `ENVELOPE_ROTATION_REQUIRED`: Emitted when active credentials exceed 30 days without DEK rotation.

---

## 7. Rollout safety gates & verification evidence

```
[Gate 1: Health Probes] ──► [Gate 2: Breaker Stability] ──► [Gate 3: Envelope Freshness] ──► [Gate 4: Clean DLQ] ──► [Gate 5: Monotonic Audit Log]
```

1. **Gate 1 (Health & Readiness Probes):** Both `/healthz` and `/readyz` return HTTP `200 OK` with verified database query execution.
2. **Gate 2 (Circuit Breaker Stability):** Metrics show zero circuit breaker oscillation over a 15-minute observation window.
3. **Gate 3 (Envelope Key Freshness):** Active connector credentials report DEK rotation age $< 30$ days.
4. **Gate 4 (Clean Dead-Letter Queue):** Zero unresolved deliveries in `webhook_delivery_dlq`.
5. **Gate 5 (Monotonic Governance Audit Log):** Sequence numbers in `governance_audit_events` and `mutation_events` form an unbroken monotonic sequence.
