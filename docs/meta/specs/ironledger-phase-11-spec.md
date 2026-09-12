# Phase 11 specification: Multi-tenant federation, cross-cluster audit propagation, and federated event routing

**Program:** IronLedger  
**Milestone:** Phase 11 — Multi-Tenant Federation, Cross-Cluster Audit Propagation & Federated Event Streaming  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `docs/meta/`  
**Date:** 2026-09-11  
**Version:** 1.1.0 (Canonical Implementation Specification - Remediated Post-Review)  
**Specification Role:** Canonical Implementation Specification & Governed Mirror  
**Change Identifier:** `IL-SPEC-PHASE-11-v1.1`  
**Decision Record:** `IL-DECISION-PHASE-11-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Approved Specification Baseline (Gate 1 Passed)  

---

## 1. Executive summary and core invariants

Phase 11 establishes multi-tenant federation, cross-cluster audit propagation, and canonical event stream routing across distributed IronLedger nodes. It unifies compliance audit bundles, rational anomaly signals, SQLite WAL replication transitions, connector governance, and webhook deliveries under the canonical `gov.event.v1` federated event envelope.

### Upstream invariants inherited and enforced

1. **Exact rational integer arithmetic & zero float drift:** All multi-tenant rate allocations, anomaly scoring, and replication lag metrics compute strictly via pure integer arithmetic and exact rational fractions ($N / D$). AST scanners strictly forbid floating-point division (`/`) and `float()` conversions across all federation, routing, and analytical algorithms.
2. **Zero runtime `import beancount`:** Beancount emission remains string-templated and AST-verified.
3. **Multi-tenant domain isolation:** Every database table, federation stream, audit proof, and event envelope maintains strict composite keys bound to `(tenant_id, ledger_id)`. Cross-tenant record leakage is prevented by relational foreign keys and token capability checks.
4. **Unified `gov.event.v1` event envelope:** All subsystems emit deterministic, immutable event records into `governance_audit_events` and `federated_event_outbox`.
5. **Fenced worker lease delivery:** Cross-cluster delivery workers enforce randomized lease fencing tokens (`lease_fence_token`) and lease expiration timestamps preventing double-dispatch and split-brain execution.
6. **Cross-cluster Merkle inclusion proofs:** Audit bundles and federation sync checkpoints generate RFC 6962 Merkle inclusion proofs for cross-cluster verification without full database synchronization.
7. **Append-only governance audit ledger:** SQLite triggers block `UPDATE` and `DELETE` on all event streams.
8. **Envelope encryption with isolated KEK/DEK scoping:** AES-256-GCM credentials remain scoped per tenant and ledger with isolated key-encryption keys. Secret payloads never appear in federation streams or logs.
9. **Peer ingestion idempotency:** Peer node ingestion enforces unique composite constraints on `(cluster_id, event_id)` within atomic ingestion transactions.

---

## 2. Work breakdown structure (WBS)

```
Phase 11: Multi-Tenant Federation & Event Streaming
├── [Task 11.1] Database Schema Migration 0014 (Federation, Peer Nodes & Fenced Event Outbox)
│   ├── Table: federation_tenants (tenant_id, name, default_ledger_id, status, created_at_utc)
│   ├── Table: federation_cluster_nodes (node_id, cluster_id, endpoint_url, role, is_active)
│   ├── Table: federated_event_outbox (event_id, tenant_id, ledger_id, payload, lease_fence_token)
│   └── Table: peer_ingested_events (cluster_id, event_id, ingested_at_utc)
├── [Task 11.2] Federated Event Engine & Event Stream Router (`src/ironledger/events/`)
│   ├── Canonical Envelope Builder & Validator (`gov.event.v1`) with Typed Domain Payloads
│   ├── Domain Event Handlers (Compliance, Anomaly, Replication, Connectors, Webhooks)
│   └── Async Outbox Dispatcher with Lease Fencing & Retry Backoff
├── [Task 11.3] Cross-Cluster Audit Propagation & Inclusion Proof Verifier
│   ├── Cross-Cluster Merkle Proof Exporter & Importer
│   └── Remote Bundle Witness Verification Protocol
├── [Task 11.4] Multi-Tenant Connector Lineage & Scoped Credential Vault
│   ├── Tenant-Scoped Provider Execution & Circuit Breakers
│   └── Isolated Envelope KEK/DEK Key Management
├── [Task 11.5] Operator Workbench UI Federation Hub (`web/`)
│   ├── Multi-Tenant Navigation & Context Switcher
│   ├── Live Federated Governance Event Stream Viewer (`/governance/events`)
│   └── Cluster Node Topology & Cross-Cluster Sync Status
└── [Task 11.6] Acceptance Regression Suite & Phase 11 Evidence Sealing
```

---

## 3. Canonical federated event envelope (`gov.event.v1`)

All federation signals share a unified JSON schema:

```json
{
  "event_id": "uuid-or-sha256-digest",
  "event_type": "string",
  "event_version": "1.0.0",
  "occurred_at": "2026-09-11T23:27:00Z",
  "recorded_at": "2026-09-11T23:27:01Z",
  "tenant_id": "tenant-uuid-or-default",
  "ledger_id": "ledger-uuid",
  "source": "compliance|anomaly|replication|connector|webhook|system",
  "correlation_id": "optional-uuid",
  "causation_id": "optional-uuid",
  "severity": "INFO|WARN|ERROR|CRITICAL",
  "payload": {
    "domain_field": "value"
  },
  "metadata": {
    "schema_version": "gov.event.v1",
    "cluster_node_id": "node-primary-01",
    "trace_id": "optional-trace",
    "tags": ["governance", "audit"]
  }
}
```

### Domain Event Families & Typed Payload Contracts

| Domain | Event Types | Strict Payload Schema Attributes |
|---|---|---|
| **Compliance** | `COMPLIANCE_BUNDLE_CREATED`, `COMPLIANCE_BUNDLE_VERIFIED`, `COMPLIANCE_BUNDLE_TAMPER_DETECTED` | `bundle_id` (str), `bundle_hash` (sha256), `merkle_root` (sha256), `record_count` (int), `verification_status` (str) |
| **Anomaly** | `ANOMALY_FLAGGED`, `ANOMALY_RESOLVED` | `flag_id` (str), `rule_type` (str), `staged_tx_id` (str), `score_numerator` (int), `score_denominator` (int), `resolution_status` (str) |
| **Replication** | `REPLICATION_POSITION_ADVANCED`, `REPLICATION_LAG_DETECTED`, `REPLICATION_FAILOVER_ELECTED` | `wal_magic` (str), `frame_index` (int), `commit_page_count` (int), `primary_lsn` (str), `replica_lsn` (str), `status` (str) |
| **Connectors** | `CONNECTOR_STATE_CHANGED`, `CONNECTOR_CIRCUIT_BREAKER_TRIPPED`, `CONNECTOR_SYNC_COMPLETED` | `provider_id` (str), `previous_state` (str), `new_state` (str), `breaker_state` (str), `failure_count` (int) |
| **Webhooks** | `WEBHOOK_SUBSCRIPTION_UPDATED`, `WEBHOOK_DLQ_REDRIVE_REQUESTED`, `WEBHOOK_DLQ_REDRIVE_COMPLETED` | `subscription_id` (str), `endpoint_url` (str), `dlq_entry_id` (str), `redrive_status` (str) |

---

## 4. Database schema architecture (`0014_multi_tenant_federation.sql`)

```sql
-- Migration 0014: Multi-Tenant Federation, Peer Nodes, and Fenced Outbox

