# IronLedger Project Status

## Active Goal
Phase 11: Multi-Tenant Federation, Cross-Cluster Audit Propagation & Federated Event Streaming (`C:\dev\IronLedger`).

## Milestone Status: Phase 11 Core Engineering Delivered
- **Preceding Baseline:** Phase 10 signed off (commit `86c1003`).
- **Regression Invariant:** 934 passed, 5 skipped (100% pass rate in 41.45s).
- **Current Milestone:** Phase 11 Core Engineering Complete (Canonical Event Model `gov.event.v1`, Dual-Emission Event Router, Fenced Outbox Dispatcher, Peer Ingestion Idempotency, Cross-Cluster Merkle Inclusion Proofs, REST Endpoints, CLI Subcommands, and Workbench Federation View).

## Completed Work (Phase 11)
1. **Canonical Phase 11 Specification**: Published `docs/meta/specs/ironledger-phase-11-spec.md` defining the `gov.event.v1` event model, domain event families (compliance, anomaly, replication, connectors, webhooks, system), fenced outbox leasing invariants, and multi-tenant federation architecture.
2. **Schema Migration `0014_multi_tenant_federation.sql`**: Added `federation_tenants`, `federation_cluster_nodes`, append-only `federated_event_outbox` with fenced worker leasing (`lease_owner_id`, `lease_fence_token`, `lease_expires_at_utc`), and `peer_ingested_events` idempotency table.
3. **Canonical Event Envelope & Router (`src/ironledger/events/`)**:
   - `envelope.py`: Dataclass `FederatedEvent` with strict schema validation (`gov.event.v1`), RFC 3339 timestamps, domain validation, and canonical JSON serialization for SHA-256 fingerprinting.
   - `router.py`: Atomic dual-emission router persisting canonical events to `federated_event_outbox` and `governance_audit_events`.
   - `dispatcher.py`: Fenced lease outbox worker (`claim_batch`, `acknowledge_batch`) and idempotent peer ingestion (`ingest_peer_event`), preserved along with Phase 9 `WebhookDispatcher`.
4. **Cross-Cluster Compliance Verification (`src/ironledger/compliance/federation.py`)**:
   - Inclusion proof bundle packaging and witness verification allowing independent clusters to verify bundle integrity against published Merkle roots without transferring full archives.
5. **REST API & CLI Subcommands (`src/ironledger/web/routers/federation.py`, `src/ironledger/cli/commands/federation.py`)**:
   - API endpoints for tenant registry, cluster topology, outbox querying, and peer event ingestion.
   - CLI commands: `ironledger federation nodes list`, `ironledger federation outbox list`, and `ironledger federation outbox dispatch`.
6. **Operator Workbench UI Modernization (`web/`)**:
   - `FederationView.tsx`: Tenant selector dropdown, peer cluster topology status cards, and live outbox event stream with status badges and payload inspectors.
   - `Sidebar.tsx` & `App.tsx`: Wired Federation tab and router navigation.
7. **Verification & Regression Matrix**:
   - `python -m pytest`: 934 passed, 5 skipped (100% pass rate).
   - `npm --prefix web run build`: Clean TypeScript compilation, Vite production bundle generated.
   - AST Zero-Float Scan: 100% compliant with zero float division or float conversions.

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite keys and tenant registries enforcing strict ledger isolation.

## Next Action
Review and release Phase 11 milestone.

