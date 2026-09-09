# IronLedger mutation ledger governance specification

- **Document ID**: `IL-GOV-MUTATION-001`
- **Status**: Ratified
- **Domain**: Cryptographic State Tracking, Immutability, and Append-Only Audit Integrity
- **Enforcement Level**: Invariant / Non-Bypassable

---

## 1. Overview & mathematical model

The IronLedger Meta-Ledger (`mutation_events` table) maintains a deterministic, cryptographically hash-chained record of all state transitions affecting the ledger disk files, rules, and staged transactions.

Each mutation event $E_k$ in sequence $k \in \mathbb{N}$ satisfies:

$$H_k = \text{SHA-256}\Big(\text{canonical\_json}\big(\text{seq}_k, \text{id}_k, \text{ts}_k, \text{actor}_k, \text{action}_k, C_{\text{staged}}, C_{\text{applied}}, C_{\text{created}}, S_{\text{before}}, S_{\text{after}}, H_{k-1}\big)\Big)$$

Where:
- $H_0 = \text{"0"}^{64}$ (Genesis previous hash).
- $S_{\text{before}}$ and $S_{\text{after}}$ represent the SHA-256 digest of the entire on-disk ledger directory.

---

## 2. Database schema and strict immutability triggers

The `mutation_events` table is created under migration `0006_mutation_events.sql` with STRICT table typing and SQLite triggers preventing any in-place modification or record deletion.

```sql
CREATE TABLE IF NOT EXISTS mutation_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    mutation_id TEXT NOT NULL UNIQUE,
    ts_utc TEXT NOT NULL,
    operator_session TEXT NOT NULL,
    action TEXT NOT NULL,
    staged_count INTEGER NOT NULL,
    rules_applied INTEGER NOT NULL,
    rules_created INTEGER NOT NULL,
    sha256_before TEXT NOT NULL,
    sha256_after TEXT NOT NULL,
    prev_mutation_hash TEXT NOT NULL,
    mutation_hash TEXT NOT NULL UNIQUE
) STRICT;

CREATE TRIGGER IF NOT EXISTS trg_mutation_events_no_update
BEFORE UPDATE ON mutation_events
BEGIN
    SELECT RAISE(ABORT, 'mutation_events table is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_mutation_events_no_delete
BEFORE DELETE ON mutation_events
BEGIN
    SELECT RAISE(ABORT, 'mutation_events table is append-only: DELETE forbidden');
END;
```

---

## 3. Invariants & audit guarantees

1. **Unbroken Chain Verification**:
   - The entire chain can be audited at any time via `ironledger.mutation.verify_mutation_chain(conn)`.
   - Any modification to sequence numbers, timestamps, hashes, or counts produces an immediate checksum mismatch error.

2. **Zero In-Place Mutation**:
   - `UPDATE` and `DELETE` queries executed against `mutation_events` raise `sqlite3.IntegrityError` (via SQLite `RAISE(ABORT)`).

3. **Compiler Integration**:
   - Every execution of `ironledger.compile.writer.compile_approved()` automatically computes `sha256_before` from disk, writes the approved plaintext transactions, computes `sha256_after`, and records a new mutation event in the chain.
