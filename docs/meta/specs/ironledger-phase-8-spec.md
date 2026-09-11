# Phase 8 Specification & Technical Design: Multi-Asset Valuation, Ledger Lineage & Audit Replay

**Program:** IronLedger  
**Milestone:** Phase 8 — Multi-Asset Valuation, Ledger Lineage & Audit Replay  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-10  
**Version:** 1.0.0 (Hardened Canonical Specification)  
**Specification Role:** Governed Documentation Mirror (Synchronized with Canonical Spec)  
**Change Identifier:** `IL-SPEC-PHASE-8-v1.0`  
**Decision Record:** `IL-DECISION-PHASE-8-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Approved Design Specification  

---

## 1. Executive Summary & Core Invariants

Phase 8 expands IronLedger from single-currency transaction recording into a multi-asset valuation, bi-directional lineage tracking, multi-tenant ledger isolation, deterministic point-in-time audit replay, and cryptographic capability-based access control engine.

### Upstream Invariants Inherited & Enforced

1. **Exact Rational Integer Arithmetic:** Multi-asset and commodity conversions operate exclusively on integer minor units and rational fraction ratios $(N / D)$ with strict mathematical sign symmetry and zero IEEE 754 floating-point drift.
2. **Bi-Directional Provenance Lineage:** Every compiled posting references its staged transaction, source record, and raw evidence SHA-256 blob through a tenant-isolated acyclic directed graph (DAG) stored in SQLite with atomic transactional registration, strict self-edge rejection (`source != target`), and unbounded insertion-time cycle detection.
3. **Deterministic Point-in-Time Replay:** The mutation ledger chain ($H_0 \to H_k$) replays schema-versioned canonical event mutation payloads into an ephemeral in-memory projection database to reconstruct exact historical state snapshots at any sequence number without mutating live files.
4. **Tenant & Entity Domain Isolation:** Explicit `ledger_id` column boundaries and foreign keys enforce strict isolation across staging buffers, price histories, compile journals, mutation ledgers, lineage nodes/edges, review rules, and compilation mutex lockfiles (`.ironledger/.compile.<ledger_id>.lock`).
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

Phase 8 schema migrations use `STRICT` table definitions and SQLite-compatible alteration patterns tracked by the governed forward-only migration runner (`ironledger.governance.migrations`):

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
    precision_scale INTEGER NOT NULL DEFAULT 4 CHECK(precision_scale >= 0 AND precision_scale <= 18),
    source TEXT NOT NULL CHECK(source IN ('MANUAL', 'POLLED_FEED', 'EXCHANGE_API')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE(ledger_id, directive_date, base_currency, quote_currency)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_price_history_lookup 
ON price_history(ledger_id, base_currency, quote_currency, directive_date DESC, id DESC);
```

### Migration `0009_ledger_lineage.sql` (Task 8.2)
```sql
CREATE TABLE IF NOT EXISTS lineage_nodes (
    ledger_id TEXT NOT NULL DEFAULT 'default',
    node_id TEXT NOT NULL,                 -- SHA-256 or UUID
    node_type TEXT NOT NULL CHECK(node_type IN ('EVIDENCE_BLOB', 'SOURCE_RECORD', 'STAGED_TX', 'POSTING')),
    entity_ref TEXT NOT NULL,              -- Target ID (posting_id, tx_id, record_id, or blob sha256)
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) = 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(ledger_id, node_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_lineage_nodes_entity ON lineage_nodes(ledger_id, entity_ref);

CREATE TABLE IF NOT EXISTS lineage_edges (
    ledger_id TEXT NOT NULL DEFAULT 'default',
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK(relationship IN ('EXTRACTED_FROM', 'STAGED_FROM', 'COMPILED_FROM')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CHECK(source_node_id != target_node_id),
    PRIMARY KEY(ledger_id, source_node_id, target_node_id, relationship),
    FOREIGN KEY(ledger_id, source_node_id) REFERENCES lineage_nodes(ledger_id, node_id) ON DELETE CASCADE,
    FOREIGN KEY(ledger_id, target_node_id) REFERENCES lineage_nodes(ledger_id, node_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_lineage_edges_forward ON lineage_edges(ledger_id, source_node_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_backward ON lineage_edges(ledger_id, target_node_id);
```

