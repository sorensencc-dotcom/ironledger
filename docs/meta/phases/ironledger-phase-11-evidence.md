# IronLedger Phase 11 evidence and exit verification

- **Status**: Phase 11 multi-tenant federation, canonical event model (`gov.event.v1`), fenced outbox dispatcher, cross-cluster compliance verification, and Operator Workbench federation view verified on 2026-09-11.
- **Scope**: Migration `0014_multi_tenant_federation.sql`, Event Envelope & Router (`src/ironledger/events/`), Compliance Federation (`src/ironledger/compliance/federation.py`), Federation Routers (`src/ironledger/web/routers/federation.py`), CLI Commands (`src/ironledger/cli/commands/federation.py`), Operator Workbench (`web/src/components/FederationView.tsx`), Unit & Integration Test Suites (`tests/test_federation_events.py`, `tests/test_federation_web_cli.py`, `tests/test_phase11_exit_contract.py`), and Specification (`docs/meta/specs/ironledger-phase-11-spec.md`).
- **Commit**: `066be54` on branch `main`.
- **D-0 Contract**: Local repository `C:\dev\IronLedger`, branch `main`, no remote, do not push.

---

## 1. Executive sign-off and ratification

Phase 11 delivers multi-tenant federation, canonical event envelopes (`gov.event.v1`), dual-emission event routing, lease-fenced outbox dispatching preventing distributed double-dispatch, idempotent peer ingestion registry, cross-cluster Merkle inclusion proof verification, REST endpoints, CLI administration commands, and a modernized local-first Operator Workbench Federation view.

All deliverables have passed validation with 100% test pass rates across the 934-test regression suite.

Phase 11 specification and implementation are formally ratified.

---

## 2. Verification of core architectural invariants

| Invariant | Policy | Enforcement Mechanism | Verification Result |
|---|---|---|---|
| **1. Zero Runtime Beancount Import** | Zero runtime `import beancount` or dynamic `importlib` calls targeting Beancount across application source code. | Static AST analysis visitor scanning all `.py` files under `src/ironledger/`. | **PASS**: 0 occurrences of direct, aliased, dynamic, or `getattr` Beancount imports across `src/ironledger/`. |
| **2. Pure Integer Rational Arithmetic** | Zero floating-point drift in federation, event routing, lease durations, or sequence calculations. | Integer rational arithmetic (`//`, `divmod`, `math.gcd`), integer millisecond timestamps, and AST `ast.Div` scanner. | **PASS**: Validated in `tests/test_federation_events.py` and full test suite. |
| **3. Fenced Outbox Leases** | Outbox workers acquire batches with distinct fencing tokens preventing expired workers from acknowledging re-assigned batches. | `OutboxDispatcher.claim_batch` and `OutboxDispatcher.acknowledge_batch`. | **PASS**: Validated in `tests/test_federation_events.py`. |
| **4. Peer Ingestion Idempotency** | Peer clusters ingest federated events idempotently; duplicate events are recorded once and deduplicated. | `peer_ingested_events` composite key `(cluster_id, event_id)`. | **PASS**: Validated in `tests/test_federation_events.py` and `tests/test_federation_web_cli.py`. |
| **5. Cross-Cluster Merkle Verification** | Remote witness nodes verify compliance bundle inclusion proofs without transmitting entire raw archives. | RFC 6962 inclusion proofs in `src/ironledger/compliance/federation.py`. | **PASS**: Validated in `tests/test_federation_events.py`. |
| **6. Append-Only Immutability** | Federated event outbox and governance audit logs strictly reject update and deletion operations. | SQLite `BEFORE DELETE` triggers. | **PASS**: Validated in `tests/test_federation_events.py`. |

---

## 3. Comprehensive test suite summary

- **Toolchain**: Python 3.14.6, pytest 9.1.1, SQLite 3.50.4, Node.js v22.10.0, Vite 6.4.3.
- **Python Regression Suite**: **934 passed, 5 skipped in 41.45s** (100% pass rate).
- **Frontend Production Build**: `npm --prefix web run build` passed with **0 TypeScript errors** generating `web/dist/index.html` (0.82 kB) and asset bundles.

---

## 4. Rollout safety gates evidence

```
[Gate 1: Schema & Triggers] ──► [Gate 2: Envelope Validation] ──► [Gate 3: Fenced Dispatch] ──► [Gate 4: Peer Idempotency] ──► [Gate 5: Full Regression]
```

1. **Gate 1 (Schema & Triggers):** Migration `0014_multi_tenant_federation.sql` created `federation_tenants`, `federation_cluster_nodes`, `federated_event_outbox`, and `peer_ingested_events`. Triggers correctly prevent deletion on the outbox. **Status: VERIFIED**.
2. **Gate 2 (Envelope Validation):** `FederatedEvent` schema validates ISO 8601 timestamps, source categories, severity levels, and payload structures with deterministic canonical JSON serialization. **Status: VERIFIED**.
3. **Gate 3 (Fenced Outbox Dispatch):** Workers claim batches with monotonic sequence ordering and randomized UUID fence tokens; expired lease acknowledgement safely updates 0 rows. **Status: VERIFIED**.
4. **Gate 4 (Peer Idempotency & Proofs):** Repeated deliveries to `/api/v1/federation/events/ingest` return `ingested: false`, and witness proof verifications confirm Merkle integrity without full data transfers. **Status: VERIFIED**.
5. **Gate 5 (Full Regression & Build):** All 934 tests passing, TypeScript compilation clean, zero float violations across all federation components. **Status: VERIFIED**.

---

## 5. Frontend production build artifacts

- `dist/index.html`: `0.82 kB` (gzip: `0.46 kB`)
- `dist/assets/index-CDFonYvn.css`: `25.78 kB` (gzip: `5.32 kB`)
- `dist/assets/index-Baea3lGh.js`: `332.31 kB` (gzip: `91.57 kB`)
