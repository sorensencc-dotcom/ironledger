# Phase 8 Specification: Multi-Asset Valuation, Ledger Lineage & Audit Replay

**Program:** IronLedger  
**Milestone:** Phase 8 — Multi-Asset Valuation, Ledger Lineage & Audit Replay  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-10  
**Status:** Approved Design Specification  

---

## 1. Executive Summary & Core Invariants

Phase 8 expands IronLedger from single-currency transaction recording into a multi-asset valuation, bi-directional lineage tracking, multi-tenant ledger isolation, deterministic point-in-time audit replay, and cryptographic capability-based access control engine.

### Upstream Invariants Inherited & Enforced

1. **Exact Rational Integer Arithmetic:** Multi-asset and commodity conversions operate exclusively on integer minor units and rational fraction ratios $(N / D)$. Floating-point floats (`float`) are strictly forbidden.
2. **Bi-Directional Provenance Lineage:** Every compiled posting references its staged transaction, source record, and raw evidence SHA-256 blob through a directed acyclic graph (DAG) stored in SQLite.
3. **Deterministic Point-in-Time Replay:** The mutation ledger chain ($H_0 \to H_k$) can be replayed into an ephemeral in-memory projection database to reconstruct exact historical state snapshots at any sequence number without mutating live files.
4. **Tenant & Entity Domain Isolation:** Explicit `ledger_id` column boundaries enforce strict isolation across staging buffers, price histories, and compilation mutex lockfiles (`.ironledger/.compile.<ledger_id>.lock`).
5. **Zero Runtime `import beancount`:** All Beancount commodity and price directives are generated via deterministic string template emission with zero Beancount imports.
6. **Scoped Capability RBAC:** Granular cryptographic capability tokens authorize actions with fail-closed default-deny enforcement.

---

## 2. Work Breakdown Structure (WBS)

```
Phase 8: Lineage, Valuation & Replay Engine
├── [Task 8.1] Multi-Asset Valuation Engine & Price Directives Cache
├── [Task 8.2] Ledger Lineage Explorer & Bi-Directional Provenance DAG
├── [Task 8.3] Multi-Ledger Topology & Isolated Staging Queues
├── [Task 8.4] Deterministic Audit Replay & Point-in-Time Time Travel
├── [Task 8.5] Scoped Capability Tokens & RBAC Policy Enforcement
└── [Task 8.6] Acceptance Regression Suite & Phase 8 Exit Evidence
```

---

## 3. Database Schema Architecture

Phase 8 additions are split across modular migrations:

### Migration `0008_price_history.sql` (Task 8.1)
```sql
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default',
    directive_date TEXT NOT NULL,          -- ISO 8601 YYYY-MM-DD
    base_currency TEXT NOT NULL,           -- e.g. 'AAPL', 'EUR', 'BTC'
    quote_currency TEXT NOT NULL,          -- e.g. 'USD'
    rate_numerator INTEGER NOT NULL,       -- e.g. 22550 for $225.50
    rate_denominator INTEGER NOT NULL,     -- e.g. 100
    source TEXT NOT NULL,                  -- e.g. 'MANUAL', 'POLLED_FEED', 'EXCHANGE_API'
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE(ledger_id, directive_date, base_currency, quote_currency)
);

CREATE INDEX IF NOT EXISTS idx_price_history_lookup 
ON price_history(ledger_id, base_currency, quote_currency, directive_date DESC);
```

### Migration `0009_ledger_lineage.sql` (Task 8.2)
```sql
CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_id TEXT PRIMARY KEY,              -- SHA-256 or entity UUID
    node_type TEXT NOT NULL,               -- 'POSTING', 'STAGED_TX', 'SOURCE_RECORD', 'EVIDENCE_BLOB'
    entity_ref TEXT NOT NULL,              -- Target ID (posting_id, tx_id, record_id, or blob sha256)
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship TEXT NOT NULL,            -- 'COMPILED_FROM', 'STAGED_FROM', 'EXTRACTED_FROM'
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(source_node_id, target_node_id, relationship),
    FOREIGN KEY(source_node_id) REFERENCES lineage_nodes(node_id) ON DELETE CASCADE,
    FOREIGN KEY(target_node_id) REFERENCES lineage_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lineage_edges_forward ON lineage_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_backward ON lineage_edges(target_node_id);
```

### Migration `0010_multi_ledger_rbac.sql` (Tasks 8.3 & 8.5)
```sql
CREATE TABLE IF NOT EXISTS ledgers (
    ledger_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default', 'Default Ledger', 'USD');

CREATE TABLE IF NOT EXISTS capability_tokens (
    token_id TEXT PRIMARY KEY,             -- UUID / Unique Token ID
    token_hash TEXT NOT NULL UNIQUE,       -- SHA-256 of the bearer token string
    ledger_id TEXT NOT NULL,               -- Scoped ledger ID or '*' for all
    role TEXT NOT NULL,                    -- 'READER', 'OPERATOR', 'COMPILER', 'ADMIN'
    capabilities_json TEXT NOT NULL,       -- JSON Array of string scopes
    expires_at TEXT,                       -- ISO 8601 or NULL for non-expiring
    revoked_at TEXT,                       -- Revocation timestamp if invalidated
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    FOREIGN KEY(ledger_id) REFERENCES ledgers(ledger_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_token_hash_lookup ON capability_tokens(token_hash);
```

---

## 4. Subsystem Detailed Specifications