-- 1. Federation Tenants Registry
CREATE TABLE IF NOT EXISTS federation_tenants (
    tenant_id TEXT PRIMARY KEY CHECK(length(tenant_id) >= 1 AND length(tenant_id) <= 64),
    name TEXT NOT NULL CHECK(length(name) >= 1 AND length(name) <= 128),
    default_ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

INSERT OR IGNORE INTO federation_tenants (tenant_id, name, default_ledger_id) VALUES ('default', 'Default Tenant', 'default');

-- 2. Peer Cluster Nodes
CREATE TABLE IF NOT EXISTS federation_cluster_nodes (
    node_id TEXT PRIMARY KEY CHECK(length(node_id) >= 1 AND length(node_id) <= 64),
    cluster_id TEXT NOT NULL CHECK(length(cluster_id) >= 1 AND length(cluster_id) <= 64),
    endpoint_url TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('PRIMARY', 'REPLICA', 'WITNESS')),
    last_heartbeat_utc TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

-- 3. Fenced Federated Event Outbox
CREATE TABLE IF NOT EXISTS federated_event_outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE CHECK(length(event_id) >= 16),
    tenant_id TEXT NOT NULL REFERENCES federation_tenants(tenant_id) ON DELETE CASCADE,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) = 1),
    published_to_peers INTEGER NOT NULL DEFAULT 0 CHECK(published_to_peers IN (0, 1)),
    lease_owner_id TEXT,
    lease_fence_token TEXT,
    lease_expires_at_utc TEXT,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_federated_outbox_unpub ON federated_event_outbox(published_to_peers, seq);
CREATE INDEX IF NOT EXISTS idx_federated_outbox_lease ON federated_event_outbox(lease_expires_at_utc);

-- 4. Peer Ingestion Idempotency Registry
CREATE TABLE IF NOT EXISTS peer_ingested_events (
    cluster_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    PRIMARY KEY (cluster_id, event_id)
) STRICT;
```

---

## 5. Rollout safety gates

```
[Gate 1: Multi-Tenant Isolation] ──► [Gate 2: Envelope Canonicality & Leases] ──► [Gate 3: Cross-Cluster Proofs] ──► [Gate 4: Zero Float Invariant] ──► [Gate 5: Monotonic Outbox]
```

1. **Gate 1 (Multi-Tenant Isolation):** Every database mutation strictly scoped by composite `(tenant_id, ledger_id)` foreign keys.
2. **Gate 2 (Event Envelope Canonicality & Fenced Leases):** 100% of emitted events conform to `gov.event.v1` schema validation and worker leases utilize fencing tokens.
3. **Gate 3 (Cross-Cluster Proof Verification):** Remote witness nodes verify Merkle inclusion proofs with zero raw transaction transfer.
4. **Gate 4 (Zero Float Invariant):** AST scanners confirm zero `/` division and zero `float()` conversions across all federation and routing code.
5. **Gate 5 (Monotonic Outbox & Zero Event Loss):** Outbox sequence numbers maintain strict gapless ordering with durable acknowledgements.
