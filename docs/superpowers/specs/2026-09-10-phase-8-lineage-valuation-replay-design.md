# Phase 8 Specification & Technical Design: Multi-Asset Valuation, Ledger Lineage & Audit Replay

**Program:** IronLedger  
**Milestone:** Phase 8 — Multi-Asset Valuation, Ledger Lineage & Audit Replay  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-10  
**Status:** Hardened Specification (Codex Review Finding Resolutions Applied)  

---

## 1. Executive Summary & Core Invariants

Phase 8 expands IronLedger from single-currency transaction recording into a multi-asset valuation, bi-directional lineage tracking, multi-tenant ledger isolation, deterministic point-in-time audit replay, and cryptographic capability-based access control engine.

### Upstream Invariants Inherited & Enforced

1. **Exact Rational Integer Arithmetic:** Multi-asset and commodity conversions operate exclusively on integer minor units and rational fraction ratios $(N / D)$ with strict mathematical sign symmetry and zero IEEE 754 floating-point drift.
2. **Bi-Directional Provenance Lineage:** Every compiled posting references its staged transaction, source record, and raw evidence SHA-256 blob through an acyclic directed graph (DAG) stored in SQLite with atomic transactional registration.
3. **Deterministic Point-in-Time Replay:** The mutation ledger chain ($H_0 \to H_k$) replays canonical event mutation payloads into an ephemeral in-memory projection database to reconstruct exact historical state snapshots at any sequence number without mutating live files.
4. **Tenant & Entity Domain Isolation:** Explicit `ledger_id` column boundaries enforce strict isolation across staging buffers, price histories, compile journals, mutation ledgers, and compilation mutex lockfiles (`.ironledger/.compile.<ledger_id>.lock`).
5. **Zero Runtime `import beancount`:** All Beancount commodity and price directives are generated via deterministic string template emission, guarded by AST static analysis and import prohibition tests.
6. **Scoped Capability RBAC:** Granular cryptographic capability tokens authorize actions with fail-closed default-deny enforcement across CLI, web, and programmatic interfaces.

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
    directive_date TEXT NOT NULL CHECK(directive_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    base_currency TEXT NOT NULL CHECK(length(base_currency) >= 1 AND base_currency GLOB '[A-Z0-9_.-]*'),
    quote_currency TEXT NOT NULL CHECK(length(quote_currency) >= 1 AND quote_currency GLOB '[A-Z0-9_.-]*'),
    rate_numerator INTEGER NOT NULL CHECK(rate_numerator > 0),
    rate_denominator INTEGER NOT NULL CHECK(rate_denominator > 0),
    source TEXT NOT NULL CHECK(source IN ('MANUAL', 'POLLED_FEED', 'EXCHANGE_API')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE(ledger_id, directive_date, base_currency, quote_currency)
);

CREATE INDEX IF NOT EXISTS idx_price_history_lookup 
ON price_history(ledger_id, base_currency, quote_currency, directive_date DESC);
```

### Migration `0009_ledger_lineage.sql` (Task 8.2)
```sql
CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_id TEXT PRIMARY KEY,              -- SHA-256 or UUID
    ledger_id TEXT NOT NULL DEFAULT 'default',
    node_type TEXT NOT NULL CHECK(node_type IN ('EVIDENCE_BLOB', 'SOURCE_RECORD', 'STAGED_TX', 'POSTING')),
    entity_ref TEXT NOT NULL,              -- Target ID (posting_id, tx_id, record_id, or blob sha256)
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) = 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_lineage_nodes_ledger ON lineage_nodes(ledger_id, node_type);

CREATE TABLE IF NOT EXISTS lineage_edges (
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK(relationship IN ('EXTRACTED_FROM', 'STAGED_FROM', 'COMPILED_FROM')),
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
    ledger_id TEXT PRIMARY KEY CHECK(length(ledger_id) >= 1 AND ledger_id GLOB '[a-zA-Z0-9_-]*'),
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(base_currency) >= 1 AND base_currency GLOB '[A-Z0-9_.-]*'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default', 'Default Ledger', 'USD');

-- Add ledger_id tenant isolation columns to core tables if missing
ALTER TABLE staged_transactions ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id);
ALTER TABLE staged_postings ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id);
ALTER TABLE compile_runs ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id);
ALTER TABLE mutation_events ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id);

CREATE INDEX IF NOT EXISTS idx_staged_tx_ledger ON staged_transactions(ledger_id, status);
CREATE INDEX IF NOT EXISTS idx_mutation_events_ledger ON mutation_events(ledger_id, seq);

