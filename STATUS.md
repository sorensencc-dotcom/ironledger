# IronLedger Project Status

## Active Goal
Phase 10: Enterprise Production Hardening, Compliance Auditing & Operational Governance (`C:\dev\IronLedger`).

## Milestone Status: Phase 10 Specification Ratified & Option B Modernization Delivered
- **Preceding Baseline:** Phase 9 ratified, sealed in `docs/meta/phases/ironledger-phase-9-evidence.md`, and released under tag `v0.9.0` (commit `6a9ee90`).
- **Regression Invariant:** 905 passed, 5 skipped (100% pass rate in 30.08s).
- **Current Milestone:** Phase 10 Specification Ratified (`docs/meta/specs/ironledger-phase-10-spec.md`) & Option B Frontend Modernization Complete.

## Completed Work (Phase 10 Foundation & Option B)
1. **Canonical Phase 10 Specification**: Published `docs/meta/specs/ironledger-phase-10-spec.md` with strict governance invariants, connector federation models, and 5-gate rollout safety policy.
2. **Schema Migration `0013_compliance_and_governance.sql`**: Added `compliance_audit_bundles`, append-only `governance_audit_events`, `governance_nonce_registry`, persistent `connector_circuit_breakers`, and `anomaly_flags`.
3. **Backend Governance Routers & Error Taxonomy**:
   - `src/ironledger/web/errors.py`: Unified governance error envelopes (`GOVERNANCE_VALIDATION_ERROR`, `GOVERNANCE_CIRCUIT_OPEN`, `GOVERNANCE_DLQ_REDRIVE_DENIED`, etc.).
   - `src/ironledger/web/routers/connectors.py`: Multi-protocol connector provider registry, circuit breaker state tracking, envelope credential status (zero plaintext leakage), sync timeline, and idempotency-protected manual sync triggers.
   - `src/ironledger/web/routers/webhooks.py`: Webhook subscription registry with SSRF private-IP validation, delivery queue tracking with lease fencing, and atomic DLQ redrive.
   - `src/ironledger/web/app.py`: Mounted governance routers and `web/dist/` static files handler.
4. **Operator Workbench UI Modernization (`web/`)**:
   - `ConnectorsView.tsx`: Live circuit breaker state pills (`CLOSED`, `OPEN`, `HALF_OPEN`), rate limit gauges, credential vault status, sync timeline, and manual execution triggers.
   - `WebhooksPanel.tsx`: Subscriptions registry with modal, delivery queue monitor, and DLQ drill-down inspector with one-click atomic redrive.
   - `MetricsView.tsx`: Prometheus / OpenMetrics `/metrics` parser and telemetry dashboard with request counters, latency percentiles, and subsystem gauges.
   - `TopHUD.tsx` & `Sidebar.tsx`: Added health/readiness probe pill, envelope encryption status widget, version bump to `v0.10.0`, and navigation routes.
   - `api.ts` & `types.ts`: Strongly-typed API client bindings with idempotency key generation and `X-IronLedger-Op-Token` headers.
5. **Production Build & Verification**:
   - `npm run build` in `web/` verified: TypeScript compilation clean, Vite bundled `web/dist/index.html` (0.82 kB) and assets (340 kB).
   - Test suite: 905 passed, 5 skipped (100% pass rate).

## Core Architectural Invariants Maintained
- **Plaintext Ground Truth:** Plaintext Beancount files remain the sole financial authority.
- **Decoupled Runtime:** Zero runtime `import beancount` enforced via static AST visitor.
- **Pure Integer Arithmetic:** Exact rational arithmetic without float representation or drift.
- **Envelope Encryption:** AES-256-GCM with separate IV/auth tags and zero plaintext payload leakage.
- **Append-Only Immutability:** SQLite triggers guarding outbox, audit, mutation, and governance event streams.
- **Multi-Tenant Boundaries:** Relational composite primary and foreign keys enforcing strict ledger isolation.

## Next Action
Implement Task 10.1 (Compliance Audit Engine & Sealed Evidence Archive Bundles) and Task 10.2 (High-Availability WAL Replication & Failover Fabric).