### Migration `0010_multi_ledger_rbac.sql` (Tasks 8.3 & 8.5)
```sql
CREATE TABLE IF NOT EXISTS ledgers (
    ledger_id TEXT PRIMARY KEY CHECK(length(ledger_id) >= 1 AND ledger_id GLOB '[a-zA-Z0-9_-]*'),
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(base_currency) >= 1 AND base_currency GLOB '[A-Z0-9_.-]*'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default', 'Default Ledger', 'USD');

-- Scoped ledger_id column additions for existing tables executed once via governed migration runner
-- (Migration runner uses PRAGMA table_info inspection to guarantee idempotency across re-runs)
ALTER TABLE source_documents ADD COLUMN ledger_id TEXT DEFAULT 'default';
ALTER TABLE source_records ADD COLUMN ledger_id TEXT DEFAULT 'default';
ALTER TABLE staged_transactions ADD COLUMN ledger_id TEXT DEFAULT 'default';
ALTER TABLE staged_postings ADD COLUMN ledger_id TEXT DEFAULT 'default';
ALTER TABLE review_rules ADD COLUMN ledger_id TEXT DEFAULT 'default';
ALTER TABLE compile_runs ADD COLUMN ledger_id TEXT DEFAULT 'default';
ALTER TABLE mutation_events ADD COLUMN ledger_id TEXT DEFAULT 'default' REFERENCES ledgers(ledger_id);

CREATE INDEX IF NOT EXISTS idx_staged_tx_ledger ON staged_transactions(ledger_id, status);
CREATE INDEX IF NOT EXISTS idx_review_rules_ledger ON review_rules(ledger_id, is_active);
CREATE INDEX IF NOT EXISTS idx_mutation_events_ledger ON mutation_events(ledger_id, seq);
CREATE INDEX IF NOT EXISTS idx_compile_runs_ledger ON compile_runs(ledger_id, compile_run_id);

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
) STRICT;

CREATE INDEX IF NOT EXISTS idx_token_hash_lookup ON capability_tokens(token_hash);
```

