# IronLedger Project Status

## Active Goal
Phase 10: Enterprise Production Hardening, Compliance Auditing & Operational Governance (`C:\dev\IronLedger`).

## Milestone Status: Phase 10 Core Engineering Delivered
- **Preceding Baseline:** Phase 9 ratified, sealed in `docs/meta/phases/ironledger-phase-9-evidence.md`, and released under tag `v0.9.0` (commit `6a9ee90`).
- **Regression Invariant:** 925 passed, 5 skipped (100% pass rate in 37.15s).
- **Current Milestone:** Phase 10 Core Engineering Complete (Compliance Audit Engine, Rational Anomaly & Fraud Engine, WAL Frame Inspector, Operator Workbench Option B, and CLI Subcommands).

## Completed Work (Phase 10)
1. **Canonical Phase 10 Specification**: Published `docs/meta/specs/ironledger-phase-10-spec.md` with strict governance invariants, connector federation models, error mapping, and 5-gate rollout safety policy.
2. **Schema Migration `0013_compliance_and_governance.sql`**: Added `compliance_audit_bundles`, append-only `governance_audit_events`, `governance_nonce_registry`, persistent `connector_circuit_breakers`, and `anomaly_flags`.
3. **Compliance Audit Engine (`src/ironledger/compliance/`)**:
   - `merkle.py`: RFC 6962 deterministic binary Merkle tree with domain-separated leaf (`0x00`) and internal node (`0x01`) hashing, odd leaf promotion, and inclusion proof generation.
   - `bundle.py`: Deterministic uncompressed TAR archive packaging with canonical JSONL event streams, non-circular manifest hashing, cryptographic verification, and hostile archive extraction defense.
4. **Pure Rational Anomaly & Fraud Detection Engine (`src/ironledger/governance/anomaly.py`)**:
   - Normalized transaction schema with signed integer cents and UTC ISO timestamps.
   - Exact rational arithmetic ($N/D$, zero float division) with sample variance cross-multiplication formula $(N \cdot x - S)^2 \cdot (N - 1) \cdot k_{\text{den}}^2 > k_{\text{num}}^2 \cdot D$.
   - Four rule types: `DUPLICATE_CHARGE`, `VELOCITY_SPIKE`, `RATIONAL_OUTLIER`, and `UNUSUAL_PAYEE`.
   - Deterministic flag fingerprinting and atomic compare-and-set resolution (`WHERE resolution_status IS NULL`) emitting governance audit trail events.
   - AST scanner verified: strictly zero `/` division and zero `float()` conversions.
5. **High-Availability SQLite WAL Frame Inspector (`src/ironledger/replication/`)**:
   - `wal_parser.py`: 32-byte header parsing supporting dual magic numbers (`0x377f0682` little-endian, `0x377f0683` big-endian), 24-byte frame header parsing, native checksum chaining, commit page count validation, and replica synchronization state model.
6. **CLI Subcommands (`src/ironledger/cli/commands/`)**:
   - `ironledger compliance generate` & `ironledger compliance verify`.
   - `ironledger anomaly scan`, `ironledger anomaly list`, and `ironledger anomaly resolve`.
7. **Operator Workbench UI Modernization (`web/`)**:
   - `ConnectorsView.tsx`: Live circuit breaker state pills, rate limit gauges, credential vault status, sync timeline, and manual execution triggers.
   - `WebhooksPanel.tsx`: Subscriptions registry with modal, delivery queue monitor, and DLQ drill-down inspector with one-click atomic redrive.
   - `MetricsView.tsx`: Prometheus / OpenMetrics `/metrics` parser and telemetry dashboard with request counters, latency percentiles, and subsystem gauges.
   - `TopHUD.tsx` & `Sidebar.tsx`: Added health/readiness probe pill, envelope encryption status widget, version bump to `v0.10.0`, and navigation routes.
8. **Verification & Regression Matrix**:
   - `python -m pytest`: 925 passed, 5 skipped (100% pass rate).
   - `npm --prefix web run build`: Clean TypeScript compilation, Vite production assets bundled to `web/dist/`.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite primary and foreign keys enforcing strict ledger isolation.

## Next Action
Finalize Phase 10 exit contracts and sign off milestone.
