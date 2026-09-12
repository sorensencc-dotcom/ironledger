# Phase 12 specification: High-availability failover fabric, cross-region disaster recovery, and tenant key rotation

**Program:** IronLedger  
**Milestone:** Phase 12 — High-Availability Failover Fabric, Cross-Region Disaster Recovery & Tenant Key Rotation  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `docs/meta/`  
**Date:** 2026-09-12  
**Version:** 1.0.0 (Canonical Implementation Specification)  
**Change Identifier:** `IL-SPEC-PHASE-12-v1.0`  
**Decision Record:** `IL-DECISION-PHASE-12-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Approved Specification Baseline (Gate 1 Passed)  

---

## 1. Executive summary and core invariants

Phase 12 delivers automated high-availability (HA) leader election, cross-region disaster recovery (DR) WAL replication, and zero-downtime per-tenant cryptographic key rotation across distributed IronLedger clusters. Building upon the Phase 11 multi-tenant federation and canonical `gov.event.v1` event streaming fabric, Phase 12 enables resilient active-passive failover and automated state convergence without violating accounting authority or cryptographic immutability.

### Upstream invariants inherited and enforced

1. **Exact rational integer arithmetic & zero float drift:** All failover timeouts, replica lag calculations, quorum thresholds, and heartbeat intervals compute strictly via integer arithmetic and exact rational numbers ($N / D$). Static AST analysis forbids floating-point division (`/`) and `float()` conversions across all HA, replication, and failover modules.
2. **Zero runtime `import beancount`:** Plaintext Beancount files remain the sole financial authority. Dynamic or direct imports of Beancount remain strictly prohibited.
3. **Monotonic leader epochs & lease fencing:** Cluster primary leases enforce strictly monotonic term counters (`term`) and randomized split-brain fencing tokens (`lease_fence_token`). Expired primary nodes attempting writes fail immediately.
4. **Cryptographic WAL frame checksum chaining:** SQLite WAL frame replication utilizes 32-byte header verification, 24-byte frame header checks, native checksum chaining, and RFC 6962 Merkle tree checkpointing.
5. **Bidirectional divergence detection:** Replicas verify that incoming WAL frame streams share the exact genesis salt and commit page boundaries with the primary before applying frames. Divergence triggers safe isolation and alerts.
6. **Zero-downtime tenant KEK rotation:** Key-encryption keys (KEKs) rotate on demand or per policy. The rotation engine re-wraps data-encryption keys (DEKs) in atomic transactions while active read/write operations continue without disruption.
7. **Append-only governance audit log:** All election events, failover decisions, WAL sync checkpoints, and key rotation lifecycles emit immutable records into `governance_audit_events` and `federated_event_outbox`.
8. **Relational tenant & cluster node isolation:** All failover tables, leases, and checkpoints bind to strict primary and foreign keys (`cluster_id`, `node_id`, `tenant_id`).

---

## 2. Work breakdown structure (WBS)

```
Phase 12: High-Availability Failover Fabric & Cross-Region Disaster Recovery
├── [Task 12.1] Database Schema Migration 0015 (Failover Leases, WAL Checkpoints & Key Rotations)
│   ├── Table: cluster_leader_leases (cluster_id, term, leader_node_id, lease_fence_token, expires_at_utc)
│   ├── Table: replication_wal_checkpoints (cluster_id, node_id, wal_offset_bytes, frame_count, checkpoint_sha256)
│   ├── Table: tenant_key_rotations (tenant_id, kek_key_id, previous_kek_key_id, status, rotated_at_utc)
│   └── Append-Only Triggers for DR Checkpoints and Key Rotation Audit Trails
├── [Task 12.2] Fenced Leader Election & Heartbeat Engine (`src/ironledger/federation/`)
│   ├── election.py: Deterministic term-based leader election, lease acquisition, and renewal
│   ├── heartbeat.py: Background node heartbeat monitor and automatic replica promotion
│   └── Split-Brain Prevention with Monotonic Term Verification
├── [Task 12.3] Cross-Region WAL Replication Fabric (`src/ironledger/replication/`)
│   ├── fabric.py: Streaming WAL frame packaging, checksum validation, and frame extraction
│   ├── sync.py: Point-in-time cross-region state sync and divergence detection
│   └── Merkle-Anchored WAL Checkpoint Verification
├── [Task 12.4] Per-Tenant Key Rotation & Re-Encryption Engine (`src/ironledger/security/`)
│   ├── rotation.py: Tenant-scoped KEK rotation, DEK re-wrapping, and vault migration
│   └── Zero-Downtime Atomic Re-Encryption Pipeline
├── [Task 12.5] REST Endpoints & CLI Failover Controls (`src/ironledger/web/routers/`, `src/ironledger/cli/`)
│   ├── REST: /api/v1/failover/status, /api/v1/failover/promote, /api/v1/security/rotate-key
│   └── CLI: ironledger failover status, ironledger failover promote, ironledger security rotate-key
├── [Task 12.6] Operator Workbench Failover Hub (`web/`)
│   ├── FailoverView.tsx: Quorum status indicator, live replica lag gauges, and manual failover modal
│   └── KEK Rotation Management Panel
└── [Task 12.7] Acceptance Regression Suite & Phase 12 Evidence Sealing
```

---

## 3. Database schema migration (`0015_failover_and_dr.sql`)

Migration 0015 introduces the tables required for distributed leader leasing, replication checkpoints, and key lifecycle management:

```sql
-- Migration 0015: Failover Leases, WAL Replication Checkpoints & Key Rotations

