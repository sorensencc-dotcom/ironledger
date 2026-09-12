# IronLedger Project Status

## Active Goal
Phase 10: Enterprise Production Hardening, Compliance Auditing & Operational Governance (C:\dev\IronLedger).

## Milestone Status: Gate 1 Planning (Session Kickoff)
- **Preceding Baseline:** Phase 9 ratified, sealed in `docs/meta/phases/ironledger-phase-9-evidence.md`, and released under tag `v0.9.0` (commit `6a9ee90`).
- **Regression Invariant:** 900 passed, 5 skipped (100% pass rate in 31.94s).
- **Current Milestone:** Phase 10 Specification & Architecture Design (Gate 1 Charter).

## Phase 10 Candidate Scope
1. **Compliance & Audit Ledger:** SOC2 / ISO27001 automated compliance reporting, immutable evidence export bundles, and cryptographic archive sealing.
2. **High-Availability & Replication Fabric:** SQLite WAL replication topology, read-replica synchronization, and automated failover recovery.
3. **Advanced Anomaly & Fraud Detection:** Rule-based and heuristic ledger anomaly detector (duplicate charges, anomalous transaction spikes, velocity checks) operating purely on integer arithmetic.
4. **Disaster Recovery & Point-in-Time Restoration:** Cold backup verification harnesses, automated backup rotation, and integrity verification pipelines.
5. **Operator Workbench UI Hardening:** Production static asset compilation, role-gated UI routing, and live WebSocket / SSE notification stream.
6. **Acceptance Regression Suite & Phase 10 Evidence:** Comprehensive end-to-end exit contract tests, static AST guards, and Phase 10 exit documentation.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and KMS/DPAPI key providers.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, and mutation streams.
- **Multi-Tenant Boundaries:** Relational composite primary and foreign keys enforcing isolation.

## Next Action
Draft Phase 10 Specification (`docs/meta/specs/ironledger-phase-10-spec.md`) and Implementation Plan for operator review and Gate 1 ratification.
