# IronLedger Phase 6 specification (IL-GOV-SPEC-006)

- **Document ID**: `IL-GOV-SPEC-006`
- **Status**: Proposed / Target Spec
- **Target Phase**: Phase 6 — Enterprise Integrations, Policy Automation, and Envelope Budgeting
- **Domain**: Automated Sync, External Data Connectors, Multi-Currency Revaluation, and Envelope Budgeting Engine
- **Enforcement Level**: Mandatory / Invariant

---

## 1. Executive summary & architectural scope

IronLedger Phase 6 extends the validated Operator Workbench (Phase 5) into an automated, multi-ledger financial operating system. Phase 6 introduces:
1. **Automated Plaid / Bank Ingestion Pipelines**: Background daemon polling, raw payload evidence archiving, and FITID deduplication.
2. **Zero-Sum Envelope Budgeting Engine**: Virtual envelope allocations derived strictly from immutable Beancount equity postings and disposable SQLite budget tables.
3. **Multi-Currency Real-Time Valuation & FX Tracking**: Deterministic price map ingestion and unrealized gain/loss projection calculations.
4. **Governed Automation & Safe Mode Policy Automation**: Policy-driven auto-approval triggers with strict circuit breakers.

---

## 2. Core architectural invariants

Phase 6 strictly adheres to all prior invariants with the following additions:

1. **Beancount as Accounting Ground Truth**:
   - Envelope allocations, revaluations, and automated imports must boil down to plaintext Beancount syntax (`.beancount` files on disk).
   - Zero `import beancount` dependency across all core ingestion, budgeting, and valuation packages.

2. **Strict Minor-Unit Arithmetic**:
   - All envelope budgets, transaction splits, and FX valuations are represented in integer minor units (`int`) with explicit scaling factors.
   - Zero floating-point representation in storage or network interfaces.

3. **Cryptographic Mutation Ledger Anchoring**:
   - Every automated pipeline run or envelope balance adjustment emits an append-only, hash-chained `mutation_events` record with verified before/after state hashes.

4. **Circuit Breakers on Automated Categorization**:
   - Automated approval pipelines halt immediately if rule drift drops below the safety threshold (HCT < 0.70) or override rate exceeds 5.0%.

---

## 3. Envelope budgeting engine specification

### 3.1 Design principles
Envelope budgeting in IronLedger is implemented without modifying Beancount core accounting balances:
- **Available Income Pool**: Sum of liquid asset accounts minus funded envelope liabilities.
- **Envelope State Projections**: Stored in a rebuildable SQLite projection (`envelope_balances`, `envelope_allocations`).
- **Zero-Sum Allocation Contract**: Sum of all envelope allocations in a given accounting period must equal total budgeted funds:
  $$\sum_{i=1}^n \text{Allocated}(E_i) \le \text{AvailableCash}$$

### 3.2 Schema definitions (`0007_envelopes.sql`)
```sql
CREATE TABLE IF NOT EXISTS envelopes (
    envelope_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    target_minor_units INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS envelope_allocations (
    allocation_id TEXT PRIMARY KEY,
    envelope_id TEXT NOT NULL REFERENCES envelopes(envelope_id),
    period_month TEXT NOT NULL, -- YYYY-MM
    allocated_minor_units INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL
) STRICT;
```

---

## 4. Automated ingestion & pipeline connector interface

Connectors implement the `BankConnector` protocol:

```python
class BankConnector(Protocol):
    def fetch_transactions(
        self, start_date: str, end_date: str
    ) -> list[RawTransactionPayload]: ...

    def archive_evidence(
        self, payload: bytes, evidence_dir: Path
    ) -> EvidenceManifest: ...
```

- Raw payloads are permanently stored in `evidence/connectors/<connector_id>/<date>/` with SHA-256 validation.
- Ingested records are placed directly in the `staged_transactions` queue with status `pending`.

---

## 5. Phase 6 Web API extensions

| Router | Method | Path | Description | Gating |
|---|---|---|---|---|
| `envelopes` | `GET` | `/api/envelopes` | List active envelopes & current balances | None |
| `envelopes` | `POST` | `/api/envelopes` | Create a new budget envelope | Safe Mode |
| `envelopes` | `POST` | `/api/envelopes/allocate` | Allocate funds to envelope for period | Safe Mode |
| `connectors` | `GET` | `/api/connectors` | List configured external connectors | None |
| `connectors` | `POST` | `/api/connectors/{id}/sync` | Trigger on-demand sync from bank | Token Gated |
| `valuation` | `GET` | `/api/valuation/summary` | Portfolio net worth across currencies | None |
