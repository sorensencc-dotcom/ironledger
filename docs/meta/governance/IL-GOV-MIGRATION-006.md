# IronLedger Phase 6 migration checklist & transition plan

- **Document ID**: `IL-GOV-MIGRATION-006`
- **Status**: Ready for Execution
- **Target Release**: Phase 6
- **Prerequisite**: Phase 5 Ratified (`IL-GOV-MANIFEST-005`)

---

## 1. Pre-flight verification checklist

- [ ] Verify local repository is on `main` at `C:\dev\IronLedger` with clean working tree.
- [ ] Confirm Python test suite passes with 100% success (`python -m pytest -q` $\ge 456$ passing).
- [ ] Confirm React 19 SPA compiles cleanly (`npm run build` in `web/`).
- [ ] Confirm Docker background container is healthy (`docker compose ps` shows `running`).

---

## 2. Phase 6 implementation sequence

### Wave 1: Envelope Budgeting Database & Models
- [ ] Create migration `0007_envelopes.sql` with STRICT tables (`envelopes`, `envelope_allocations`, `envelope_transactions`).
- [ ] Implement `src/ironledger/budget/envelope.py` for zero-sum fund allocation math (integer minor units).
- [ ] Add unit tests in `tests/test_envelope_budget.py` validating zero-sum budget conservation.

### Wave 2: Bank Connectors & Ingestion Daemon
- [ ] Define `BankConnector` protocol and abstract connector harness in `src/ironledger/connectors/`.
- [ ] Implement OFX/Plaid mock connector with raw evidence payload archiving in `evidence/connectors/`.
- [ ] Add duplicate detection using FITID trust tables.
- [ ] Add unit tests in `tests/test_connectors.py`.

### Wave 3: Valuation & Multi-Currency Engine
- [ ] Create price map parser in `src/ironledger/valuation/prices.py` without Beancount Python imports.
- [ ] Implement unrealized gain/loss calculation in integer minor units.
- [ ] Add test vectors in `tests/test_valuation.py`.

### Wave 4: Web API & Workbench UI Extensions
- [ ] Implement FastAPI routers: `src/ironledger/web/routers/envelopes.py` and `valuation.py`.
- [ ] Mount new views in `Sidebar.tsx` and `App.tsx` (Envelope Budget View, Net Worth Chart).
- [ ] Build end-to-end integration test suite `tests/test_phase6_e2e.py`.

---

## 3. Exit criteria & sign-off

- [ ] All Phase 6 test suites passing (target $\ge 490$ tests).
- [ ] Zero `import beancount` dependency preserved across all modules.
- [ ] Meta-ledger audit chain verification passes without gap or checksum drift.
- [ ] Formal ratification in `IL-GOV-MANIFEST-006` and `ironledger-phase-6-evidence.md`.
