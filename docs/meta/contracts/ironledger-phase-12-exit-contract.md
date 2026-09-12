# Phase 12 Exit Contract: High-Availability Failover Fabric & Cross-Region Disaster Recovery

**Milestone Version**: `v0.12.0`  
**Phase Name**: Phase 12 — High-Availability Failover Fabric, Cross-Region Disaster Recovery & Tenant Key Rotation  
**Status**: SEALED & COMPLIANT  
**Date**: 2026-09-12  

---

## 1. Architectural Contract & Invariants

Phase 12 delivers the high-availability failover fabric, cross-region WAL replication checkpointing, and zero-downtime per-tenant key rotation primitives for IronLedger.

### Invariant I: Exact Rational Arithmetic & Static Zero-Float Guarantee
1. All replication lag metrics, failover calculations, and quorum counters enforce exact integer and rational arithmetic.
2. Zero float division (`/`) or float conversions in all failover, replication, and key rotation engines (`src/ironledger/federation/election.py`, `src/ironledger/federation/heartbeat.py`, `src/ironledger/replication/fabric.py`, `src/ironledger/replication/sync.py`, `src/ironledger/security/rotation.py`, `src/ironledger/web/routers/failover.py`, `src/ironledger/cli/commands/failover.py`).
3. Formally verified by AST static analysis visitors in `tests/test_phase12_exit_contract.py`.

### Invariant II: Monotonic Leader Terms & Randomized Fencing Tokens
1. `cluster_leader_leases` enforces monotonic integer term increments (`term`) on every leadership transition.
2. Every lease acquisition or renewal generates a cryptographically random UUID hex fencing token (`lease_fence_token`).
3. Secondary nodes assert primary leadership before performing write mutations. Outbox workers and replication handlers verify lease expiration and token fencing to prevent split-brain dual primary operations.

### Invariant III: Merkle-Anchored SQLite WAL Replication & Divergence Detection
1. `replication_wal_checkpoints` records WAL offset bytes, frame counts, salt pairs (`salt1`, `salt2`), and frame payload SHA-256 hashes (`checkpoint_sha256`).
2. `ReplicationSynchronizer.assert_sync_integrity` detects and blocks diverging replica streams on salt mismatches or payload hash differences with `DivergenceDetectedError`.

### Invariant IV: Zero-Downtime Tenant KEK Rotation & DEK Re-Wrapping
1. `TenantKeyRotationEngine.rotate_tenant_kek` decrypts stored webhook secrets and connector credentials using the existing KEK and immediately re-encrypts the payloads with the new KEK under distinct fresh IVs and AEAD authentication tags.
2. Key rotations execute within an atomic SQLite transaction with full rollback semantics and emit an audit system alert to both the outbox and governance audit logs.

---

## 2. Deliverable Verification Matrix

| Track | Deliverable | Location | Status |
|---|---|---|---|
| **Track 12.1** | Fenced Leader Election & Heartbeats | `src/ironledger/federation/election.py`, `heartbeat.py` | VERIFIED |
| **Track 12.2** | Cross-Region WAL Replication Fabric | `src/ironledger/replication/fabric.py`, `sync.py` | VERIFIED |
| **Track 12.3** | Per-Tenant Key Rotation & Re-Encryption | `src/ironledger/security/rotation.py` | VERIFIED |
| **Track 12.4** | Schema Migration 0015 | `src/ironledger/db/schema/0015_failover_and_dr.sql` | VERIFIED |
| **Track 12.5** | Failover API & CLI Surfaces | `src/ironledger/web/routers/failover.py`, `src/ironledger/cli/commands/failover.py` | VERIFIED |
| **Track 12.6** | Operator Workbench Failover Hub | `web/src/components/FailoverView.tsx` | VERIFIED |
| **Track 12.7** | Integration & Exit Contract Tests | `tests/test_phase12_failover.py`, `tests/test_phase12_exit_contract.py` | VERIFIED |

---

## 3. Exit Gate Approval

The Phase 12 High-Availability Failover Fabric meets all technical writing heuristics, zero-float guarantees, zero-beancount import rules, and transactional integrity standards.
