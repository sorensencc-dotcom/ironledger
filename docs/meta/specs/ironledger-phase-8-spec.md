# Phase 8 Specification & Technical Design: Multi-Asset Valuation, Ledger Lineage & Audit Replay

**Program:** IronLedger  
**Milestone:** Phase 8 — Multi-Asset Valuation, Ledger Lineage & Audit Replay  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-10  
**Version:** 1.0.0 (Hardened Canonical Specification)  
**Specification Role:** Canonical Implementation Specification & Governed Mirror  
**Change Identifier:** `IL-SPEC-PHASE-8-v1.0`  
**Decision Record:** `IL-DECISION-PHASE-8-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Pre-Implementation Architectural Specification & Design Contract (Gate 1)  

---

## 1. Executive Summary & Core Invariants

Phase 8 expands IronLedger from single-currency transaction recording into a multi-asset valuation, bi-directional lineage tracking, multi-tenant ledger isolation, deterministic point-in-time audit replay, and cryptographic capability-based access control engine.

### Upstream Invariants Inherited & Enforced

1. **Exact Rational Integer Arithmetic:** Multi-asset and commodity conversions operate exclusively on integer minor units and rational fraction ratios $(N / D)$ with strict mathematical sign symmetry and zero IEEE 754 floating-point drift. Price directive formatting uses pure integer arithmetic with exact Banker's half-even rounding (no float or lossy division).
2. **Bi-Directional Provenance Lineage:** Every compiled posting references its staged transaction, source record, and raw evidence SHA-256 blob through a tenant-isolated acyclic directed graph (DAG) stored in SQLite with atomic transactional registration, strict self-edge rejection (`source != target`), and unbounded insertion-time cycle detection.
3. **Deterministic Point-in-Time Replay:** The mutation ledger chain ($H_0 \to H_k$) verifies the global contiguous sequence and Merkle chain from genesis anchors, then replays schema-versioned canonical event mutation payloads into an ephemeral in-memory projection database and ephemeral filesystem manifest to reconstruct exact historical state snapshots at any sequence number without mutating live files.
4. **Tenant & Entity Domain Isolation:** Explicit `ledger_id` column boundaries, composite primary keys (`PRIMARY KEY(ledger_id, entity_id)`), composite foreign keys (`FOREIGN KEY(ledger_id, parent_id) REFERENCES parent_table(ledger_id, parent_id)`), tenant-scoped lockfiles (`.ironledger/.compile.<ledger_id>.lock`), and tenant-scoped uniqueness constraints enforce strict cross-tenant isolation at the relational schema and filesystem boundaries with mandatory `PRAGMA foreign_keys = ON;`.
5. **Authoritative Plaintext Accounting & Zero Runtime `import beancount`:** Plaintext Beancount files remain the ultimate accounting authority. All Beancount commodity and price directives are generated via deterministic string template emission, guarded by symbol-tracking static AST scanners forbidding `import beancount`, `from beancount import ...`, `__import__("beancount")`, `importlib.import_module("beancount")`, and dynamic `getattr` module loaders (reading package version metadata via `importlib.metadata.version("beancount")` is permitted).
6. **Scoped Capability RBAC:** Granular cryptographic capability tokens authorize actions with fail-closed default-deny enforcement and issuance-time role ceiling validation across CLI, web, and programmatic interfaces.

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

Phase 8 schema migrations use `STRICT` table definitions and SQLite-compatible alteration patterns tracked by the governed forward-only migration runner (`ironledger.db.migrations`). All connections execute `PRAGMA foreign_keys = ON;` upon initialization.

### Entity & Key Isolation Coverage Matrix (Migration `0010`)
| Entity Table | Primary Key | Foreign Key Reference | Tenant Uniqueness |
|---|---|---|---|
| `ledgers` | `(ledger_id)` | Root tenant catalog | `UNIQUE(ledger_id)` |
| `source_documents` | `(ledger_id, source_document_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, content_sha256)` |
| `source_records` | `(ledger_id, source_record_id)` | `FOREIGN KEY(ledger_id, source_document_id) REFERENCES source_documents(ledger_id, source_document_id)` | `UNIQUE(ledger_id, source_document_id, record_index)` |
| `staged_transactions` | `(ledger_id, staged_transaction_id)` | `FOREIGN KEY(ledger_id, source_record_id) REFERENCES source_records(ledger_id, source_record_id)` | `UNIQUE(ledger_id, identity_algo_version, identity_fingerprint)` |
| `staged_postings` | `(ledger_id, staged_posting_id)` | `FOREIGN KEY(ledger_id, staged_transaction_id) REFERENCES staged_transactions(ledger_id, staged_transaction_id)`<br>`FOREIGN KEY(ledger_id, source_record_id) REFERENCES source_records(ledger_id, source_record_id)` | `UNIQUE(ledger_id, staged_transaction_id, posting_index)` |
| `categorization_rules` | `(ledger_id, rule_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, match_type, pattern, importing_account)` |
| `price_history` | `(id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, directive_date, base_currency, quote_currency)` |
| `mutation_events` | `(seq)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(mutation_id)`, `UNIQUE(mutation_hash)`, `UNIQUE(seq, mutation_id, ledger_id)` |
| `mutation_payloads` | `(seq)` | `FOREIGN KEY(seq, mutation_id, ledger_id) REFERENCES mutation_events(seq, mutation_id, ledger_id)` | `UNIQUE(mutation_id)` |
| `capability_tokens` | `(token_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(token_hash)` |

### Migration `0008_price_history.sql` (Task 8.1)
```sql
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
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
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,                 -- SHA-256 or UUID
    node_type TEXT NOT NULL CHECK(node_type IN ('EVIDENCE_BLOB', 'SOURCE_RECORD', 'STAGED_TX', 'POSTING')),
    entity_ref TEXT NOT NULL,              -- Target ID (posting_id, tx_id, record_id, or blob sha256)
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) = 1),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(ledger_id, node_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_lineage_nodes_entity ON lineage_nodes(ledger_id, entity_ref);

CREATE TABLE IF NOT EXISTS lineage_edges (
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
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
-- 1. Create root tenant ledgers table
CREATE TABLE IF NOT EXISTS ledgers (
    ledger_id TEXT PRIMARY KEY CHECK(length(ledger_id) >= 1 AND ledger_id GLOB '[a-zA-Z0-9_-]*'),
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(base_currency) >= 1 AND base_currency GLOB '[A-Z0-9_.-]*'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default', 'Default Ledger', 'USD');

-- 2. Transactional Table Rebuild with Composite Foreign Keys for Tenant Isolation

-- 2a. Rebuild source_documents with (ledger_id, source_document_id) composite identity
CREATE TABLE source_documents_new (
    source_document_id   TEXT NOT NULL,
    ledger_id            TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    mime_type            TEXT NOT NULL,
    encoding             TEXT NOT NULL,
    provenance           TEXT NOT NULL,
    acquisition_time_utc TEXT NOT NULL CHECK (acquisition_time_utc GLOB '????-??-??T??:??:??*Z'),
    content_sha256       TEXT NOT NULL CHECK (length(content_sha256) = 64),
    raw_payload_ref      TEXT NOT NULL,
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    PRIMARY KEY (ledger_id, source_document_id),
    UNIQUE (ledger_id, content_sha256)
) STRICT;

INSERT INTO source_documents_new (
    source_document_id, ledger_id, mime_type, encoding, provenance,
    acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc
)
SELECT
    source_document_id, 'default', mime_type, encoding, provenance,
    acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc
FROM source_documents;

-- 2b. Rebuild source_records with composite FK to source_documents
CREATE TABLE source_records_new (
    source_record_id   TEXT NOT NULL,
    ledger_id          TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    source_document_id TEXT NOT NULL,
    record_index       INTEGER NOT NULL CHECK (record_index >= 0),
    canonical_payload  TEXT NOT NULL,
    content_sha256     TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_at_utc     TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    PRIMARY KEY (ledger_id, source_record_id),
    UNIQUE (ledger_id, source_document_id, record_index),
    FOREIGN KEY (ledger_id, source_document_id) REFERENCES source_documents_new (ledger_id, source_document_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

INSERT INTO source_records_new (
    source_record_id, ledger_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc
)
SELECT
    source_record_id, 'default', source_document_id, record_index, canonical_payload, content_sha256, created_at_utc
FROM source_records;

-- 2c. Rebuild staged_transactions with composite FK to source_records
CREATE TABLE staged_postings_rebuild_backup_0010 AS SELECT * FROM staged_postings;
DELETE FROM staged_postings;

CREATE TABLE staged_transactions_new (
    staged_transaction_id TEXT NOT NULL,
    ledger_id             TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    source_record_id      TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'categorized', 'approved', 'rejected')),
    proposed_date         TEXT NOT NULL CHECK (proposed_date GLOB '????-??-??'),
    payee                 TEXT NOT NULL DEFAULT '',
    narration             TEXT NOT NULL DEFAULT '',
    identity_algo_version INTEGER NOT NULL CHECK (identity_algo_version >= 1),
    identity_method       TEXT NOT NULL CHECK (identity_method IN ('fitid', 'sha256_fallback')),
    identity_fingerprint  TEXT NOT NULL CHECK (length(identity_fingerprint) = 64),
    created_at_utc        TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    decided_at_utc        TEXT CHECK (decided_at_utc IS NULL OR decided_at_utc GLOB '????-??-??T??:??:??*Z'),
    reject_reason         TEXT,
    categorized_at_utc    TEXT CHECK (categorized_at_utc IS NULL OR categorized_at_utc GLOB '????-??-??T??:??:??*Z'),
    PRIMARY KEY (ledger_id, staged_transaction_id),
    UNIQUE (ledger_id, identity_algo_version, identity_fingerprint),
    FOREIGN KEY (ledger_id, source_record_id) REFERENCES source_records_new (ledger_id, source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

INSERT INTO staged_transactions_new (
    staged_transaction_id, ledger_id, source_record_id, status, proposed_date, payee, narration,
    identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc,
    reject_reason, categorized_at_utc
)
SELECT
    staged_transaction_id, 'default', source_record_id, status, proposed_date, payee, narration,
    identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc,
    reject_reason, categorized_at_utc
FROM staged_transactions;

-- 2d. Rebuild staged_postings with composite FK to staged_transactions and source_records
CREATE TABLE staged_postings_new (
    staged_posting_id     TEXT NOT NULL,
    ledger_id             TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    staged_transaction_id TEXT NOT NULL,
    source_record_id      TEXT NOT NULL,
    role                  TEXT NOT NULL CHECK (role IN ('imported', 'contra')),
    posting_index         INTEGER NOT NULL CHECK (posting_index >= 0),
    account               TEXT CHECK (
        account IS NULL
        OR account GLOB 'Assets:*' OR account GLOB 'Liabilities:*' OR account GLOB 'Equity:*'
        OR account GLOB 'Income:*' OR account GLOB 'Expenses:*'
    ),
    minor_units           INTEGER NOT NULL,
    currency              TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
    minor_unit_scale      INTEGER NOT NULL CHECK (minor_unit_scale >= 0),
    created_at_utc        TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    CHECK (role = 'contra' OR account IS NOT NULL),
    PRIMARY KEY (ledger_id, staged_posting_id),
    UNIQUE (ledger_id, staged_transaction_id, posting_index),
    FOREIGN KEY (ledger_id, staged_transaction_id) REFERENCES staged_transactions_new (ledger_id, staged_transaction_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    FOREIGN KEY (ledger_id, source_record_id) REFERENCES source_records_new (ledger_id, source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

INSERT INTO staged_postings_new (
    staged_posting_id, ledger_id, staged_transaction_id, source_record_id, role,
    posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc
)
SELECT
    staged_posting_id, 'default', staged_transaction_id, source_record_id, role,
    posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc
FROM staged_postings_rebuild_backup_0010;

-- 2e. Rebuild categorization_rules
CREATE TABLE categorization_rules_new (
    rule_id           TEXT NOT NULL,
    ledger_id         TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    match_type        TEXT NOT NULL CHECK (match_type IN ('exact', 'prefix', 'regex')),
    pattern           TEXT NOT NULL,
    importing_account TEXT CHECK (
        importing_account IS NULL
        OR importing_account GLOB 'Assets:*' OR importing_account GLOB 'Liabilities:*'
        OR importing_account GLOB 'Equity:*' OR importing_account GLOB 'Income:*'
        OR importing_account GLOB 'Expenses:*'
    ),
    target_account    TEXT NOT NULL CHECK (
        target_account GLOB 'Assets:*' OR target_account GLOB 'Liabilities:*'
        OR target_account GLOB 'Equity:*' OR target_account GLOB 'Income:*'
        OR target_account GLOB 'Expenses:*'
    ),
    priority          INTEGER NOT NULL DEFAULT 100,
    active            INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at_utc    TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    disabled_at_utc   TEXT CHECK (disabled_at_utc IS NULL OR disabled_at_utc GLOB '????-??-??T??:??:??*Z'),
    PRIMARY KEY (ledger_id, rule_id),
    UNIQUE (ledger_id, match_type, pattern, importing_account)
) STRICT;

INSERT INTO categorization_rules_new (
    rule_id, ledger_id, match_type, pattern, importing_account, target_account,
    priority, active, created_at_utc, disabled_at_utc
)
SELECT
    rule_id, 'default', match_type, pattern, importing_account, target_account,
    priority, active, created_at_utc, disabled_at_utc
FROM categorization_rules;

-- 2f. Swap all rebuilt tables
DROP TABLE staged_postings;
DROP TABLE staged_transactions;
DROP TABLE source_records;
DROP TABLE source_documents;
DROP TABLE categorization_rules;
DROP TABLE staged_postings_rebuild_backup_0010;

ALTER TABLE source_documents_new RENAME TO source_documents;
ALTER TABLE source_records_new RENAME TO source_records;
ALTER TABLE staged_transactions_new RENAME TO staged_transactions;
ALTER TABLE staged_postings_new RENAME TO staged_postings;
ALTER TABLE categorization_rules_new RENAME TO categorization_rules;

CREATE INDEX idx_source_records_doc ON source_records (ledger_id, source_document_id);
CREATE INDEX idx_staged_source_record ON staged_transactions (ledger_id, source_record_id);
CREATE INDEX idx_staged_tx_ledger ON staged_transactions (ledger_id, status);
CREATE INDEX idx_staged_postings_transaction ON staged_postings (ledger_id, staged_transaction_id);
CREATE INDEX idx_staged_postings_source ON staged_postings (ledger_id, source_record_id);
CREATE INDEX idx_categorization_rules_active_priority ON categorization_rules (ledger_id, active, priority);

-- 2g. Rebuild mutation_events with ledger_id FK and composite key for payload joining
DROP TRIGGER IF EXISTS mutation_events_no_update;
DROP TRIGGER IF EXISTS mutation_events_no_delete;

CREATE TABLE mutation_events_new (
    seq                 INTEGER PRIMARY KEY,
    mutation_id         TEXT NOT NULL,
    ledger_id           TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    ts_utc              TEXT NOT NULL CHECK (ts_utc GLOB '????-??-??T??:??:??*Z'),
    operator_session    TEXT NOT NULL,
    action              TEXT NOT NULL,
    staged_count        INTEGER NOT NULL CHECK (staged_count >= 0),
    rules_applied       INTEGER NOT NULL CHECK (rules_applied >= 0),
    rules_created       INTEGER NOT NULL CHECK (rules_created >= 0),
    sha256_before       TEXT NOT NULL CHECK (length(sha256_before) = 64),
    sha256_after        TEXT NOT NULL CHECK (length(sha256_after) = 64),
    prev_mutation_hash  TEXT NOT NULL CHECK (length(prev_mutation_hash) = 64),
    mutation_hash       TEXT NOT NULL CHECK (length(mutation_hash) = 64),
    CHECK (seq >= 1),
    UNIQUE (mutation_id),
    UNIQUE (mutation_hash),
    UNIQUE (seq, mutation_id, ledger_id)
) STRICT;

INSERT INTO mutation_events_new (
    seq, mutation_id, ledger_id, ts_utc, operator_session, action,
    staged_count, rules_applied, rules_created, sha256_before, sha256_after,
    prev_mutation_hash, mutation_hash
)
SELECT
    seq, mutation_id, 'default', ts_utc, operator_session, action,
    staged_count, rules_applied, rules_created, sha256_before, sha256_after,
    prev_mutation_hash, mutation_hash
FROM mutation_events;

DROP TABLE mutation_events;
ALTER TABLE mutation_events_new RENAME TO mutation_events;
CREATE INDEX idx_mutation_events_session ON mutation_events (operator_session);
CREATE INDEX idx_mutation_events_action ON mutation_events (action);
CREATE INDEX idx_mutation_events_ledger ON mutation_events (ledger_id, seq);

CREATE TRIGGER mutation_events_no_update
BEFORE UPDATE ON mutation_events
BEGIN
    SELECT RAISE(ABORT, 'mutation_events is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER mutation_events_no_delete
BEFORE DELETE ON mutation_events
BEGIN
    SELECT RAISE(ABORT, 'mutation_events is append-only: DELETE is forbidden');
END;

-- 3. Capability Tokens Table
CREATE TABLE IF NOT EXISTS capability_tokens (
    token_id TEXT PRIMARY KEY,             -- UUID
    token_hash TEXT NOT NULL UNIQUE,       -- SHA-256 of the bearer token string
    ledger_id TEXT REFERENCES ledgers(ledger_id) ON DELETE CASCADE, -- NULL indicates global admin scope
    is_global INTEGER NOT NULL DEFAULT 0 CHECK(is_global IN (0, 1)),
    role TEXT NOT NULL CHECK(role IN ('READER', 'OPERATOR', 'COMPILER', 'ADMIN')),
    capabilities_json TEXT NOT NULL CHECK(json_valid(capabilities_json) = 1 AND json_type(capabilities_json) = 'array'),
    expires_at TEXT CHECK(expires_at IS NULL OR expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'),
    revoked_at TEXT CHECK(revoked_at IS NULL OR revoked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CHECK((is_global = 1 AND role = 'ADMIN' AND ledger_id IS NULL) OR (is_global = 0 AND ledger_id IS NOT NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_token_hash_lookup ON capability_tokens(token_hash);
```

### Migration `0011_mutation_payloads.sql` (Task 8.4)
```sql
CREATE TABLE IF NOT EXISTS mutation_payloads (
    seq INTEGER PRIMARY KEY,
    mutation_id TEXT NOT NULL UNIQUE,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    payload_schema_version INTEGER NOT NULL DEFAULT 1 CHECK(payload_schema_version >= 1),
    event_type TEXT NOT NULL CHECK(event_type IN ('STAGE_TRANSACTION', 'REVIEW_DECISION', 'COMPILE_LEDGER', 'PRICE_DIRECTIVE', 'RULE_UPDATE')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) = 1),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
    projection_hash_before TEXT NOT NULL CHECK(length(projection_hash_before) = 64),
    projection_hash_after TEXT NOT NULL CHECK(length(projection_hash_after) = 64),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    FOREIGN KEY(seq, mutation_id, ledger_id) REFERENCES mutation_events(seq, mutation_id, ledger_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_mutation_payloads_ledger ON mutation_payloads(ledger_id, seq);

CREATE TRIGGER IF NOT EXISTS mutation_payloads_no_update
BEFORE UPDATE ON mutation_payloads
BEGIN
    SELECT RAISE(ABORT, 'mutation_payloads is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS mutation_payloads_no_delete
BEFORE DELETE ON mutation_payloads
BEGIN
    SELECT RAISE(ABORT, 'mutation_payloads is append-only: DELETE is forbidden');
END;
```

---

## 4. Subsystem Detailed Specifications

### Task 8.1: Multi-Asset Valuation Engine & Historical Price Directives
* **Location:** `src/ironledger/valuation/engine.py`, `src/ironledger/valuation/models.py`
* **Mathematical Conversion Formula (Integer Rational Arithmetic):**
  $$\text{Sign} = \begin{cases} 1 & \text{if } \text{Source Minor} \ge 0 \\ -1 & \text{if } \text{Source Minor} < 0 \end{cases}$$
  $$\text{Target Minor} = \text{Sign} \times \left\lfloor \frac{|\text{Source Minor}| \times \text{Numerator} \times 10^{\max(0, \text{Target Dec} - \text{Source Dec})}}{\text{Denominator} \times 10^{\max(0, \text{Source Dec} - \text{Target Dec})}} \right\rfloor$$
* **Identity Conversion:** If `base_currency == quote_currency`, conversion immediately returns source minor units unchanged (1:1) without database lookup.
* **Ratio Normalization:** Fractions are reduced via `math.gcd(rate_numerator, rate_denominator)` before conversion.
* **Deterministic Price Resolution Order:**
  1. Direct lookup: `WHERE ledger_id = :l AND base_currency = :b AND quote_currency = :q AND directive_date <= :d ORDER BY directive_date DESC, id DESC LIMIT 1`.
  2. Inverse lookup fallback: `WHERE ledger_id = :l AND base_currency = :q AND quote_currency = :b AND directive_date <= :d ORDER BY directive_date DESC, id DESC LIMIT 1`, inverted as `(rate_denominator, rate_numerator)`.
  3. Staleness boundary: If `(requested_date - directive_date).days > max_staleness_days`, raise `StalePriceDirectiveError`. If no directive exists, raise `MissingPriceDirectiveError`.
* **Zero-Import Plaintext Directives (Pure Integer Formatting with Banker's Rounding):**
  Template-based emission uses pure integer arithmetic with Banker's (half-even) rounding (zero floating-point approximation):
  ```python
  def format_beancount_price_directive(
      directive_date: str,
      base_currency: str,
      quote_currency: str,
      rate_numerator: int,
      rate_denominator: int,
      precision_scale: int = 4,
  ) -> str:
      if rate_denominator <= 0 or rate_numerator <= 0:
          raise ValueError("Rate numerator and denominator must be positive integers")
      
      # Pure integer division and Banker's (half-even) tie-breaking
      integer_part = rate_numerator // rate_denominator
      remainder = rate_numerator % rate_denominator
      multiplier = 10 ** precision_scale
      
      quot, subrem = divmod(remainder * multiplier, rate_denominator)
      doubled_subrem = subrem * 2
      
      if doubled_subrem > rate_denominator:
          quot += 1
      elif doubled_subrem == rate_denominator:
          # Exact tie: round to nearest even integer
          if quot % 2 == 1:
              quot += 1
              
      if quot >= multiplier:
          integer_part += 1
          quot -= multiplier
          
      formatted_rate = f"{integer_part}.{quot:0{precision_scale}d}"
      return f"{directive_date} price {base_currency} {formatted_rate} {quote_currency}"
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
  1. `sha256_after` (Beancount manifest hash): Recorded on `mutation_events`. Canonical hash of `.beancount` files on disk (`src/ironledger/manifests.py:compute_ledger_manifest_hash`). Authoritatively computed before and after filesystem emissions, never caller-defaulted.
  2. `projection_hash` (SQLite table state hash): Recorded on `mutation_payloads`. Deterministic SHA-256 computed by `compute_projection_hash(conn, ledger_id)`.
* **Genesis State Anchors:**
  - `GENESIS_MANIFEST_HASH`: Canonical SHA-256 of empty ledger directory structure (all files empty or absent, computed by `compute_ledger_manifest_hash` on clean workspace = `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
  - `GENESIS_PROJECTION_HASH`: Deterministic SHA-256 computed over schema migrations `0001` through `0011` with zero data rows across the static projection tables. Canonical JSON value: `[["staged_transactions",["ledger_id","staged_transaction_id","source_record_id","status","proposed_date","payee","narration","reject_reason"],[]],["staged_postings",["ledger_id","staged_posting_id","staged_transaction_id","source_record_id","role","posting_index","account","minor_units","currency","minor_unit_scale"],[]],["categorization_rules",["ledger_id","rule_id","match_type","pattern","importing_account","target_account","priority","active"],[]],["price_history",["ledger_id","id","directive_date","base_currency","quote_currency","rate_numerator","rate_denominator","precision_scale","source"],[]],["compile_runs",["ledger_id","compile_run_id","beancount_version","compiler_version","input_hash","intended_output_hash","actual_output_hash","status"],[]]]`.
* **Canonical `projection_hash` Algorithm:**
  ```python
  STATIC_PROJECTION_COLUMNS: dict[str, list[str]] = {
      "staged_transactions": [
          "ledger_id", "staged_transaction_id", "source_record_id",
          "status", "proposed_date", "payee", "narration", "reject_reason"
      ],
      "staged_postings": [
          "ledger_id", "staged_posting_id", "staged_transaction_id", "source_record_id",
          "role", "posting_index", "account", "minor_units", "currency", "minor_unit_scale"
      ],
      "categorization_rules": [
          "ledger_id", "rule_id", "match_type", "pattern", "importing_account", "target_account", "priority", "active"
      ],
      "price_history": [
          "ledger_id", "id", "directive_date", "base_currency", "quote_currency",
          "rate_numerator", "rate_denominator", "precision_scale", "source"
      ],
      "compile_runs": [
          "ledger_id", "compile_run_id", "beancount_version", "compiler_version",
          "input_hash", "intended_output_hash", "actual_output_hash", "status"
      ],
  }

  TABLE_ORDER_CLAUSES: dict[str, str] = {
      "staged_transactions": "ledger_id ASC, staged_transaction_id ASC",
      "staged_postings": "ledger_id ASC, staged_transaction_id ASC, posting_index ASC, staged_posting_id ASC",
      "categorization_rules": "ledger_id ASC, rule_id ASC",
      "price_history": "ledger_id ASC, base_currency ASC, quote_currency ASC, directive_date ASC, id ASC",
      "compile_runs": "ledger_id ASC, compile_run_id ASC",
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
    - `proposed_date`: string format `YYYY-MM-DD` (required)
    - `payee`: string (required)
    - `narration`: string (required)
    - `status`: enum `["pending", "categorized", "approved", "rejected"]` (required)
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
    - `prior_status`: enum `["pending", "categorized", "approved", "rejected"]` (required)
    - `new_status`: enum `["pending", "categorized", "approved", "rejected"]` (required)
    - `assigned_account`: string or null (required)
    - `rule_id`: string or null (required)
    - `reject_reason`: string or null (optional)
    - Valid Status Transitions:
      - `pending` $\to$ `categorized` (rule match or manual account assignment)
      - `pending` $\to$ `approved` (manual approval)
      - `pending` $\to$ `rejected` (operator rejection)
      - `categorized` $\to$ `approved` (operator confirmation)
      - `categorized` $\to$ `rejected` (operator rejection)
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
    - `match_type`: enum `["exact", "prefix", "regex"]` (required)
    - `pattern`: string (required)
    - `importing_account`: string or null (required)
    - `target_account`: string (required)
    - `priority`: integer (required)
    - `active`: integer `0` or `1` (required; set to `0` on `DELETE`)

* **Deterministic Plaintext Manifest Rendering Contracts:**
  Only `COMPILE_LEDGER` and `PRICE_DIRECTIVE` perform filesystem mutations:
  ```python
  def render_compiled_ledger_manifest(staging_dir: Path, ledger_id: str, payload: dict[str, Any], staged_transactions: list[Any]) -> None:
      """Render deterministic ledger.beancount manifest into staging directory."""
      ledger_file = staging_dir / f"{ledger_id}.beancount"
      lines = [f";; IronLedger Compiled Ledger: {ledger_id}", f";; Compile Run: {payload['compile_run_id']}", ""]
      for tx in staged_transactions:
          lines.append(f"{tx.proposed_date} * \"{tx.payee}\" \"{tx.narration}\"")
          for p in tx.postings:
              dec_val = p.minor_units / (10 ** p.minor_unit_scale)
              lines.append(f"  {p.account}  {dec_val:.{p.minor_unit_scale}f} {p.currency}")
          lines.append("")
      ledger_file.write_text("\n".join(lines), encoding="utf-8")

  def render_price_directive_manifest(staging_dir: Path, ledger_id: str, payload: dict[str, Any]) -> None:
      """Append deterministic price directive into prices.beancount in staging directory."""
      prices_file = staging_dir / "prices.beancount"
      directive_line = format_beancount_price_directive(
          payload["directive_date"], payload["base_currency"], payload["quote_currency"],
          payload["rate_numerator"], payload["rate_denominator"], payload["precision_scale"]
      )
      current_content = prices_file.read_text(encoding="utf-8") if prices_file.exists() else ""
      new_content = current_content + directive_line + "\n"
      prices_file.write_text(new_content, encoding="utf-8")
  ```

* **Transactional Mutation Dispatch & Authoritative Outbox Commit Protocol:**
  ```python
  def apply_mutation_and_append(
      conn: sqlite3.Connection,
      beancount_root: Path,
      ledger_id: str,
      operator_session: str,
      action: str,
      event_type: str,
      payload: dict[str, Any],
      payload_schema_version: int = 1,
      rules_applied: int = 0,
      rules_created: int = 0,
  ) -> tuple[MutationEvent, MutationPayload]:
      """Apply domain mutation and append mutation event + payload in a deterministic 2-phase commit."""
      # 1. Validate payload schema and tenant consistency
      validate_payload_schema(event_type, payload, payload_schema_version)
      if payload.get("ledger_id") != ledger_id:
          raise ValueError(
              f"Payload ledger_id '{payload.get('ledger_id')}' does not match target ledger_id '{ledger_id}'"
          )
      
      # 2. Stage filesystem mutations to isolated staging directory if applicable
      temp_dir: Path | None = None
      sha256_before = compute_ledger_manifest_hash(beancount_root, ledger_id)
      
      if event_type in ("COMPILE_LEDGER", "PRICE_DIRECTIVE"):
          temp_dir = beancount_root / f".staging_{uuid4().hex}"
          temp_dir.mkdir(parents=True, exist_ok=True)
          # Clone current manifest into staging directory
          for f in beancount_root.glob("*.beancount"):
              shutil.copy2(f, temp_dir / f.name)
          if event_type == "COMPILE_LEDGER":
              staged_txs = fetch_staged_transactions_for_compilation(conn, ledger_id, payload["compiled_tx_ids"])
              render_compiled_ledger_manifest(temp_dir, ledger_id, payload, staged_txs)
          elif event_type == "PRICE_DIRECTIVE":
              render_price_directive_manifest(temp_dir, ledger_id, payload)
          # Flush and fsync
          for f in temp_dir.rglob("*.beancount"):
              with open(f, "a+b") as fp:
                  fp.flush()
                  os.fsync(fp.fileno())
          sha256_after = compute_ledger_manifest_hash(temp_dir, ledger_id)
      else:
          sha256_after = sha256_before
      
      # 3. Begin immediate transaction for SQLite single-writer exclusivity
      conn.execute("BEGIN IMMEDIATE")
      try:
          # 4. Compute projection hash before mutation
          projection_hash_before = compute_projection_hash(conn, ledger_id)
          
          # 5. Dispatch and execute domain table mutations
          dispatch_event_mutation(conn, ledger_id, event_type, payload)
          
          # 6. Compute projection hash after mutation
          projection_hash_after = compute_projection_hash(conn, ledger_id)
          
          # 7. Allocate monotonic sequence and fetch previous hash & timestamp
          cur = conn.execute("SELECT seq, mutation_hash, ts_utc FROM mutation_events ORDER BY seq DESC LIMIT 1")
          last_row = cur.fetchone()
          if not last_row:
              seq = 1
              prev_mutation_hash = "0" * 64
              last_ts = ""
          else:
              seq = last_row[0] + 1
              prev_mutation_hash = last_row[1]
              last_ts = last_row[2]
              
          mutation_id = f"mut_{uuid4().hex}"
          
          # Ensure strictly non-decreasing monotonic timestamp strings
          now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
          ts_utc = max(now_ts, last_ts)
          if ts_utc == last_ts:
              dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00")) + timedelta(microseconds=1)
              ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
          
          # 8. Canonical JSON hash computation
          canonical_payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
          payload_sha256 = hashlib.sha256(canonical_payload_bytes).hexdigest()
          
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
          
          # 9. Insert into mutation_events and mutation_payloads
          conn.execute(
              "INSERT INTO mutation_events (seq, mutation_id, ledger_id, ts_utc, operator_session, action, "
              "staged_count, rules_applied, rules_created, sha256_before, sha256_after, prev_mutation_hash, mutation_hash) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (seq, mutation_id, ledger_id, ts_utc, operator_session, action, 0, rules_applied, rules_created,
               sha256_before, sha256_after, prev_mutation_hash, mutation_hash)
          )
          conn.execute(
              "INSERT INTO mutation_payloads (seq, mutation_id, ledger_id, payload_schema_version, event_type, "
              "payload_json, payload_sha256, projection_hash_before, projection_hash_after, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (seq, mutation_id, ledger_id, payload_schema_version, event_type,
               canonical_payload_bytes.decode("utf-8"), payload_sha256,
               projection_hash_before, projection_hash_after, ts_utc)
          )
          
          # 10. Commit SQLite transaction (authoritative intent recorded)
          conn.execute("COMMIT")
          
      except Exception:
          conn.execute("ROLLBACK")
          if temp_dir and temp_dir.exists():
              shutil.rmtree(temp_dir, ignore_errors=True)
          raise
      
      # 11. Promote staged files to live directory with complete state replacement
      if temp_dir and temp_dir.exists():
          try:
              promote_staged_manifest(temp_dir, beancount_root, ledger_id)
              shutil.rmtree(temp_dir, ignore_errors=True)
          except Exception as promo_err:
              raise ManifestPromotionError(f"Filesystem promotion failed for mutation {mutation_id}: {promo_err}") from promo_err
      
      return (
          MutationEvent(seq=seq, mutation_id=mutation_id, ledger_id=ledger_id, ts_utc=ts_utc,
                        operator_session=operator_session, action=action, mutation_hash=mutation_hash, ...),
          MutationPayload(seq=seq, mutation_id=mutation_id, ledger_id=ledger_id, event_type=event_type, ...)
      )
  ```

* **Complete State Manifest Promotion Contract (`promote_staged_manifest`):**
  1. For every `.beancount` file in `beancount_root` that is absent from `temp_dir`: unlink file (complete state replacement).
  2. For every `.beancount` file in `temp_dir`: execute `os.replace(src, dst)` over target in `beancount_root`.
  3. Flush and fsync directory metadata.
  4. Verify that live manifest `compute_ledger_manifest_hash(beancount_root, ledger_id) == sha256_after`.

* **Startup Manifest Reconciliation Protocol (`reconcile_manifest_on_startup`):**
  - Invoked during database session startup (`DatabaseSessionManager.get_connection`):
  1. For each active ledger in `ledgers`:
     - Query all `mutation_events` rows for `ledger_id` ordered by `seq ASC`.
     - Compute current live manifest hash $H_{\text{live}}$.
     - If no events exist: assert $H_{\text{live}} == \text{GENESIS\_MANIFEST\_HASH}$.
     - If events exist:
       - Let $M_{\text{latest}}$ be the last event in sequence.
       - If $H_{\text{live}} == M_{\text{latest}}.\text{sha256\_after}$, filesystem is synchronized.
       - If $H_{\text{live}} != M_{\text{latest}}.\text{sha256\_after}$:
         - Search historical sequence for event $M_k$ where $M_k.\text{sha256\_before} == H_{\text{live}}$.
         - If found, sequentially re-emit plain text manifests from the payloads of $M_k \dots M_{\text{latest}}$, verifying each step advances the hash to the recorded `sha256_after`.
         - If $H_{\text{live}}$ does not match any historical point in the chain, raise `ManifestDesyncError` (unauthorized out-of-band edit or corruption).

* **Deterministic Replay Engine Algorithm:**
  1. Resolve `target_sequence`: If `target_timestamp` is provided, select `MAX(seq)` where `ts_utc <= target_timestamp` ordered strictly by `seq ASC`.
  2. Query live database max sequence $S_{\text{max}} = \text{SELECT MAX(seq) FROM mutation\_events}$. If `target_sequence >` $S_{\text{max}}$, raise `ReplayBoundaryError`.
  3. **Phase 1: Global Sequence & Merkle Chain Integrity Verification (Global $1 \dots \text{target\_seq}$):**
     - Query all `mutation_events` and `mutation_payloads` from `seq = 1` to `target_seq` ordered by `seq ASC`.
     - Assert `seq` sequence is strictly contiguous $1, 2, \dots, N$ with zero gaps.
     - Assert timestamps `ts_utc` are strictly non-decreasing monotonic.
     - For each row:
       - Validate `payload_sha256 == sha256(payload_json)`.
       - Recompute canonical `mutation_hash` from `canonical_dict` and assert equality with `event.mutation_hash`.
       - Assert `event.prev_mutation_hash` matches prior event's `mutation_hash` (or $0^{64}$ for `seq = 1`).
  4. **Phase 2: Tenant-Scoped Dual-Fingerprint Replay (Projection + Filesystem):**
     - Spin up an in-memory SQLite projection database (`:memory:`), load schema `0001` through `0011`.
     - Create an ephemeral temporary directory for Beancount plaintext manifest playback.
     - Assert initial in-memory `compute_projection_hash(mem_conn, target_ledger_id) == GENESIS_PROJECTION_HASH`.
     - Assert initial ephemeral manifest `compute_ledger_manifest_hash(temp_manifest_dir, target_ledger_id) == GENESIS_MANIFEST_HASH`.
     - Stream the validated events from `seq = 1` to `target_seq`:
       - If `event.ledger_id == target_ledger_id`:
         - Validate in-memory `compute_projection_hash(mem_conn, target_ledger_id) == payload.projection_hash_before`.
         - Execute `dispatch_event_mutation(mem_conn, target_ledger_id, payload.event_type, json.loads(payload.payload_json))`.
         - Validate resulting in-memory `compute_projection_hash(mem_conn, target_ledger_id) == payload.projection_hash_after`.
         - If event has filesystem emissions (`COMPILE_LEDGER` or `PRICE_DIRECTIVE`):
           - Render Beancount plaintext directives into ephemeral directory using `render_compiled_ledger_manifest` / `render_price_directive_manifest`.
           - Validate resulting ephemeral manifest hash equals `event.sha256_after`.
       - If `event.ledger_id != target_ledger_id`:
         - Skip projection mutation (tenant isolation).
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
* **Protected Operations Inventory Matrix:**
  | Operation / Route | Scope Required | Minimum Role | Target Ledger Extraction |
  |---|---|---|---|
  | `GET /api/v1/ledger/{id}/*` | `ledger:read` | `READER` | Path parameter `{id}` |
  | `GET /api/v1/lineage/{id}/*` | `ledger:read` | `READER` | Path parameter `{id}` |
  | `POST /api/v1/replay/{id}/*` | `audit:replay` | `READER` | Path parameter `{id}` |
  | `POST /api/v1/staging/{id}/ingest` | `staging:write` | `OPERATOR` | Path parameter `{id}` |
  | `POST /api/v1/staging/{id}/decision` | `review:decide` | `OPERATOR` | Path parameter `{id}` |
  | `POST /api/v1/rules/{id}/*` | `review:decide` | `OPERATOR` | Path parameter `{id}` |
  | `POST /api/v1/prices/{id}/*` | `staging:write` | `OPERATOR` | Path parameter `{id}` |
  | `POST /api/v1/compile/{id}/execute` | `compile:execute` | `COMPILER` | Path parameter `{id}` |
  | `POST /api/v1/auth/tokens` | `*` (Admin) | `ADMIN` | Global or body `ledger_id` |
  | `POST /api/v1/ledgers` | `*` (Admin) | `ADMIN` | Global admin scope required |
* **Token Security, Issuance Validation & Tenant Policy:**
  - Bearer tokens generated via `secrets.token_hex(32)` (`il_cap_<hex64>`).
  - `create_capability_token(conn, role, ledger_id, requested_scopes)`: validates that `requested_scopes` are a subset of `ROLE_CEILINGS[role]` before inserting row into `capability_tokens`.
  - `PolicyEnforcer.authorize(token, required_scope, target_ledger_id)`:
    1. Look up token by SHA-256 hash.
    2. Fail closed if `revoked_at` is NOT NULL.
    3. Fail closed if `expires_at` is NOT NULL and `expires_at <= current_utc_iso`.
    4. Check ledger scope: `token.is_global == 1` (Admin) OR `token.ledger_id == target_ledger_id`.
    5. Check role ceiling: verify that granted scopes in `capabilities_json` do not exceed the role's maximum allowed scopes.
    6. Check `required_scope` in `token.capabilities` or `token.capabilities == ["*"]`.
* **Centralized Policy Enforcement:** Invoked across CLI commands, MCP tools, and web endpoints. Unauthenticated requests or requests with invalid tokens fail closed with HTTP 401 Unauthorized / `UnauthorizedError`.

### Task 8.6: Acceptance Regression Suite & Phase 8 Exit Evidence
* **Location:** `tests/test_valuation.py`, `tests/test_lineage.py`, `tests/test_multi_ledger.py`, `tests/test_replay.py`, `tests/test_capabilities.py`, `tests/test_phase8_exit_contract.py`
* **Static Analysis Import Guard:** AST scanner in `tests/test_phase8_exit_contract.py` implements a symbol-tracking AST visitor checking all Python source files in `src/ironledger/**/*.py`:
  - Tracks alias bindings across `import x as y`, `from x import y as z`.
  - Flags direct and aliased imports of `beancount` or submodules `beancount.*`.
  - Flags direct and aliased invocations of `importlib.import_module`, `__import__`, or `builtins.__import__` targeting `beancount`.
  - Flags dynamic `getattr(mod, "import_module")("beancount")`.
  - AST scanner test includes positive and negative test fixtures verifying scanner detection fidelity.
* **Exit Evidence Artifact:** `docs/meta/phases/ironledger-phase-8-evidence.md`.

---

## 5. Verification & Test Plan

1. **Valuation Suite (`tests/test_valuation.py`):**
   - Verify integer rational price conversion with 0 floating-point drift across mixed decimal precisions (USD 2-dec, BTC 8-dec, AAPL 4-dec).
   - Verify bounded preceding price resolution, stale price rejection, identity same-currency conversion, and inverse quote resolution.
   - Verify Beancount price directive string template output with zero runtime Beancount imports and pure integer Banker's rounding.
2. **Lineage Suite (`tests/test_lineage.py`):**
   - Verify bi-directional recursive CTE DAG traversals within tenant boundaries (posting $\to$ evidence hash, and evidence hash $\to$ postings).
   - Verify self-edge rejection and unbounded cycle prevention rejection and transactional atomicity on edge registration.
3. **Multi-Ledger Suite (`tests/test_multi_ledger.py`):**
   - Verify complete isolation of staging queues, lineage nodes, review rules, and concurrent compilation locks across multiple `ledger_id`s.
   - Verify composite primary and foreign key constraints reject cross-tenant record linking at the SQLite database layer.
   - Verify multi-entity consolidated balance aggregation.
4. **Replay Suite (`tests/test_replay.py`):**
   - Verify genesis state anchor verification, global sequence contiguity, Merkle chain verification, and dual-fingerprint payload replay into ephemeral in-memory database and manifest directory validating `projection_hash_before`/`after` and `sha256_before`/`after`.
   - Verify zero side-effects on live database files.
5. **RBAC Suite (`tests/test_capabilities.py`):**
   - Verify token creation with issuance-time ceiling checks, constant-time hash verification, role ceiling enforcement, expiration/revocation gating, and global vs tenant-scoped validation.
6. **Phase 8 Exit Contract (`tests/test_phase8_exit_contract.py`):**
   - Run end-to-end integration scenario combining multi-asset pricing, lineage tracing, multi-tenant isolation, replay, and RBAC enforcement.