### Task 8.1: Multi-Asset Valuation Engine & Historical Price Directives
* **Location:** `src/ironledger/valuation/engine.py`, `src/ironledger/valuation/models.py`
* **Mathematical Conversion Formula:**
  $$\text{Target Minor Units} = \left\lfloor \frac{\text{Source Minor Units} \times \text{Numerator Price}}{\text{Denominator Unit Base} \times 10^{(\text{source\_decimals} - \text{target\_decimals})}} \right\rfloor$$
* **Price Resolution Policy:** Bounded preceding lookup on `directive_date <= requested_date` within a configurable maximum staleness window (`max_staleness_days = 30`). Missing or stale prices raise `MissingPriceDirectiveError` or `StalePriceDirectiveError`.
* **Zero-Import Directives:** Template-based emission of Beancount format: `YYYY-MM-DD price <COMMODITY> <PRICE_DECIMAL> <QUOTE_CURRENCY>`.

### Task 8.2: Ledger Lineage Explorer & Bi-Directional Provenance DAG
* **Location:** `src/ironledger/lineage/explorer.py`, `src/ironledger/lineage/dag.py`
* **Lineage Layers:** `EVIDENCE_BLOB` $\xrightarrow{\text{EXTRACTED\_FROM}}$ `SOURCE_RECORD` $\xrightarrow{\text{STAGED\_FROM}}$ `STAGED_TX` $\xrightarrow{\text{COMPILED\_FROM}}$ `POSTING`.
* **Recursive Resolution:** SQLite recursive Common Table Expressions (`WITH RECURSIVE`) resolving complete upstream and downstream traversal trees in a single query.
* **Auto-Edge Recording:** Integration hooks in staging pipeline and compile writer record DAG nodes and edges synchronously during mutations.

### Task 8.3: Multi-Ledger Topology & Isolated Staging Queues
* **Location:** `src/ironledger/ledger/topology.py`, `src/ironledger/ledger/staging.py`
* **Tenant Isolation:** Explicit `ledger_id` parameter required on all staging, review, and compile operations.
* **Compile Mutex Locking:** Per-ledger mutex lockfiles `.ironledger/.compile.<ledger_id>.lock` ensure independent compilation across entities.
* **Consolidation Engine:** Read-only multi-entity balance aggregation normalizing asset values into a designated base currency using Task 8.1 valuation routines.

### Task 8.4: Deterministic Audit Replay & Point-in-Time Time Travel
* **Location:** `src/ironledger/replay/engine.py`, `src/ironledger/replay/snapshot.py`
* **Hash-Chain Verification:** Validates Merkle links ($H_i = \text{SHA-256}(H_{i-1} \parallel \text{payload}_i)$) before replaying.
* **Hermetic Projection:** Instantiates an in-memory SQLite database (`:memory:`), applies mutations sequentially up to `target_sequence` or `target_timestamp`, and produces exact bit-for-bit point-in-time balance and staging snapshots.
* **Zero Mutation Guarantee:** Live ledger state and SQLite files are strictly read-only during replay.

### Task 8.5: Scoped Capability Tokens & RBAC Policy Enforcement
* **Location:** `src/ironledger/auth/capabilities.py`, `src/ironledger/auth/policy.py`
* **Token Format:** Cryptographic bearer tokens (`il_cap_<hex32>`), stored only as SHA-256 hashes.
* **Capability Matrix:**
  - `ledger:read`, `staging:write`, `review:decide`, `compile:execute`, `audit:replay`, `admin:*`.
* **Policy Interceptors:** CLI and API middleware enforce fail-closed authorization checks before executing any bounded command.

### Task 8.6: Acceptance Regression Suite & Phase 8 Exit Evidence
* **Location:** `tests/test_valuation.py`, `tests/test_lineage.py`, `tests/test_multi_ledger.py`, `tests/test_replay.py`, `tests/test_capabilities.py`, `tests/test_phase8_exit_contract.py`
* **Evidence File:** `docs/meta/phases/ironledger-phase-8-evidence.md`

---

## 5. Verification & Test Plan

1. **Valuation Suite (`tests/test_valuation.py`):**
   - Verify integer rational price conversion with 0 floating-point drift across mixed decimal precisions (USD 2-dec, BTC 8-dec, AAPL 4-dec).
   - Verify bounded preceding price resolution, stale price rejection, and inverse quote resolution.
   - Verify Beancount price directive string template output with zero runtime Beancount imports.
2. **Lineage Suite (`tests/test_lineage.py`):**
   - Verify bi-directional recursive CTE DAG traversals (posting $\to$ evidence hash, and evidence hash $\to$ postings).
   - Verify cycle prevention and cascade deletion safety.
3. **Multi-Ledger Suite (`tests/test_multi_ledger.py`):**
   - Verify complete isolation of staging queues and concurrent compilation locks across multiple `ledger_id`s.
   - Verify multi-entity consolidated balance aggregation.
4. **Replay Suite (`tests/test_replay.py`):**
   - Verify full hash-chain validation and point-in-time state reconstruction equality.
   - Verify zero side-effects on live database files.
5. **RBAC Suite (`tests/test_capabilities.py`):**
   - Verify token creation, hash verification, expired/revoked token rejection, and fine-grained capability scope gating.
6. **Phase 8 Exit Contract (`tests/test_phase8_exit_contract.py`):**
   - Run end-to-end integration scenario combining multi-asset pricing, lineage tracing, multi-tenant isolation, replay, and RBAC enforcement.
