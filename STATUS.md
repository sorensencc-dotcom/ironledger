# IronLedger Project Status

## Active Goal
Phase 12: High-Availability Failover Fabric, Cross-Region Disaster Recovery & Tenant Key Rotation (`C:\dev\IronLedger`).

## Milestone Status: Phase 12 Core Engineering Delivered
- **Preceding Baseline:** Phase 11 sealed and ratified (version `v0.11.0`, commit `e2cf9d4`).
- **Regression Invariant:** 947 passed, 5 skipped (100% pass rate in 33.31s).
- **Current Milestone:** Phase 12 Core Engineering Complete (Fenced Leader Election, Monotonic Terms, Cross-Region WAL Replication Checkpointing, Divergence Detection, Zero-Downtime Tenant KEK Rotation, Failover API & CLI, and Operator Workbench Failover Hub).

## Completed Work (Phase 12)
1. **Canonical Phase 12 Specification**: Published `docs/meta/specs/ironledger-phase-12-spec.md` defining monotonic leader terms, randomized fencing tokens, Merkle-anchored SQLite WAL frame bundles, replica divergence assertions, and zero-downtime per-tenant KEK rotation algorithms.
2. **Schema Migration `0015_failover_and_dr.sql`**: Added `cluster_leader_leases` with monotonic terms and lease fence tokens, `replication_wal_checkpoints` for WAL frame offsets and SHA-256 payload hashes, and `tenant_key_rotations` for immutable key rotation audit history.
3. **Fenced Leader Election & Heartbeats (`src/ironledger/federation/`)**:
   - `election.py`: `LeaderElectionEngine` with `acquire_lease`, `renew_lease`, `step_down`, `is_leader`, and `assert_leadership` enforcing monotonic term increments and randomized lease fence tokens.
   - `heartbeat.py`: `HeartbeatMonitor` tracking cluster node health, liveness timeouts, and automated candidate election.
4. **Cross-Region WAL Replication Fabric (`src/ironledger/replication/`)**:
   - `fabric.py`: `WalReplicationFabric` packaging SQLite WAL bytes into verifiable `WalBundle` payloads with frame payload SHA-256 digests and checkpoint persistence.
   - `sync.py`: `ReplicationSynchronizer` detecting stream divergence (`DivergenceDetectedError`) on salt pairs or frame payload hash mismatches.
5. **Per-Tenant Cryptographic Key Rotation (`src/ironledger/security/`)**:
   - `rotation.py`: `TenantKeyRotationEngine` executing atomic zero-downtime KEK rotation and DEK re-wrapping for webhook secrets and connector credentials under fresh IVs and AEAD authentication tags.
6. **REST API & CLI Subcommands (`src/ironledger/web/routers/failover.py`, `src/ironledger/cli/commands/failover.py`)**:
   - API endpoints: `/api/v1/failover/status`, `/api/v1/failover/heartbeat`, `/api/v1/failover/promote`, `/api/v1/security/rotate-key`.
   - CLI commands: `ironledger failover status`, `ironledger failover promote`, `ironledger security rotate-key`.
7. **Operator Workbench Failover Hub (`web/src/components/FailoverView.tsx`)**:
   - Live cluster quorum indicators, leader lease countdown, node replication lag matrix, failover promote modal, and tenant KEK rotation wizard.
8. **Exit Contract & Verification Suite (`docs/meta/contracts/ironledger-phase-12-exit-contract.md`, `evidence/phase-12-evidence.json`, `tests/`)**:
   - `tests/test_phase12_failover.py` & `tests/test_phase12_exit_contract.py`: 100% pass rate across all 947 tests.
   - AST Zero-Float Scan: 100% compliant with zero float division or float conversions.
   - Zero runtime `import beancount` across all codebase modules.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.
- **Fenced HA Quorum:** Monotonic terms and randomized fence tokens preventing split-brain dual primary operations.

## Next Action
Sealed release of Phase 12 milestone (`v0.12.0`).