CREATE TABLE IF NOT EXISTS capability_tokens (
    token_id TEXT PRIMARY KEY,             -- UUID
    token_hash TEXT NOT NULL UNIQUE,       -- SHA-256 of the bearer token string
    ledger_id TEXT REFERENCES ledgers(ledger_id) ON DELETE CASCADE, -- NULL indicates global admin scope
    is_global INTEGER NOT NULL DEFAULT 0 CHECK(is_global IN (0, 1)),
    role TEXT NOT NULL CHECK(role IN ('READER', 'OPERATOR', 'COMPILER', 'ADMIN')),
    capabilities_json TEXT NOT NULL CHECK(json_valid(capabilities_json) = 1),
    expires_at TEXT CHECK(expires_at IS NULL OR expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'),
    revoked_at TEXT CHECK(revoked_at IS NULL OR revoked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CHECK((is_global = 1 AND ledger_id IS NULL) OR (is_global = 0 AND ledger_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_token_hash_lookup ON capability_tokens(token_hash);
```

### Migration `0011_mutation_payloads.sql` (Task 8.4)
```sql
CREATE TABLE IF NOT EXISTS mutation_payloads (
    seq INTEGER PRIMARY KEY,
    mutation_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL CHECK(event_type IN ('STAGE_TRANSACTION', 'REVIEW_DECISION', 'COMPILE_LEDGER', 'PRICE_DIRECTIVE', 'RULE_UPDATE')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    FOREIGN KEY(seq) REFERENCES mutation_events(seq) ON DELETE CASCADE
);
```

---

## 4. Subsystem Detailed Specifications

### Task 8.1: Multi-Asset Valuation Engine & Historical Price Directives
* **Location:** `src/ironledger/valuation/engine.py`, `src/ironledger/valuation/models.py`
* **Mathematical Conversion Formula:**
  $$\text{Sign} = \begin{cases} 1 & \text{if } \text{Source Minor} \ge 0 \\ -1 & \text{if } \text{Source Minor} < 0 \end{cases}$$
  $$\text{Target Minor} = \text{Sign} \times \left\lfloor \frac{|\text{Source Minor}| \times \text{Numerator} \times 10^{\max(0, \text{Target Dec} - \text{Source Dec})}}{\text{Denominator} \times 10^{\max(0, \text{Source Dec} - \text{Target Dec})}} \right\rfloor$$
* **Identity Conversion:** If `base_currency == quote_currency`, conversion immediately returns source minor units unchanged (1:1).
* **Ratio Normalization:** Fractions are reduced via `math.gcd(rate_numerator, rate_denominator)` before conversion.
* **Deterministic Price Resolution Order:**
  1. Direct lookup: `WHERE ledger_id = :l AND base_currency = :b AND quote_currency = :q AND directive_date <= :d ORDER BY directive_date DESC LIMIT 1`.
  2. Inverse lookup fallback: `WHERE ledger_id = :l AND base_currency = :q AND quote_currency = :b AND directive_date <= :d ORDER BY directive_date DESC LIMIT 1`, inverted as `(rate_denominator, rate_numerator)`.
  3. Staleness boundary: If `(requested_date - directive_date).days > max_staleness_days`, raise `StalePriceDirectiveError`. If no directive exists, raise `MissingPriceDirectiveError`.
* **Zero-Import Directives:** Template-based emission: `f"{directive_date} price {base_currency} {Decimal(num)/Decimal(denom):.4f} {quote_currency}"`.

### Task 8.2: Ledger Lineage Explorer & Bi-Directional Provenance DAG
* **Location:** `src/ironledger/lineage/explorer.py`, `src/ironledger/lineage/dag.py`
* **Lineage Layers:** `EVIDENCE_BLOB` $\xrightarrow{\text{EXTRACTED\_FROM}}$ `SOURCE_RECORD` $\xrightarrow{\text{STAGED\_FROM}}$ `STAGED_TX` $\xrightarrow{\text{COMPILED\_FROM}}$ `POSTING`.
* **Acyclicity & Cycle Prevention:**
  - Insertion-time check: `LineageDAG.add_edge(source_id, target_id)` runs a recursive reachability check. If `target_id` can reach `source_id`, insertion is aborted with `LineageCycleError`.
  - Query recursion bound: Recursive CTEs enforce `depth <= 50` hard limit.
* **Atomic Edge Recording:** Staging and compile writers execute lineage node and edge inserts inside the *same atomic database transaction* (`BEGIN IMMEDIATE`) as the accounting mutations.

### Task 8.3: Multi-Ledger Topology & Isolated Staging Queues
* **Location:** `src/ironledger/ledger/topology.py`, `src/ironledger/ledger/staging.py`
* **Tenant Isolation:** All queries filter strictly by `ledger_id = :ledger_id`.
* **Compile Mutex Locking:** Scoped lockfile path: `.ironledger/.compile.<ledger_id>.lock`.
* **Consolidation Engine:** Read-only multi-entity balance normalization into a designated reporting currency using Task 8.1 valuation routines.

### Task 8.4: Deterministic Audit Replay & Point-in-Time Time Travel
* **Location:** `src/ironledger/replay/engine.py`, `src/ironledger/replay/snapshot.py`
* **Hash-Chain Canonical Verification:** Uses the repository canonical JSON hash calculation (`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")`) verifying $H_i = \text{SHA-256}(\text{CanonicalEvent}_i)$.
* **Deterministic Replay Execution:**
  1. Resolve `target_sequence`: If `target_timestamp` is provided, select $\max(\text{seq})$ where `ts_utc <= target_timestamp`.
  2. Verify hash chain from sequence 1 to `target_sequence`.
  3. Spin up an in-memory SQLite projection database (`:memory:`), load schema `0001` through `0011`.
  4. Stream `mutation_payloads` and execute schema-versioned deterministic event handlers.
  5. Validate final projection fingerprint against `sha256_after` and return the point-in-time balance snapshot.
* **Zero Side-Effects:** Live database and filesystem are strictly untouched during replay.

### Task 8.5: Scoped Capability Tokens & RBAC Policy Enforcement
* **Location:** `src/ironledger/auth/capabilities.py`, `src/ironledger/auth/policy.py`
* **Token Security:** Bearer tokens generated via `secrets.token_hex(32)` (`il_cap_<hex64>`). Verification uses `hmac.compare_digest(stored_hash, sha256(token))`.
* **Centralized Policy Enforcement:** `PolicyEnforcer.authorize(token, required_scope, target_ledger_id)` invoked across CLI commands, MCP tools, and web endpoints.
* **Scope Matrix:**
  - `ledger:read`, `staging:write`, `review:decide`, `compile:execute`, `audit:replay`, `admin:*`.

### Task 8.6: Acceptance Regression Suite & Phase 8 Exit Evidence
* **Location:** `tests/test_valuation.py`, `tests/test_lineage.py`, `tests/test_multi_ledger.py`, `tests/test_replay.py`, `tests/test_capabilities.py`, `tests/test_phase8_exit_contract.py`
* **Static Analysis Import Guard:** AST scanner in `tests/test_phase8_exit_contract.py` scans `src/ironledger/**/*.py` to assert zero `import beancount` or dynamic `__import__("beancount")`.
* **Exit Evidence Artifact:** `docs/meta/phases/ironledger-phase-8-evidence.md`.

---

## 5. Verification & Test Plan

1. **Valuation Suite (`tests/test_valuation.py`):**
   - Verify integer rational price conversion with 0 floating-point drift across mixed decimal precisions (USD 2-dec, BTC 8-dec, AAPL 4-dec).
   - Verify bounded preceding price resolution, stale price rejection, identity same-currency conversion, and inverse quote resolution.
   - Verify Beancount price directive string template output with zero runtime Beancount imports.
2. **Lineage Suite (`tests/test_lineage.py`):**
   - Verify bi-directional recursive CTE DAG traversals (posting $\to$ evidence hash, and evidence hash $\to$ postings).
   - Verify cycle prevention rejection and transactional atomicity on edge registration.
3. **Multi-Ledger Suite (`tests/test_multi_ledger.py`):**
   - Verify complete isolation of staging queues and concurrent compilation locks across multiple `ledger_id`s.
   - Verify multi-entity consolidated balance aggregation.
4. **Replay Suite (`tests/test_replay.py`):**
   - Verify full hash-chain validation and payload replay into in-memory projection database.
   - Verify zero side-effects on live database files.
5. **RBAC Suite (`tests/test_capabilities.py`):**
   - Verify token creation, constant-time hash verification, global vs tenant-scoped validation, and fine-grained capability scope gating.
6. **Phase 8 Exit Contract (`tests/test_phase8_exit_contract.py`):**
   - Run end-to-end integration scenario combining multi-asset pricing, lineage tracing, multi-tenant isolation, replay, and RBAC enforcement.
