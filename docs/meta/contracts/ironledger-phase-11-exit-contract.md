# IronLedger Phase 11 exit contract

- **Status**: Ratified
- **Milestone**: Phase 11 (Multi-Tenant Federation, Cross-Cluster Audit Propagation & Federated Event Streaming)
- **Baseline Commit**: `066be54` on branch `main`
- **Specification**: `docs/meta/specs/ironledger-phase-11-spec.md`
- **D-0 Contract**: Local repository `C:\dev\IronLedger`, branch `main`, no remote, do not push.

---

## 1. Executive contract scope

Phase 11 establishes multi-tenant cluster federation, canonical event streaming (`gov.event.v1`), dual-emission event routing, randomized lease-fenced outbox dispatching, idempotent peer ingestion, and cross-cluster Merkle inclusion proof verification.

To satisfy the Phase 11 exit criteria, the implementation must enforce all core architectural invariants, pass 100% of automated unit and integration tests, compile the web frontend with zero TypeScript errors, and satisfy the 5 rollout safety gates.

---

## 2. Core architectural invariants

| Invariant | Standard | Enforcement Mechanism | Verification Criteria |
|---|---|---|---|
| **1. Zero Float Drift** | Exact rational integer arithmetic ($N/D$, signed cents, integer basis points). | Static AST scanner (`tests/test_federation_events.py`). | 0 float division (`/`), 0 `float()`, 0 `Decimal` occurrences in federation/event modules. |
| **2. Zero Runtime Beancount Import** | Zero runtime `import beancount` or dynamic `importlib` calls. | Static AST analysis visitor scanning `src/ironledger/`. | 0 occurrences across `src/ironledger/`. |
| **3. Fenced Outbox Leases** | Randomized fencing token (`lease_fence_token`) and integer lease timeout. | `OutboxDispatcher.claim_batch` and `acknowledge_batch`. | Expired lease acknowledgements return 0 affected rows; zero double-dispatch across distributed workers. |
| **4. Peer Ingestion Idempotency** | Duplicate peer event deliveries rejected without side effects. | `peer_ingested_events` composite primary key `(cluster_id, event_id)`. | Repeated ingestion returns `False` and skips local audit insertion. |
| **5. Cross-Cluster Merkle Verification** | Remote witness verification of inclusion proofs without transmitting full archive bundles. | `verify_witness_bundle_proof` in `src/ironledger/compliance/federation.py`. | Valid proofs return `True`; altered leaves or invalid roots return `False`. |
| **6. Append-Only Immutability** | Federated event outbox and governance audit logs reject update/deletion. | SQLite `BEFORE DELETE` triggers. | Direct `DELETE` queries raise abort database exceptions. |

---

## 3. Rollout safety gates

```
[Gate 1: Schema & Triggers] ──► [Gate 2: Envelope Validation] ──► [Gate 3: Fenced Dispatch] ──► [Gate 4: Peer Idempotency] ──► [Gate 5: Full Regression]
```

1. **Gate 1 (Schema & Triggers):** Migration `0014_multi_tenant_federation.sql` applies cleanly on fresh and migrated databases. Append-only triggers abort `DELETE` statements on `federated_event_outbox`.
2. **Gate 2 (Envelope Validation):** `FederatedEvent` validates ISO 8601 UTC timestamps, canonical sources, recognized event types, and deterministic SHA-256 fingerprinting.
3. **Gate 3 (Fenced Outbox Dispatch):** Outbox workers acquire batches with distinct fencing tokens; expired lease acks safely no-op without corrupting newer worker claims.
4. **Gate 4 (Peer Idempotency & Proofs):** Peer clusters ingest events idempotently, rejecting duplicates and verifying Merkle inclusion proofs for compliance records.
5. **Gate 5 (Full Regression & Build):** All pytest suites pass with 100% success rate, and `npm --prefix web run build` produces production assets with 0 TypeScript errors.

---

## 4. Verification commands

To verify compliance with this contract, execute:

```powershell
# 1. Mandatory repository preflight
pwsh -NoProfile -File C:\dev\scripts\verify-repo-context.ps1 -Path C:\dev\IronLedger

# 2. Complete test suite
python -m pytest

# 3. Phase 11 specific contract tests
python -m pytest tests/test_federation_events.py tests/test_federation_web_cli.py tests/test_phase11_exit_contract.py -v

# 4. Frontend production compilation
npm --prefix web run build
```

---

## 5. Exit sign-off

Execution of all verification commands without errors confirms full satisfaction of the Phase 11 Exit Contract.