### Migration `0011_mutation_payloads.sql` (Task 8.4)
```sql
CREATE TABLE IF NOT EXISTS mutation_payloads (
    seq INTEGER PRIMARY KEY,
    mutation_id TEXT NOT NULL UNIQUE,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id),
    payload_schema_version INTEGER NOT NULL DEFAULT 1 CHECK(payload_schema_version >= 1),
    event_type TEXT NOT NULL CHECK(event_type IN ('STAGE_TRANSACTION', 'REVIEW_DECISION', 'COMPILE_LEDGER', 'PRICE_DIRECTIVE', 'RULE_UPDATE')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    projection_hash_before TEXT NOT NULL,
    projection_hash_after TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    FOREIGN KEY(seq) REFERENCES mutation_events(seq) ON DELETE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_mutation_payloads_ledger ON mutation_payloads(ledger_id, seq);
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
  1. Direct lookup: `WHERE ledger_id = :l AND base_currency = :b AND quote_currency = :q AND directive_date <= :d ORDER BY directive_date DESC, id DESC LIMIT 1`.
  2. Inverse lookup fallback: `WHERE ledger_id = :l AND base_currency = :q AND quote_currency = :b AND directive_date <= :d ORDER BY directive_date DESC, id DESC LIMIT 1`, inverted as `(rate_denominator, rate_numerator)`.
  3. Staleness boundary: If `(requested_date - directive_date).days > max_staleness_days`, raise `StalePriceDirectiveError`. If no directive exists, raise `MissingPriceDirectiveError`.
* **Zero-Import Directives:** Template-based emission with parameterized precision:
  ```python
  def format_beancount_price_directive(
      directive_date: str,
      base_currency: str,
      quote_currency: str,
      rate_numerator: int,
      rate_denominator: int,
      precision_scale: int = 4,
  ) -> str:
      decimal_val = Decimal(rate_numerator) / Decimal(rate_denominator)
      fmt = f"{{:.{precision_scale}f}}"
      return f"{directive_date} price {base_currency} {fmt.format(decimal_val)} {quote_currency}"
  ```

### Task 8.2: Ledger Lineage Explorer & Bi-Directional Provenance DAG
* **Location:** `src/ironledger/lineage/explorer.py`, `src/ironledger/lineage/dag.py`
* **Lineage Layers:** `EVIDENCE_BLOB` $\xrightarrow{\text{EXTRACTED\_FROM}}$ `SOURCE_RECORD` $\xrightarrow{\text{STAGED\_FROM}}$ `STAGED_TX` $\xrightarrow{\text{COMPILED\_FROM}}$ `POSTING`.
* **API Signature:**
  ```python
  def add_edge(ledger_id: str, source_node_id: str, target_node_id: str, relationship: str) -> None
  ```
* **Acyclicity & Cycle Prevention:**
  - Self-edge check: If `source_node_id == target_node_id`, raise `LineageCycleError("Self-edges are forbidden")`.
  - Insertion-time check: `LineageDAG.add_edge` executes an unbounded recursive reachability query (`WITH RECURSIVE reachability(node) AS (...)`). If `target_node_id` can reach `source_node_id` within the `ledger_id`, insertion is aborted with `LineageCycleError`.
  - Query recursion bound: Read traversal queries enforce `depth <= 50` limit.
* **Atomic Edge Recording:** Staging and compile writers execute lineage node and edge inserts inside the *same atomic database transaction* (`BEGIN IMMEDIATE`) as the accounting mutations.

### Task 8.3: Multi-Ledger Topology & Isolated Staging Queues
* **Location:** `src/ironledger/ledger/topology.py`, `src/ironledger/ledger/staging.py`
* **Tenant Isolation:** All queries filter strictly by `ledger_id = :ledger_id`.
* **Compile Mutex Locking:** Scoped lockfile path: `.ironledger/.compile.<ledger_id>.lock`.
* **Consolidation Engine:** Read-only multi-entity balance normalization into a designated reporting currency using Task 8.1 valuation routines.

### Task 8.4: Deterministic Audit Replay & Point-in-Time Time Travel
* **Location:** `src/ironledger/replay/engine.py`, `src/ironledger/replay/snapshot.py`
* **Fingerprint Duality Defined:**
  1. `sha256_after` (Beancount manifest hash): Recorded on `mutation_events`. Canonical hash of `.beancount` files on disk (`src/ironledger/manifests.py:compute_ledger_manifest_hash`).
  2. `projection_hash` (SQLite table state hash): Recorded on `mutation_payloads`. Deterministic SHA-256 computed by `compute_projection_hash(conn, ledger_id)`.
* **Global Sequence vs Tenant-Scoped Streams:** Sequence numbers (`seq`) are globally monotonic and contiguous across the entire database instance to preserve global append-only Merkle chain integrity (`prev_mutation_hash`). Each event explicitly records `ledger_id` (foreign key to `ledgers.ledger_id`), and tenant-specific audit or replay streams are queried using the composite index `(ledger_id, seq)`. Tenant replay streams process only the events belonging to the requested `ledger_id` while verifying global chain continuity against the root database.
* **Canonical `projection_hash` Algorithm:**
  ```python
  STATIC_PROJECTION_COLUMNS: dict[str, list[str]] = {
      "staged_transactions": [
          "staged_transaction_id", "source_record_id", "source_document_id",
          "entry_date", "payee", "narration", "status", "assigned_account", "rule_id", "ledger_id"
      ],
      "staged_postings": [
          "staged_posting_id", "staged_transaction_id", "source_record_id",
          "role", "posting_index", "account", "minor_units", "currency", "minor_unit_scale", "ledger_id"
      ],
      "review_rules": [
          "rule_id", "name", "match_pattern", "account", "priority", "is_active", "ledger_id"
      ],
      "price_history": [
          "id", "directive_date", "base_currency", "quote_currency",
          "rate_numerator", "rate_denominator", "precision_scale", "source", "ledger_id"
      ],
      "compile_runs": [
          "compile_run_id", "beancount_version", "compiler_version",
          "input_hash", "intended_output_hash", "actual_output_hash", "status", "ledger_id"
      ],
  }

  TABLE_ORDER_CLAUSES: dict[str, str] = {
      "staged_transactions": "staged_transaction_id ASC",
      "staged_postings": "staged_transaction_id ASC, posting_index ASC, staged_posting_id ASC",
      "review_rules": "rule_id ASC",
      "price_history": "base_currency ASC, quote_currency ASC, directive_date ASC, id ASC",
      "compile_runs": "compile_run_id ASC",
  }

  def compute_projection_hash(conn: sqlite3.Connection, ledger_id: str) -> str:
      """Compute canonical SHA-256 hash over tenant projection state ordered by primary keys."""
      payload = []
      for table, cols in STATIC_PROJECTION_COLUMNS.items():
          col_str = ", ".join(cols)
          order_clause = TABLE_ORDER_CLAUSES[table]
          cur = conn.execute(
              f"SELECT {col_str} FROM {table} WHERE ledger_id = ? ORDER BY {order_clause}",
              (ledger_id,),
          )
          rows = []
          for row in cur.fetchall():
              normalized_row = [
                  None if val is None
                  else int(val) if isinstance(val, (int, bool))
                  else str(val)
                  for val in row
              ]
              rows.append(normalized_row)
          payload.append([table, cols, rows])
      encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
      return hashlib.sha256(encoded).hexdigest()
  ```
* **Payload Event Schemas (`payload_schema_version = 1`):**
  - All payloads conform to JSON Schema draft-07 and enforce `additionalProperties: false`.
  - Every payload requires `ledger_id` matching the event's `ledger_id`, plus event-specific properties:
  - `STAGE_TRANSACTION`:
    - `ledger_id`: string (required, must equal event `ledger_id`)
    - `staged_transaction_id`: string (required)
    - `source_record_id`: string (required)
    - `source_document_id`: string (required)
    - `entry_date`: string format `YYYY-MM-DD` (required)
    - `payee`: string (required)
    - `narration`: string (required)
    - `status`: enum `["PENDING", "APPROVED", "REJECTED"]` (required)
    - `postings`: array of posting objects (minItems 2, required):
      - `staged_posting_id`: string (required)
      - `source_record_id`: string (required)
      - `role`: enum `["imported", "contra"]` (required)
      - `posting_index`: integer `>= 0` (required)
      - `account`: string (required)
      - `minor_units`: integer (required)
      - `currency`: string (required)
      - `minor_unit_scale`: integer `>= 0` (required)
  - `REVIEW_DECISION`:
    - `ledger_id`: string (required, must equal event `ledger_id`)
    - `staged_transaction_id`: string (required)
    - `prior_status`: enum `["PENDING", "APPROVED", "REJECTED"]` (required)
    - `new_status`: enum `["PENDING", "APPROVED", "REJECTED"]` (required)
    - `assigned_account`: string or null (required)
    - `rule_id`: string or null (required)
  - `COMPILE_LEDGER`:
    - `ledger_id`: string (required, must equal event `ledger_id`)
    - `compile_run_id`: string (required)
    - `beancount_version`: string (required)
    - `compiler_version`: string (required)
    - `input_hash`: string length 64 hex (required)
    - `intended_output_hash`: string length 64 hex (required)
    - `actual_output_hash`: string length 64 hex (required)
    - `compiled_tx_ids`: array of string (required)
  - `PRICE_DIRECTIVE`:
    - `ledger_id`: string (required, must equal event `ledger_id`)
    - `directive_date`: string format `YYYY-MM-DD` (required)
    - `base_currency`: string (required)
    - `quote_currency`: string (required)
    - `rate_numerator`: integer `> 0` (required)
    - `rate_denominator`: integer `> 0` (required)
    - `precision_scale`: integer `0..18` (required)
    - `source`: enum `["MANUAL", "POLLED_FEED", "EXCHANGE_API"]` (required)
  - `RULE_UPDATE`:
    - `ledger_id`: string (required, must equal event `ledger_id`)
    - `rule_id`: string (required)
    - `action`: enum `["CREATE", "UPDATE", "DELETE"]` (required)
    - `name`: string (required)
    - `match_pattern`: string (required)
    - `account`: string (required)
    - `priority`: integer (required)
    - `is_active`: integer `0` or `1` (required)

* **Transactional Mutation Dispatch & Atomic Append Contract:**
  ```python
  def apply_mutation_and_append(
      conn: sqlite3.Connection,
      ledger_id: str,
      operator_session: str,
      action: str,
      event_type: str,
      payload: dict[str, Any],
      payload_schema_version: int = 1,
      rules_applied: int = 0,
      rules_created: int = 0,
      sha256_before: str = "0" * 64,
      sha256_after: str = "0" * 64,
  ) -> tuple[MutationEvent, MutationPayload]:
      """Apply domain mutation and append mutation event + payload in a single atomic transaction."""
      # 1. Validate payload schema and enforce additionalProperties: false & tenant consistency
      validate_payload_schema(event_type, payload, payload_schema_version)
      if payload.get("ledger_id") != ledger_id:
          raise ValueError(
              f"Payload ledger_id '{payload.get('ledger_id')}' does not match target ledger_id '{ledger_id}'"
          )
      
      # 2. Begin immediate transaction for write exclusivity
      conn.execute("BEGIN IMMEDIATE")
      try:
          # 3. Compute projection hash before mutation
          projection_hash_before = compute_projection_hash(conn, ledger_id)
          
          # 4. Dispatch and execute domain table mutations inside transaction
          dispatch_event_mutation(conn, ledger_id, event_type, payload)
          
          # 5. Compute projection hash after mutation
          projection_hash_after = compute_projection_hash(conn, ledger_id)
          
          # 6. Allocate monotonic sequence and fetch previous hash
          cur = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM mutation_events")
          seq = cur.fetchone()[0] + 1
          
          if seq == 1:
              prev_mutation_hash = "0" * 64
          else:
              cur = conn.execute("SELECT mutation_hash FROM mutation_events WHERE seq = ?", (seq - 1,))
              prev_mutation_hash = cur.fetchone()[0]
              
          mutation_id = f"mut_{uuid4().hex}"
          ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
          
          # 7. Canonical JSON hash computation
          canonical_dict = {
              "action": action,
              "event_type": event_type,
              "ledger_id": ledger_id,
              "mutation_id": mutation_id,
              "operator_session": operator_session,
              "payload": payload,
              "payload_schema_version": payload_schema_version,
              "prev_mutation_hash": prev_mutation_hash,
              "projection_hash_after": projection_hash_after,
              "projection_hash_before": projection_hash_before,
              "rules_applied": rules_applied,
              "rules_created": rules_created,
              "seq": seq,
              "sha256_after": sha256_after,
              "sha256_before": sha256_before,
              "ts_utc": ts_utc,
          }
          mutation_hash = hashlib.sha256(
              json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
          ).hexdigest()
          
          # 8. Insert into mutation_events and mutation_payloads
          conn.execute(
              "INSERT INTO mutation_events (seq, mutation_id, ledger_id, ts_utc, operator_session, action, "
              "staged_count, rules_applied, rules_created, sha256_before, sha256_after, prev_mutation_hash, mutation_hash) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (seq, mutation_id, ledger_id, ts_utc, operator_session, action, 0, rules_applied, rules_created,
               sha256_before, sha256_after, prev_mutation_hash, mutation_hash)
          )
          conn.execute(
              "INSERT INTO mutation_payloads (seq, mutation_id, ledger_id, payload_schema_version, event_type, "
              "payload_json, projection_hash_before, projection_hash_after, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (seq, mutation_id, ledger_id, payload_schema_version, event_type,
               json.dumps(payload, sort_keys=True, separators=(",", ":")),
               projection_hash_before, projection_hash_after, ts_utc)
          )
          
          conn.execute("COMMIT")
      except Exception:
          conn.execute("ROLLBACK")
          raise
      
      return (
          MutationEvent(seq=seq, mutation_id=mutation_id, ledger_id=ledger_id, ts_utc=ts_utc,
                        operator_session=operator_session, action=action, mutation_hash=mutation_hash, ...),
          MutationPayload(seq=seq, mutation_id=mutation_id, ledger_id=ledger_id, event_type=event_type, ...)
      )
  ```

* **Deterministic Replay Engine Algorithm:**
  1. Resolve `target_sequence`: If `target_timestamp` is provided, select `MAX(seq)` where `ts_utc <= target_timestamp` ordered strictly by `seq ASC`.
  2. Verify hash chain from sequence 1 to `target_sequence`.
  3. Spin up an in-memory SQLite projection database (`:memory:`), load schema `0001` through `0011`.
  4. Stream `mutation_payloads` ordered by `seq ASC`:
     - Validate that current in-memory `compute_projection_hash(mem_conn, event.ledger_id)` equals `event.projection_hash_before`. If mismatched, fail closed with `ReplayVerificationError`.
     - Execute `dispatch_event_mutation(mem_conn, event.ledger_id, event.event_type, event.payload)`.
     - Validate that resulting in-memory `compute_projection_hash(mem_conn, event.ledger_id)` equals `event.projection_hash_after`. If mismatched, fail closed with `ReplayVerificationError`.
  5. Return verified in-memory projection database and point-in-time trial balance.

### Task 8.5: Scoped Capability Tokens & RBAC Policy Enforcement
* **Location:** `src/ironledger/auth/capabilities.py`, `src/ironledger/auth/policy.py`
* **Role Ceiling Matrix:**
  | Role | Maximum Allowed Capability Scopes |
  |---|---|
  | `READER` | `["ledger:read", "audit:replay"]` |
  | `OPERATOR` | `["ledger:read", "staging:write", "review:decide", "audit:replay"]` |
  | `COMPILER` | `["ledger:read", "compile:execute", "audit:replay"]` |
  | `ADMIN` | `["*"]` (Matches all scopes across all operations) |
* **Token Security & Validation:**
  - Bearer tokens generated via `secrets.token_hex(32)` (`il_cap_<hex64>`).
  - `PolicyEnforcer.authorize(token, required_scope, target_ledger_id)`:
    1. Look up token by SHA-256 hash.
    2. Fail closed if `revoked_at` is NOT NULL.
    3. Fail closed if `expires_at` is NOT NULL and `expires_at <= current_utc_iso`.
    4. Check ledger scope: `token.is_global == 1` (Admin) OR `token.ledger_id == target_ledger_id`.
    5. Check role ceiling: verify that granted scopes in `capabilities_json` do not exceed the role's maximum allowed scopes.
    6. Check `required_scope` in `token.capabilities` or `token.capabilities == ["*"]`.
* **Centralized Policy Enforcement:** Invoked across CLI commands, MCP tools, and web endpoints.

### Task 8.6: Acceptance Regression Suite & Phase 8 Exit Evidence
* **Location:** `tests/test_valuation.py`, `tests/test_lineage.py`, `tests/test_multi_ledger.py`, `tests/test_replay.py`, `tests/test_capabilities.py`, `tests/test_phase8_exit_contract.py`
* **Static Analysis Import Guard:** AST scanner in `tests/test_phase8_exit_contract.py` scans `src/ironledger/**/*.py` to assert zero `import beancount` or dynamic `__import__("beancount")`.
* **Exit Evidence Artifact:** `docs/meta/phases/ironledger-phase-8-evidence.md`.

---

## 5. Verification & Test Plan

1. **Valuation Suite (`tests/test_valuation.py`):**
   - Verify integer rational price conversion with 0 floating-point drift across mixed decimal precisions (USD 2-dec, BTC 8-dec, AAPL 4-dec).
   - Verify bounded preceding price resolution, stale price rejection, identity same-currency conversion, and inverse quote resolution.
   - Verify Beancount price directive string template output with zero runtime Beancount imports and configurable scale precision.
2. **Lineage Suite (`tests/test_lineage.py`):**
   - Verify bi-directional recursive CTE DAG traversals within tenant boundaries (posting $\to$ evidence hash, and evidence hash $\to$ postings).
   - Verify self-edge rejection and unbounded cycle prevention rejection and transactional atomicity on edge registration.
3. **Multi-Ledger Suite (`tests/test_multi_ledger.py`):**
   - Verify complete isolation of staging queues, lineage nodes, review rules, and concurrent compilation locks across multiple `ledger_id`s.
   - Verify multi-entity consolidated balance aggregation.
4. **Replay Suite (`tests/test_replay.py`):**
   - Verify full hash-chain validation and payload replay into in-memory projection database validating `projection_hash_before` and `projection_hash_after`.
   - Verify zero side-effects on live database files.
5. **RBAC Suite (`tests/test_capabilities.py`):**
   - Verify token creation, constant-time hash verification, role ceiling enforcement, expiration/revocation gating, and global vs tenant-scoped validation.
6. **Phase 8 Exit Contract (`tests/test_phase8_exit_contract.py`):**
   - Run end-to-end integration scenario combining multi-asset pricing, lineage tracing, multi-tenant isolation, replay, and RBAC enforcement.