-- 1. Cluster Leader Leases (Fenced Primary Election)
CREATE TABLE IF NOT EXISTS cluster_leader_leases (
    cluster_id TEXT PRIMARY KEY CHECK(length(cluster_id) >= 1 AND length(cluster_id) <= 64),
    term INTEGER NOT NULL DEFAULT 1 CHECK(term >= 1),
    leader_node_id TEXT NOT NULL REFERENCES federation_cluster_nodes(node_id) ON DELETE RESTRICT,
    lease_fence_token TEXT NOT NULL UNIQUE CHECK(length(lease_fence_token) >= 16),
    lease_acquired_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    lease_expires_at_utc TEXT NOT NULL
) STRICT;

-- 2. WAL Replication Checkpoints (Cross-Region Frame Tracking)
CREATE TABLE IF NOT EXISTS replication_wal_checkpoints (
    checkpoint_id TEXT PRIMARY KEY CHECK(length(checkpoint_id) >= 16),
    cluster_id TEXT NOT NULL,
    node_id TEXT NOT NULL REFERENCES federation_cluster_nodes(node_id) ON DELETE RESTRICT,
    wal_offset_bytes INTEGER NOT NULL CHECK(wal_offset_bytes >= 0),
    frame_count INTEGER NOT NULL CHECK(frame_count >= 0),
    salt1 INTEGER NOT NULL,
    salt2 INTEGER NOT NULL,
    checkpoint_sha256 TEXT NOT NULL CHECK(length(checkpoint_sha256) = 64),
    synced_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_wal_checkpoints_node ON replication_wal_checkpoints(cluster_id, node_id, wal_offset_bytes);

-- 3. Tenant Key Rotations (Cryptographic Re-Key Audit)
CREATE TABLE IF NOT EXISTS tenant_key_rotations (
    rotation_id TEXT PRIMARY KEY CHECK(length(rotation_id) >= 16),
    tenant_id TEXT NOT NULL REFERENCES federation_tenants(tenant_id) ON DELETE RESTRICT,
    kek_key_id TEXT NOT NULL,
    previous_kek_key_id TEXT,
    rewrapped_count INTEGER NOT NULL DEFAULT 0 CHECK(rewrapped_count >= 0),
    status TEXT NOT NULL CHECK(status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')),
    rotated_by TEXT NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%fZ', 'now')),
    completed_at_utc TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_tenant_key_rotations ON tenant_key_rotations(tenant_id, created_at_utc);
```

---

## 4. Leader election and failover protocol

```
                   ┌────────────────────────────┐
                   │          FOLLOWER          │
                   └─────────────┬──────────────┘
                                 │ Missed Heartbeat Timeout
                                 ▼
                   ┌────────────────────────────┐
                   │         CANDIDATE          │
                   └─────────────┬──────────────┘
                                 │ Quorum Vote & Lease Acquisition
                                 ▼
                   ┌────────────────────────────┐
                   │           LEADER           │
                   └────────────────────────────┘
```

1. **Heartbeat Monitoring:** Replicas ping the active primary every $T_{	ext{heartbeat}}$ (default: 5,000 ms). If no valid heartbeat arrives within $T_{	ext{lease}}$ (default: 15,000 ms), the replica initiates an election.
2. **Lease Acquisition:** The candidate increments `term`, generates a randomized UUID `lease_fence_token`, and attempts an atomic `INSERT OR REPLACE` into `cluster_leader_leases` conditional on `term > current_term` or expired lease.
3. **Fencing Execution:** All write operations (mutations, compiles, outbox dispatch) verify that their local `lease_fence_token` matches the database lease. If the lease expired or another node acquired a higher term, the write aborts with `LeaderFencedError`.

---

## 5. Rollout safety gates

```
[Gate 1: Schema Integrity] ──► [Gate 2: Election Fencing] ──► [Gate 3: WAL Sync Integrity] ──► [Gate 4: Zero-Downtime Re-Key] ──► [Gate 5: Full Regression]
```

1. **Gate 1 (Schema Integrity):** Migration `0015_failover_and_dr.sql` applies cleanly on existing and clean databases with strict type checks and foreign keys enabled.
2. **Gate 2 (Election Fencing):** Candidate promotion increments terms monotonically. Stale leaders attempting writes are rejected by the fence token invariant.
3. **Gate 3 (WAL Sync Integrity):** Replicas verify frame checksums against the primary stream, successfully detecting frame truncation or salt mismatch.
4. **Gate 4 (Zero-Downtime Re-Key):** Tenant KEK rotation re-wraps 100% of stored DEKs without leaking plaintext secrets or failing active queries.
5. **Gate 5 (Full Regression):** Complete test suite passes with 100% success rate, and frontend builds with 0 TypeScript errors.
