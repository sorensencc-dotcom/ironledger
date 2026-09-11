# Phase 8 Specification & Technical Design: Multi-Asset Valuation, Ledger Lineage & Audit Replay

**Program:** IronLedger  
**Milestone:** Phase 8 — Multi-Asset Valuation, Ledger Lineage & Audit Replay  
**Governed Repo:** `C:\dev\IronLedger`  
**Governed Docs:** `C:\dev\docs\meta\`  
**Date:** 2026-09-10  
**Version:** 1.0.0 (Hardened Canonical Specification - Pass 18 Remediation)  
**Specification Role:** Canonical Implementation Specification & Governed Mirror  
**Change Identifier:** `IL-SPEC-PHASE-8-v1.0`  
**Decision Record:** `IL-DECISION-PHASE-8-SPEC`  
**Governance Authority:** Tier 1 Architecture Board  
**Status:** Pre-Implementation Architectural Specification & Design Contract (Gate 1)  

---

## 1. Executive Summary & Core Invariants

Phase 8 expands IronLedger from single-currency transaction recording into a multi-asset valuation, bi-directional lineage tracking, multi-tenant ledger isolation, deterministic point-in-time audit replay, and cryptographic capability-based access control engine.

### Upstream Invariants Inherited & Enforced

1. **Exact Rational Integer Arithmetic & Zero Float Drift:** Multi-asset and commodity conversions operate exclusively on integer minor units and rational fraction ratios $(N / D)$ with strict mathematical sign symmetry and zero IEEE 754 floating-point drift. Strict integer type guards (`type(v) is int and not isinstance(v, bool)`) enforce pure integer inputs across all valuation, formatting, and conversion functions. Exact Banker's half-even integer rounding applies uniformly across all precisions, including `precision_scale == 0`. No float division `/` is permitted anywhere in valuation or rendering code paths, strictly enforced by AST guards.
2. **Bi-Directional Provenance Lineage:** Every compiled posting references its staged transaction, source record, and raw evidence SHA-256 blob through a tenant-isolated acyclic directed graph (DAG) stored in SQLite with atomic transactional registration, strict self-edge rejection (`source != target`), and unbounded insertion-time cycle detection.
3. **Deterministic Point-in-Time Replay & Cryptographic Audit Authenticity:** The mutation ledger chain ($H_0 \to H_k$) verifies the global contiguous sequence, Merkle chain continuity, authority digital signatures/HMACs, and external out-of-band trust anchor commitments (`.ironledger/anchors/<ledger_id>.anchor.json`). Replay executes schema-versioned canonical self-contained event mutation payloads into an ephemeral in-memory projection database and ephemeral filesystem manifest to reconstruct exact historical state snapshots at any sequence number without mutating live files.
4. **Tenant & Entity Domain Isolation:** Explicit `ledger_id` validation (`^[A-Za-z0-9_-]+$`), symlink refusal and canonical path boundary enforcement (`Path.relative_to`), composite primary keys (`PRIMARY KEY(ledger_id, entity_id)`), composite foreign keys (`FOREIGN KEY(ledger_id, parent_id) REFERENCES parent_table(ledger_id, parent_id)`), tenant-isolated directory subtrees (`beancount_root/ledgers/<ledger_id>/current/`), tenant-scoped compile lockfiles (`.ironledger/.compile.<ledger_id>.lock`), and tenant-scoped uniqueness constraints enforce strict cross-tenant isolation at the relational schema and filesystem boundaries with mandatory `PRAGMA foreign_keys = ON;`.
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

## 3. Database Schema Architecture & Migration Contract

Phase 8 schema migrations use `STRICT` table definitions and forward-only SQLite migration scripts tracked in `schema_migrations` with SHA-256 checksum verification. Migration scripts reside authoritatively in `src/ironledger/db/schema/` (`0001_core_schema.sql` through `0011_mutation_payloads.sql`) and are executed by `src/ironledger/db/migrations.py` / `src/ironledger/governance/migrations.py`.

### Migration Schema DDL (Authoritative Governance Schema)
```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version        INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    checksum       TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
) STRICT;
```

### Migration Runner Execution Lifecycle (`ironledger.governance.migrations`)
1. **Connection Setup & Deterministic SQL Function Registration:**
   - Every SQLite connection configured by `get_connection()` or migration runner registers deterministic Python cryptographic functions prior to DDL execution, bound to the active `authority_key`:
     ```python
     conn.create_function(
         "sha256_hex",
         1,
         lambda val: hashlib.sha256(val.encode("utf-8") if isinstance(val, str) else bytes(val)).hexdigest(),
         deterministic=True,
     )
     conn.create_function(
         "sign_authority_sql",
         1,
         lambda digest: sign_authority_payload(digest, authority_key),
         deterministic=True,
     )
     ```
2. **Discovery & Contiguity Validation:**
   - Discovers migration files `NNNN_<name>.sql` in `src/ironledger/db/schema/`.
   - Parses integer version numbers and sorts ascending.
   - Asserts versions form a strictly contiguous sequence starting at 1 ($1, 2, \dots, N$). If any version is missing or duplicate, raises `MigrationError`.
3. **Preflight Checksum Verification:**
   - Reads `schema_migrations` rows from database.
   - For every already-applied version $v \in \{1 \dots K\}$:
     - Computes SHA-256 checksum of the migration file on disk.
     - Asserts `recorded.checksum == computed_checksum` and `recorded.name == file.name`.
     - If mismatch, raises `ChecksumMismatch(version, name, recorded, computed)`.
4. **Transaction-Preserving Statement Execution:**
   - Splits the migration SQL into individual executable statements using a semicolon-aware SQL tokenizer, executing them sequentially within an explicit `BEGIN IMMEDIATE ... COMMIT` block to ensure transactional atomicity across DDL, DML, foreign key checks, and metadata recording:
     ```python
     # 1. Connection-level preflight: disable foreign keys outside transaction for table rebuild safety
     conn.execute("PRAGMA foreign_keys = OFF")
     try:
         # 2. Acquire exclusive writer lock
         conn.execute("BEGIN IMMEDIATE")
         
         # 3. Execute migration statements individually
         statements = split_sql_statements(migration_sql)
         for stmt in statements:
             if stmt.strip():
                 conn.execute(stmt)
         
         # 4. Verify foreign key integrity across entire database
         cur = conn.execute("PRAGMA foreign_key_check")
         fk_violations = cur.fetchall()
         if fk_violations:
             raise ForeignKeyViolationError(f"Foreign key violations after migration {v}: {fk_violations}")
             
         # 5. Record applied migration in same transaction
        normalized_sql_bytes = migration_sql.replace("\r\n", "\n").encode("utf-8")
        checksum = hashlib.sha256(normalized_sql_bytes).hexdigest()
        applied_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum, applied_at_utc) VALUES (?, ?, ?, ?)",
            (v, migration_name, checksum, applied_at),
        )
        
        # 6. Commit migration
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        # 7. Restore foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        
5. **Post-Migration Trust Anchor Establishment:**
   - After applying migrations, the runner ensures external trust anchors exist for all active ledgers:
     ```python
     anchor_dir = beancount_root / ".ironledger" / "anchors"
     anchor_dir.mkdir(parents=True, exist_ok=True)
     for (ledger_id,) in conn.execute("SELECT ledger_id FROM ledgers").fetchall():
         cur = conn.execute(
             "SELECT e.seq, e.mutation_id, e.mutation_hash, e.prev_mutation_hash, e.sha256_after, "
             "e.authority_signature, e.ts_utc, p.projection_hash_after "
             "FROM mutation_events e "
             "JOIN mutation_payloads p ON e.seq = p.seq AND e.ledger_id = p.ledger_id "
             "WHERE e.ledger_id = ? ORDER BY e.seq DESC LIMIT 1",
             (ledger_id,),
         )
         row = cur.fetchone()
         anchor_file = anchor_dir / f"{ledger_id}.anchor.json"
         if row:
             seq, m_id, m_hash, p_hash, s_after, sig, ts, proj_after = row
             anchor_data = {
                 "anchor_version": 1,
                 "ledger_id": ledger_id,
                 "seq": seq,
                 "mutation_id": m_id,
                 "mutation_hash": m_hash,
                 "prev_mutation_hash": p_hash,
                 "manifest_hash": s_after,
                 "projection_hash": proj_after,
                 "authority_signature": sig,
                 "anchored_at_utc": ts,
             }
             temp_a = anchor_dir / f".a_{uuid4().hex}.tmp"
             temp_a.write_text(json.dumps(anchor_data, indent=2), encoding="utf-8")
             os.replace(temp_a, anchor_file)
     ```
     ```

### Entity & Key Isolation Coverage Matrix
| Entity Table | Primary Key | Foreign Key Reference | Tenant Uniqueness |
|---|---|---|---|
| `ledgers` | `(ledger_id)` | Root tenant catalog | `UNIQUE(ledger_id)` |
| `source_documents` | `(ledger_id, source_document_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, content_sha256)` |
| `source_records` | `(ledger_id, source_record_id)` | `FOREIGN KEY(ledger_id, source_document_id) REFERENCES source_documents(ledger_id, source_document_id)` | `UNIQUE(ledger_id, source_document_id, record_index)` |
| `staged_transactions` | `(ledger_id, staged_transaction_id)` | `FOREIGN KEY(ledger_id, source_record_id) REFERENCES source_records(ledger_id, source_record_id)` | `UNIQUE(ledger_id, identity_algo_version, identity_fingerprint)` |
| `staged_postings` | `(ledger_id, staged_posting_id)` | `FOREIGN KEY(ledger_id, staged_transaction_id) REFERENCES staged_transactions(ledger_id, staged_transaction_id)`<br>`FOREIGN KEY(ledger_id, source_record_id) REFERENCES source_records(ledger_id, source_record_id)` | `UNIQUE(ledger_id, staged_transaction_id, posting_index)` |
| `categorization_rules` | `(ledger_id, rule_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, match_type, pattern, importing_account)` |
| `price_history` | `(ledger_id, id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, directive_date, base_currency, quote_currency)` |
| `lineage_nodes` | `(ledger_id, node_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(ledger_id, node_id)` |
| `lineage_edges` | `(ledger_id, source_node_id, target_node_id, relationship)` | `FOREIGN KEY(ledger_id, source_node_id) REFERENCES lineage_nodes(ledger_id, node_id)`<br>`FOREIGN KEY(ledger_id, target_node_id) REFERENCES lineage_nodes(ledger_id, node_id)` | `PRIMARY KEY` |
| `compile_runs` | `(ledger_id, compile_run_id)` | `REFERENCES ledgers(ledger_id)` | `PRIMARY KEY(ledger_id, compile_run_id)` |
| `mutation_events` | `(seq)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(mutation_id)`, `UNIQUE(mutation_hash)`, `UNIQUE(seq, mutation_id, ledger_id)` |
| `mutation_payloads` | `(seq)` | `FOREIGN KEY(seq, mutation_id, ledger_id) REFERENCES mutation_events(seq, mutation_id, ledger_id)` | `UNIQUE(mutation_id)` |
| `capability_tokens` | `(token_id)` | `REFERENCES ledgers(ledger_id)` | `UNIQUE(token_hash)` |

---

### Migration Scripts DDL

#### `0008_price_history.sql` (Task 8.1)
```sql
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER NOT NULL,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    directive_date TEXT NOT NULL CHECK(length(directive_date) = 10 AND directive_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND directive_date NOT GLOB '*[^0-9-]*'),
    base_currency TEXT NOT NULL CHECK(length(base_currency) >= 1 AND length(base_currency) <= 12 AND base_currency NOT GLOB '*[^A-Z0-9_.-]*'),
    quote_currency TEXT NOT NULL CHECK(length(quote_currency) >= 1 AND length(quote_currency) <= 12 AND quote_currency NOT GLOB '*[^A-Z0-9_.-]*'),
    rate_numerator INTEGER NOT NULL CHECK(rate_numerator > 0),
    rate_denominator INTEGER NOT NULL CHECK(rate_denominator > 0),
    precision_scale INTEGER NOT NULL DEFAULT 4 CHECK(precision_scale >= 0 AND precision_scale <= 18),
    source TEXT NOT NULL CHECK(source IN ('MANUAL', 'POLLED_FEED', 'EXCHANGE_API')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(ledger_id, id),
    UNIQUE(ledger_id, directive_date, base_currency, quote_currency)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_price_history_lookup 
ON price_history(ledger_id, base_currency, quote_currency, directive_date DESC, id DESC);
```

#### `0009_ledger_lineage.sql` (Task 8.2)
```sql
CREATE TABLE IF NOT EXISTS lineage_nodes (
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL CHECK(length(node_id) >= 1 AND length(node_id) <= 64 AND node_id NOT GLOB '*[^a-zA-Z0-9_-]*'),
    node_type TEXT NOT NULL CHECK(node_type IN ('EVIDENCE_BLOB', 'SOURCE_RECORD', 'STAGED_TX', 'POSTING')),
    entity_ref TEXT NOT NULL CHECK(length(entity_ref) >= 1 AND length(entity_ref) <= 128),
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

#### `0010_multi_ledger_rbac.sql` (Tasks 8.3 & 8.5)
```sql
-- 1. Create root tenant ledgers table
CREATE TABLE IF NOT EXISTS ledgers (
    ledger_id TEXT PRIMARY KEY CHECK(length(ledger_id) >= 1 AND length(ledger_id) <= 64 AND ledger_id NOT GLOB '*[^a-zA-Z0-9_-]*'),
    name TEXT NOT NULL CHECK(length(name) >= 1 AND length(name) <= 128),
    base_currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(base_currency) >= 1 AND length(base_currency) <= 12 AND base_currency NOT GLOB '*[^A-Z0-9_.-]*'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

INSERT OR IGNORE INTO ledgers (ledger_id, name, base_currency) VALUES ('default', 'Default Ledger', 'USD');

-- 2. Rebuild Tables in Strict Dependency Order with Composite Foreign Keys

-- 2a. Rebuild source_documents with (ledger_id, source_document_id) composite identity
CREATE TABLE source_documents_backup_0010 AS SELECT * FROM source_documents;
DROP TABLE source_documents;

CREATE TABLE source_documents (
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

INSERT INTO source_documents (
    source_document_id, ledger_id, mime_type, encoding, provenance,
    acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc
)
SELECT
    source_document_id, 'default', mime_type, encoding, provenance,
    acquisition_time_utc, content_sha256, raw_payload_ref, created_at_utc
FROM source_documents_backup_0010;
DROP TABLE source_documents_backup_0010;

-- 2b. Rebuild source_records with composite FK to source_documents
CREATE TABLE source_records_backup_0010 AS SELECT * FROM source_records;
DROP TABLE source_records;

CREATE TABLE source_records (
    source_record_id   TEXT NOT NULL,
    ledger_id          TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    source_document_id TEXT NOT NULL,
    record_index       INTEGER NOT NULL CHECK (record_index >= 0),
    canonical_payload  TEXT NOT NULL,
    content_sha256     TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_at_utc     TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    PRIMARY KEY (ledger_id, source_record_id),
    UNIQUE (ledger_id, source_document_id, record_index),
    FOREIGN KEY (ledger_id, source_document_id) REFERENCES source_documents (ledger_id, source_document_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

INSERT INTO source_records (
    source_record_id, ledger_id, source_document_id, record_index, canonical_payload, content_sha256, created_at_utc
)
SELECT
    source_record_id, 'default', source_document_id, record_index, canonical_payload, content_sha256, created_at_utc
FROM source_records_backup_0010;
DROP TABLE source_records_backup_0010;

-- 2c. Rebuild staged_transactions with composite FK to source_records
CREATE TABLE staged_transactions_backup_0010 AS SELECT * FROM staged_transactions;
DROP TABLE staged_transactions;

CREATE TABLE staged_transactions (
    staged_transaction_id TEXT NOT NULL,
    ledger_id             TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT,
    source_record_id      TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'categorized', 'approved', 'rejected')),
    proposed_date         TEXT NOT NULL CHECK (length(proposed_date) = 10 AND proposed_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND proposed_date NOT GLOB '*[^0-9-]*'),
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
    FOREIGN KEY (ledger_id, source_record_id) REFERENCES source_records (ledger_id, source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

INSERT INTO staged_transactions (
    staged_transaction_id, ledger_id, source_record_id, status, proposed_date, payee, narration,
    identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc,
    reject_reason, categorized_at_utc
)
SELECT
    staged_transaction_id, 'default', source_record_id, status, proposed_date, payee, narration,
    identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc,
    reject_reason, categorized_at_utc
FROM staged_transactions_backup_0010;
DROP TABLE staged_transactions_backup_0010;

-- 2d. Rebuild staged_postings with composite FK to staged_transactions and source_records
CREATE TABLE staged_postings_backup_0010 AS SELECT * FROM staged_postings;
DROP TABLE staged_postings;

CREATE TABLE staged_postings (
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
    currency              TEXT NOT NULL CHECK (length(currency) >= 1 AND length(currency) <= 12 AND currency NOT GLOB '*[^A-Z0-9_.-]*'),
    minor_unit_scale      INTEGER NOT NULL CHECK (minor_unit_scale >= 0 AND minor_unit_scale <= 18),
    created_at_utc        TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    CHECK (role = 'contra' OR account IS NOT NULL),
    PRIMARY KEY (ledger_id, staged_posting_id),
    UNIQUE (ledger_id, staged_transaction_id, posting_index),
    FOREIGN KEY (ledger_id, staged_transaction_id) REFERENCES staged_transactions (ledger_id, staged_transaction_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    FOREIGN KEY (ledger_id, source_record_id) REFERENCES source_records (ledger_id, source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

INSERT INTO staged_postings (
    staged_posting_id, ledger_id, staged_transaction_id, source_record_id, role,
    posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc
)
SELECT
    staged_posting_id, 'default', staged_transaction_id, source_record_id, role,
    posting_index, account, minor_units, currency, minor_unit_scale, created_at_utc
FROM staged_postings_backup_0010;
DROP TABLE staged_postings_backup_0010;

-- 2e. Rebuild categorization_rules
CREATE TABLE categorization_rules_backup_0010 AS SELECT * FROM categorization_rules;
DROP TABLE categorization_rules;

CREATE TABLE categorization_rules (
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

INSERT INTO categorization_rules (
    rule_id, ledger_id, match_type, pattern, importing_account, target_account,
    priority, active, created_at_utc, disabled_at_utc
)
SELECT
    rule_id, 'default', match_type, pattern, importing_account, target_account,
    priority, active, created_at_utc, disabled_at_utc
FROM categorization_rules_backup_0010;
DROP TABLE categorization_rules_backup_0010;

-- 2f. Create compile_runs table with tenant isolation
CREATE TABLE IF NOT EXISTS compile_runs (
    compile_run_id TEXT NOT NULL,
    ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    beancount_version TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash) = 64),
    intended_output_hash TEXT NOT NULL CHECK(length(intended_output_hash) = 64),
    actual_output_hash TEXT NOT NULL CHECK(length(actual_output_hash) = 64),
    status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'FAILED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY(ledger_id, compile_run_id)
) STRICT;

-- 2g. Rebuild mutation_events with ledger_id FK and composite key for payload joining
DROP TRIGGER IF EXISTS mutation_events_no_update;
DROP TRIGGER IF EXISTS mutation_events_no_delete;

CREATE TABLE mutation_events_backup_0010 AS SELECT * FROM mutation_events;
DROP TABLE mutation_events;

CREATE TABLE mutation_events (
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
    authority_signature TEXT NOT NULL CHECK (length(authority_signature) >= 64),
    CHECK (seq >= 1),
    UNIQUE (mutation_id),
    UNIQUE (mutation_hash),
    UNIQUE (seq, mutation_id, ledger_id)
) STRICT;

-- In migration 0010, legacy pre-Phase 8 events are sealed with deterministic migration transition signatures
INSERT INTO mutation_events (
    seq, mutation_id, ledger_id, ts_utc, operator_session, action,
    staged_count, rules_applied, rules_created, sha256_before, sha256_after,
    prev_mutation_hash, mutation_hash, authority_signature
)
SELECT
    seq, mutation_id, 'default', ts_utc, operator_session, action,
    staged_count, rules_applied, rules_created, sha256_before, sha256_after,
    prev_mutation_hash, mutation_hash,
    -- Cryptographic authority signature over canonical digest using registered authority key
    sign_authority_sql(
        sha256_hex(
            seq || ':' || mutation_id || ':default:' || ts_utc || ':' ||
            mutation_hash || ':' || prev_mutation_hash || ':' ||
            sha256_after || ':1e3b03f64f2e93ca3cde5c5fd5e63b6194416b8b31871df1153ab643f7342314'
        )
    )
FROM mutation_events_backup_0010;
DROP TABLE mutation_events_backup_0010;

CREATE INDEX idx_source_records_doc ON source_records (ledger_id, source_document_id);
CREATE INDEX idx_staged_source_record ON staged_transactions (ledger_id, source_record_id);
CREATE INDEX idx_staged_tx_ledger ON staged_transactions (ledger_id, status);
CREATE INDEX idx_staged_postings_transaction ON staged_postings (ledger_id, staged_transaction_id);
CREATE INDEX idx_staged_postings_source ON staged_postings (ledger_id, source_record_id);
CREATE INDEX idx_categorization_rules_active_priority ON categorization_rules (ledger_id, active, priority);
CREATE INDEX idx_mutation_events_session ON mutation_events (operator_session);
CREATE INDEX idx_mutation_events_action ON mutation_events (action);
CREATE INDEX idx_mutation_events_ledger ON mutation_events (ledger_id, seq);
CREATE INDEX idx_compile_runs_lookup ON compile_runs (ledger_id, compile_run_id);

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
    expires_at TEXT CHECK(expires_at IS NULL OR (expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND expires_at NOT GLOB '*[^0-9T:.-Z]*')),
    revoked_at TEXT CHECK(revoked_at IS NULL OR (revoked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND revoked_at NOT GLOB '*[^0-9T:.-Z]*')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CHECK((is_global = 1 AND role = 'ADMIN' AND ledger_id IS NULL) OR (is_global = 0 AND role IN ('READER', 'OPERATOR', 'COMPILER', 'ADMIN') AND ledger_id IS NOT NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_token_hash_lookup ON capability_tokens(token_hash);
```

#### `0011_mutation_payloads.sql` (Task 8.4)
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

-- Backfill mutation_payloads for all pre-Phase 8 legacy events
INSERT OR IGNORE INTO mutation_payloads (
    seq, mutation_id, ledger_id, payload_schema_version, event_type,
    payload_json, payload_sha256, projection_hash_before, projection_hash_after, created_at
)
SELECT
    seq,
    mutation_id,
    ledger_id,
    1,
    'COMPILE_LEDGER',
    json_object(
        'action', action,
        'rules_applied', rules_applied,
        'rules_created', rules_created,
        'sha256_before', sha256_before,
        'sha256_after', sha256_after,
        'staged_count', staged_count
    ),
    sha256_hex(
        json_object(
            'action', action,
            'rules_applied', rules_applied,
            'rules_created', rules_created,
            'sha256_before', sha256_before,
            'sha256_after', sha256_after,
            'staged_count', staged_count
        )
    ),
    '1e3b03f64f2e93ca3cde5c5fd5e63b6194416b8b31871df1153ab643f7342314',
    '1e3b03f64f2e93ca3cde5c5fd5e63b6194416b8b31871df1153ab643f7342314',
    ts_utc
FROM mutation_events;
```

---

## 4. Subsystem Detailed Specifications

### Task 8.1: Multi-Asset Valuation Engine & Historical Price Directives
* **Location:** `src/ironledger/valuation/engine.py`, `src/ironledger/valuation/models.py`, `src/ironledger/valuation/formatting.py`
* **Mathematical Conversion Formula (Integer Rational Arithmetic with Banker's Half-Even Rounding):**
  $$\text{Sign} = \begin{cases} 1 & \text{if } \text{Source Minor} \ge 0 \\ -1 & \text{if } \text{Source Minor} < 0 \end{cases}$$
  ```python
  def convert_amount_rational(
      source_minor: int,
      source_scale: int,
      rate_numerator: int,
      rate_denominator: int,
      target_scale: int,
  ) -> int:
      """Convert currency amount using exact Banker's half-even integer rational arithmetic.
      
      Computes: source_minor * (rate_numerator / rate_denominator) * (10^target_scale / 10^source_scale)
      with zero float operations and exact round-half-to-even tie-breaking.
      """
      # Strict integer type and range assertions
      if type(source_minor) is not int or isinstance(source_minor, bool):
          raise TypeError("source_minor must be an integer (not bool or float)")
      if type(source_scale) is not int or isinstance(source_scale, bool) or not (0 <= source_scale <= 18):
          raise TypeError("source_scale must be an integer between 0 and 18")
      if type(rate_numerator) is not int or isinstance(rate_numerator, bool) or rate_numerator <= 0:
          raise TypeError("rate_numerator must be a positive integer")
      if type(rate_denominator) is not int or isinstance(rate_denominator, bool) or rate_denominator <= 0:
          raise TypeError("rate_denominator must be a positive integer")
      if type(target_scale) is not int or isinstance(target_scale, bool) or not (0 <= target_scale <= 18):
          raise TypeError("target_scale must be an integer between 0 and 18")
      
      scale_diff = target_scale - source_scale
      if scale_diff >= 0:
          num = abs(source_minor) * rate_numerator * (10 ** scale_diff)
          denom = rate_denominator
      else:
          num = abs(source_minor) * rate_numerator
          denom = rate_denominator * (10 ** (-scale_diff))
          
      quot, rem = divmod(num, denom)
      doubled_rem = rem * 2
      
      if doubled_rem > denom:
          quot += 1
      elif doubled_rem == denom:
          # Exact tie: round to nearest even integer
          if quot % 2 == 1:
              quot += 1
              
      return -quot if source_minor < 0 else quot
  ```
* **Identity Conversion:** If `base_currency == quote_currency`, conversion returns source minor units unchanged (1:1) without database lookup.
* **Ratio Normalization:** Fractions are reduced via `math.gcd(rate_numerator, rate_denominator)` before storage and conversion.
* **Deterministic Price Resolution Order:**
  1. Direct lookup: `WHERE ledger_id = :l AND base_currency = :b AND quote_currency = :q AND directive_date <= :d ORDER BY directive_date DESC, id DESC LIMIT 1`.
  2. Inverse lookup fallback: `WHERE ledger_id = :l AND base_currency = :q AND quote_currency = :b AND directive_date <= :d ORDER BY directive_date DESC, id DESC LIMIT 1`, inverted as `(rate_denominator, rate_numerator)`.
  3. Staleness boundary: If `(requested_date - directive_date).days > max_staleness_days`, raise `StalePriceDirectiveError`. If no directive exists, raise `MissingPriceDirectiveError`.
* **Zero-Import Plaintext Directives (Pure Integer Formatting with Strict Calendar & Integer Validation):**
  ```python
  import re
  from datetime import datetime

  CURRENCY_PATTERN = re.compile(r"^[A-Z0-9_.-]{1,12}$")

  def validate_calendar_date(date_str: str) -> str:
      if not isinstance(date_str, str) or len(date_str) != 10:
          raise ValueError(f"Invalid date string format: {date_str!r}")
      try:
          parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
      except ValueError as e:
          raise ValueError(f"Invalid calendar date {date_str!r}: {e}") from e
      return parsed.strftime("%Y-%m-%d")

  def format_minor_units(minor_units: int, scale: int) -> str:
      """Format minor units to decimal string using pure integer arithmetic (zero float)."""
      if type(minor_units) is not int or isinstance(minor_units, bool):
          raise TypeError("minor_units must be an integer (not bool or float)")
      if type(scale) is not int or isinstance(scale, bool) or not (0 <= scale <= 18):
          raise TypeError("scale must be an integer between 0 and 18")
      sign = "-" if minor_units < 0 else ""
      abs_units = abs(minor_units)
      if scale == 0:
          return f"{sign}{abs_units}"
      multiplier = 10 ** scale
      integer_part, fraction_part = divmod(abs_units, multiplier)
      return f"{sign}{integer_part}.{fraction_part:0{scale}d}"

  def format_beancount_price_directive(
      directive_date: str,
      base_currency: str,
      quote_currency: str,
      rate_numerator: int,
      rate_denominator: int,
      precision_scale: int = 4,
  ) -> str:
      valid_date = validate_calendar_date(directive_date)
      if not isinstance(base_currency, str) or not CURRENCY_PATTERN.match(base_currency):
          raise ValueError(f"Invalid base_currency: {base_currency}")
      if not isinstance(quote_currency, str) or not CURRENCY_PATTERN.match(quote_currency):
          raise ValueError(f"Invalid quote_currency: {quote_currency}")
      if type(rate_numerator) is not int or isinstance(rate_numerator, bool) or rate_numerator <= 0:
          raise TypeError("rate_numerator must be a positive integer")
      if type(rate_denominator) is not int or isinstance(rate_denominator, bool) or rate_denominator <= 0:
          raise TypeError("rate_denominator must be a positive integer")
      if type(precision_scale) is not int or isinstance(precision_scale, bool) or not (0 <= precision_scale <= 18):
          raise TypeError("precision_scale must be an integer between 0 and 18")
      
      # Handle precision_scale == 0 with Banker's rounding
      if precision_scale == 0:
          quot, rem = divmod(rate_numerator, rate_denominator)
          doubled_rem = rem * 2
          if doubled_rem > rate_denominator:
              quot += 1
          elif doubled_rem == rate_denominator:
              if quot % 2 == 1:
                  quot += 1
          return f"{valid_date} price {base_currency} {quot} {quote_currency}"
      
      # Pure integer division and Banker's (half-even) tie-breaking for precision_scale > 0
      integer_part, rem = divmod(rate_numerator, rate_denominator)
      multiplier = 10 ** precision_scale
      quot, subrem = divmod(rem * multiplier, rate_denominator)
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
      return f"{valid_date} price {base_currency} {formatted_rate} {quote_currency}"
  ```

---

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

---

### Task 8.3: Multi-Ledger Topology & Isolated Staging Queues
* **Location:** `src/ironledger/ledger/topology.py`, `src/ironledger/ledger/staging.py`
* **Tenant Isolation, Symlink Refusal & Path Validation:**
  ```python
  LEDGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

  def validate_and_resolve_ledger_root(beancount_root: Path, ledger_id: str) -> Path:
      if not isinstance(ledger_id, str) or not LEDGER_ID_PATTERN.match(ledger_id):
          raise ValueError(f"Invalid ledger_id '{ledger_id}': must match ^[A-Za-z0-9_-]{{1,64}}$")
      
      root_path = Path(beancount_root).absolute()
      target_unresolved = root_path / "ledgers" / ledger_id
      
      # 1. Inspect every path segment along the entire unresolved hierarchy up to filesystem root
      curr = target_unresolved
      while curr != curr.parent:
          if curr.is_symlink():
              raise SecurityError(f"Symlink detected in path hierarchy: {curr}")
          curr = curr.parent
      if curr.is_symlink():
          raise SecurityError(f"Symlink detected at filesystem root: {curr}")
          
      # 2. Resolve target and root, asserting strict path containment
      root_resolved = root_path.resolve()
      target_resolved = target_unresolved.resolve()
      try:
          target_resolved.relative_to(root_resolved)
      except ValueError:
          raise SecurityError(f"Directory traversal detected: {target_resolved} is outside {root_resolved}")
          
      # 3. Final symlink check on resolved target
      if target_resolved.is_symlink():
          raise SecurityError(f"Symlink detected at resolved target: {target_resolved}")
          
      return target_resolved
  ```
* **Compile Mutex Locking:** Scoped lockfile path: `.ironledger/.compile.<ledger_id>.lock`. Lock is acquired **before** reading pre-mutation filesystem state and held until post-mutation directory promotion completes.
* **Consolidation Engine:** Read-only multi-entity balance normalization into a designated reporting currency using Task 8.1 valuation routines.

---

### Task 8.4: Deterministic Audit Replay & Point-in-Time Time Travel
* **Location:** `src/ironledger/replay/engine.py`, `src/ironledger/replay/snapshot.py`, `src/ironledger/manifests.py`
* **Tenant Directory Layout:**
  `beancount_root / "ledgers" / <ledger_id> /`
  - `current/`: Authoritative live directory containing active `.beancount` files.
  - `staging_<seq>_<id>/`: Immutable scratch staging directories.
  - `.promotion_journal.json`: Durable journal state file.
* **Manifest Hash Calculation Contract:**
  ```python
  def compute_directory_manifest_hash(target_dir: Path) -> str:
      """Compute canonical SHA-256 manifest hash over all *.beancount files directly within target_dir."""
      if not target_dir.exists():
          return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      files = sorted([f for f in target_dir.glob("*.beancount") if f.is_file()], key=lambda f: f.name)
      if not files:
          return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      parts = []
      for f in files:
          content_hash = hashlib.sha256(f.read_bytes()).hexdigest()
          parts.append(f"{f.name}\n{content_hash}\n")
      canonical_bytes = "".join(parts).encode("utf-8")
      return hashlib.sha256(canonical_bytes).hexdigest()

  def compute_ledger_manifest_hash(beancount_root: Path, ledger_id: str) -> str:
      tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_id)
      return compute_directory_manifest_hash(tenant_dir / "current")
  ```
* **Genesis State Anchors:**
  - `GENESIS_MANIFEST_HASH`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (SHA-256 of empty bytes `b""`).
  - `GENESIS_PROJECTION_HASH`: `1e3b03f64f2e93ca3cde5c5fd5e63b6194416b8b31871df1153ab643f7342314` (SHA-256 of canonical JSON for the 5 projection tables with 0 rows).
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
              normalized_row = []
              for val in row:
                  if val is None:
                      normalized_row.append(None)
                  elif type(val) is int and not isinstance(val, bool):
                      normalized_row.append(val)
                  elif isinstance(val, bool):
                      raise TypeError("Boolean value encountered in projection table; must be integer 0 or 1")
                  else:
                      normalized_row.append(str(val))
              rows.append(normalized_row)
          payload.append([table, cols, rows])
      encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
      return hashlib.sha256(encoded).hexdigest()
  ```

* **Complete JSON Schema Draft-07 Specifications for All 5 Mutation Payload Types:**
  All payloads enforce `additionalProperties: false` and are validated via `jsonschema.validate()` raising `PayloadValidationError` on violation.

  ```python
  STAGE_TRANSACTION_SCHEMA = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": [
          "ledger_id", "staged_transaction_id", "source_record_id",
          "proposed_date", "payee", "narration", "status",
          "identity_algo_version", "identity_method", "identity_fingerprint",
          "created_at_utc", "source_record", "postings"
      ],
      "additionalProperties": False,
      "properties": {
          "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
          "staged_transaction_id": {"type": "string", "minLength": 1, "maxLength": 64},
          "source_record_id": {"type": "string", "minLength": 1, "maxLength": 64},
          "proposed_date": {"type": "string", "pattern": "^\d{4}-\d{2}-\d{2}$"},
          "payee": {"type": "string"},
          "narration": {"type": "string"},
          "status": {"type": "string", "enum": ["pending", "categorized", "approved", "rejected"]},
          "identity_algo_version": {"type": "integer", "minimum": 1},
          "identity_method": {"type": "string", "enum": ["fitid", "sha256_fallback"]},
          "identity_fingerprint": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
          "created_at_utc": {"type": "string", "pattern": "^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*Z$"},
          "source_record": {
              "type": "object",
              "required": ["source_document_id", "record_index", "canonical_payload", "content_sha256", "mime_type", "encoding", "provenance", "raw_payload_ref"],
              "additionalProperties": False,
              "properties": {
                  "source_document_id": {"type": "string"},
                  "record_index": {"type": "integer", "minimum": 0},
                  "canonical_payload": {"type": "string"},
                  "content_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                  "mime_type": {"type": "string"},
                  "encoding": {"type": "string"},
                  "provenance": {"type": "string"},
                  "raw_payload_ref": {"type": "string"}
              }
          },
          "postings": {
              "type": "array",
              "minItems": 2,
              "items": {
                  "type": "object",
                  "required": ["staged_posting_id", "source_record_id", "role", "posting_index", "account", "minor_units", "currency", "minor_unit_scale", "created_at_utc"],
                  "additionalProperties": False,
                  "properties": {
                      "staged_posting_id": {"type": "string"},
                      "source_record_id": {"type": "string"},
                      "role": {"type": "string", "enum": ["imported", "contra"]},
                      "posting_index": {"type": "integer", "minimum": 0},
                      "account": {"type": ["string", "null"]},
                      "minor_units": {"type": "integer"},
                      "currency": {"type": "string", "pattern": "^[A-Z0-9_.-]{1,12}$"},
                      "minor_unit_scale": {"type": "integer", "minimum": 0, "maximum": 18},
                      "created_at_utc": {"type": "string"}
                  }
              }
          }
      }
  }

  REVIEW_DECISION_SCHEMA = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": ["ledger_id", "staged_transaction_id", "prior_status", "new_status", "assigned_account", "rule_id", "reject_reason", "decided_at_utc"],
      "additionalProperties": False,
      "properties": {
          "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
          "staged_transaction_id": {"type": "string"},
          "prior_status": {"type": "string", "enum": ["pending", "categorized", "approved", "rejected"]},
          "new_status": {"type": "string", "enum": ["pending", "categorized", "approved", "rejected"]},
          "assigned_account": {"type": ["string", "null"]},
          "rule_id": {"type": ["string", "null"]},
          "reject_reason": {"type": ["string", "null"]},
          "decided_at_utc": {"type": "string"}
      }
  }

  COMPILE_LEDGER_SCHEMA = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": [
          "ledger_id", "compile_run_id", "beancount_version", "compiler_version",
          "input_hash", "intended_output_hash", "actual_output_hash", "status",
          "compiled_tx_ids", "compiled_directives"
      ],
      "additionalProperties": False,
      "properties": {
          "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
          "compile_run_id": {"type": "string"},
          "beancount_version": {"type": "string"},
          "compiler_version": {"type": "string"},
          "input_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
          "intended_output_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
          "actual_output_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
          "status": {"type": "string", "enum": ["SUCCESS", "FAILED"]},
          "compiled_tx_ids": {"type": "array", "items": {"type": "string"}},
          "compiled_directives": {
              "type": "array",
              "items": {
                  "type": "object",
                  "required": ["proposed_date", "payee", "narration", "postings"],
                  "additionalProperties": False,
                  "properties": {
                      "proposed_date": {"type": "string", "pattern": "^\d{4}-\d{2}-\d{2}$"},
                      "payee": {"type": "string"},
                      "narration": {"type": "string"},
                      "postings": {
                          "type": "array",
                          "items": {
                              "type": "object",
                              "required": ["account", "minor_units", "currency", "minor_unit_scale"],
                              "additionalProperties": False,
                              "properties": {
                                  "account": {"type": "string"},
                                  "minor_units": {"type": "integer"},
                                  "currency": {"type": "string"},
                                  "minor_unit_scale": {"type": "integer", "minimum": 0, "maximum": 18}
                              }
                          }
                      }
                  }
              }
          }
      }
  }

  PRICE_DIRECTIVE_SCHEMA = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": ["ledger_id", "id", "directive_date", "base_currency", "quote_currency", "rate_numerator", "rate_denominator", "precision_scale", "source"],
      "additionalProperties": False,
      "properties": {
          "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
          "id": {"type": "integer"},
          "directive_date": {"type": "string", "pattern": "^\d{4}-\d{2}-\d{2}$"},
          "base_currency": {"type": "string", "pattern": "^[A-Z0-9_.-]{1,12}$"},
          "quote_currency": {"type": "string", "pattern": "^[A-Z0-9_.-]{1,12}$"},
          "rate_numerator": {"type": "integer", "minimum": 1},
          "rate_denominator": {"type": "integer", "minimum": 1},
          "precision_scale": {"type": "integer", "minimum": 0, "maximum": 18},
          "source": {"type": "string", "enum": ["MANUAL", "POLLED_FEED", "EXCHANGE_API"]}
      }
  }

  RULE_UPDATE_SCHEMA = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": ["ledger_id", "rule_id", "action", "match_type", "pattern", "importing_account", "target_account", "priority", "active"],
      "additionalProperties": False,
      "properties": {
          "ledger_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
          "rule_id": {"type": "string"},
          "action": {"type": "string", "enum": ["CREATE", "UPDATE", "DELETE"]},
          "match_type": {"type": "string", "enum": ["exact", "prefix", "regex"]},
          "pattern": {"type": "string"},
          "importing_account": {"type": ["string", "null"]},
          "target_account": {"type": "string"},
          "priority": {"type": "integer"},
          "active": {"type": "integer", "enum": [0, 1]}
      }
  }
  ```

* **Crash-Atomic Outbox Protocol with Lock and Promotion Journal:**
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
      validate_payload_schema(event_type, payload, payload_schema_version)
      tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_id)
      tenant_dir.mkdir(parents=True, exist_ok=True)
      current_dir = tenant_dir / "current"
      current_dir.mkdir(parents=True, exist_ok=True)
      
      # Acquire tenant compile lock before staging
      lock_path = beancount_root / ".ironledger" / f".compile.{ledger_id}.lock"
      lock_path.parent.mkdir(parents=True, exist_ok=True)
      
      with open(lock_path, "w") as lock_file:
          portalocker_lock(lock_file)
          try:
              staging_dir: Path | None = None
              journal_file = tenant_dir / ".promotion_journal.json"
              sha256_before = compute_directory_manifest_hash(current_dir)
              
              if event_type in ("COMPILE_LEDGER", "PRICE_DIRECTIVE"):
                  staging_dir = tenant_dir / f"staging_{uuid4().hex}"
                  staging_dir.mkdir(parents=True, exist_ok=True)
                  for f in current_dir.glob("*.beancount"):
                      shutil.copy2(f, staging_dir / f.name)
                  if event_type == "COMPILE_LEDGER":
                      if payload.get("status") == "SUCCESS":
                          render_compiled_ledger_manifest(staging_dir, ledger_id, payload)
                  elif event_type == "PRICE_DIRECTIVE":
                      render_price_directive_manifest(staging_dir, ledger_id, payload)
                  for f in staging_dir.rglob("*.beancount"):
                      with open(f, "a+b") as fp:
                          fp.flush()
                          os.fsync(fp.fileno())
                  sha256_after = compute_directory_manifest_hash(staging_dir)
              else:
                  sha256_after = sha256_before
              
              conn.execute("BEGIN IMMEDIATE")
              try:
                  projection_hash_before = compute_projection_hash(conn, ledger_id)
                  dispatch_event_mutation(conn, ledger_id, event_type, payload)
                  projection_hash_after = compute_projection_hash(conn, ledger_id)
                  
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
                  now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                  ts_utc = max(now_ts, last_ts)
                  if ts_utc == last_ts:
                      dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00")) + timedelta(microseconds=1)
                      ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                  
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
                  
                  # Generate cryptographic authority signature using canonical digest formula
                  sign_digest = compute_anchor_signature_digest(
                      seq, mutation_id, ledger_id, ts_utc, mutation_hash,
                      prev_mutation_hash, sha256_after, projection_hash_after
                  )
                  authority_signature = sign_authority_payload(sign_digest, authority_key)

                  # Prepare anchor data
                  anchor_dir = beancount_root / ".ironledger" / "anchors"
                  anchor_dir.mkdir(parents=True, exist_ok=True)
                  anchor_file = anchor_dir / f"{ledger_id}.anchor.json"
                  anchor_data = {
                      "anchor_version": 1,
                      "ledger_id": ledger_id,
                      "seq": seq,
                      "mutation_id": mutation_id,
                      "mutation_hash": mutation_hash,
                      "prev_mutation_hash": prev_mutation_hash,
                      "manifest_hash": sha256_after,
                      "projection_hash": projection_hash_after,
                      "authority_signature": authority_signature,
                      "anchored_at_utc": ts_utc
                  }

                  backup_dir = tenant_dir / f"current_bak_{uuid4().hex}" if (staging_dir and staging_dir.exists()) else None

                  # Step 1: Write PRE_COMMIT promotion journal BEFORE committing database transaction
                  journal_data = {
                      "state": "PRE_COMMIT",
                      "seq": seq,
                      "ledger_id": ledger_id,
                      "sha256_before": sha256_before,
                      "sha256_after": sha256_after,
                      "staging_dir": staging_dir.name if (staging_dir and staging_dir.exists()) else None,
                      "backup_dir": backup_dir.name if backup_dir else None,
                      "anchor_data": anchor_data
                  }
                  temp_j = tenant_dir / f".j_{uuid4().hex}.tmp"
                  temp_j.write_text(json.dumps(journal_data), encoding="utf-8")
                  os.replace(temp_j, journal_file)

                  # Step 2: Insert into database tables and COMMIT
                  conn.execute(
                      "INSERT INTO mutation_events (seq, mutation_id, ledger_id, ts_utc, operator_session, action, "
                      "staged_count, rules_applied, rules_created, sha256_before, sha256_after, prev_mutation_hash, mutation_hash, authority_signature) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (seq, mutation_id, ledger_id, ts_utc, operator_session, action, 0, rules_applied, rules_created,
                       sha256_before, sha256_after, prev_mutation_hash, mutation_hash, authority_signature)
                  )
                  conn.execute(
                      "INSERT INTO mutation_payloads (seq, mutation_id, ledger_id, payload_schema_version, event_type, "
                      "payload_json, payload_sha256, projection_hash_before, projection_hash_after, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (seq, mutation_id, ledger_id, payload_schema_version, event_type,
                       canonical_payload_bytes.decode("utf-8"), payload_sha256,
                       projection_hash_before, projection_hash_after, ts_utc)
                  )
                  conn.execute("COMMIT")
              except Exception:
                  conn.execute("ROLLBACK")
                  if journal_file.exists():
                      journal_file.unlink()
                  if staging_dir and staging_dir.exists():
                      shutil.rmtree(staging_dir, ignore_errors=True)
                  raise
              
              # Step 3: Advance journal state to COMMITTED_PRE_SWAP immediately post-commit
              try:
                  journal_data["state"] = "COMMITTED_PRE_SWAP"
                  temp_j = tenant_dir / f".j_{uuid4().hex}.tmp"
                  temp_j.write_text(json.dumps(journal_data), encoding="utf-8")
                  os.replace(temp_j, journal_file)

                  # Step 4: Perform directory swap (for filesystem mutations)
                  if staging_dir and staging_dir.exists():
                      if backup_dir.exists():
                          shutil.rmtree(backup_dir, ignore_errors=True)
                      if current_dir.exists():
                          os.replace(current_dir, backup_dir)
                      os.replace(staging_dir, current_dir)

                  # Step 5: Update external trust anchor atomically
                  temp_a = anchor_dir / f".a_{uuid4().hex}.tmp"
                  temp_a.write_text(json.dumps(anchor_data, indent=2), encoding="utf-8")
                  os.replace(temp_a, anchor_file)

                  # Step 6: Advance journal state to SWAPPED only after verified filesystem swap and anchor update
                  journal_data["state"] = "SWAPPED"
                  temp_j = tenant_dir / f".j_{uuid4().hex}.tmp"
                  temp_j.write_text(json.dumps(journal_data), encoding="utf-8")
                  os.replace(temp_j, journal_file)
                  
                  # Step 7: Clean up backup directory and journal
                  if backup_dir and backup_dir.exists():
                      shutil.rmtree(backup_dir, ignore_errors=True)
                  if journal_file.exists():
                      journal_file.unlink()
              except Exception as promo_err:
                  raise ManifestPromotionError(f"Promotion failed for mutation {mutation_id}: {promo_err}") from promo_err
          finally:
              portalocker_unlock(lock_file)
      
      return (
          MutationEvent(seq=seq, mutation_id=mutation_id, ledger_id=ledger_id, ...),
          MutationPayload(seq=seq, mutation_id=mutation_id, ledger_id=ledger_id, ...)
      )
  ```

* **Startup Manifest Reconciliation Protocol (`reconcile_manifest_on_startup`):**
  - Invoked during database connection startup under tenant compile mutex lock:
  1. For each active ledger in `ledgers`:
     - Let `tenant_dir = validate_and_resolve_ledger_root(beancount_root, ledger_id)`.
     - Let `current_dir = tenant_dir / "current"`.
     - Let `journal_file = tenant_dir / ".promotion_journal.json"`.
     - Let `anchor_dir = beancount_root / ".ironledger" / "anchors"`.
     - Let `anchor_file = anchor_dir / f"{ledger_id}.anchor.json"`.
     - If `journal_file.exists()`:
       - Read journal metadata: `state = journal.get("state")`, `anchor_data = journal.get("anchor_data")`.
       - **Strict Journal Path Containment Guard:**
         ```python
         SUBDIR_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
         def resolve_journal_subpath(parent_dir: Path, subpath_str: str | None) -> Path | None:
             if not subpath_str:
                 return None
             if not SUBDIR_NAME_PATTERN.match(subpath_str) or ".." in subpath_str or "/" in subpath_str or "\\" in subpath_str:
                 raise SecurityError(f"Path traversal or invalid directory name in promotion journal: {subpath_str}")
             resolved = (parent_dir / subpath_str).resolve()
             if not resolved.is_relative_to(parent_dir.resolve()):
                 raise SecurityError(f"Directory escape detected in journal path: {resolved}")
             if resolved.is_symlink():
                 raise SecurityError(f"Symlink detected in journal path: {resolved}")
             return resolved
         ```
       - `staged_cand = resolve_journal_subpath(tenant_dir, journal.get("staging_dir"))`
       - `bak_cand = resolve_journal_subpath(tenant_dir, journal.get("backup_dir"))`
       - Check if sequence was committed in DB: `db_has_seq = bool(conn.execute("SELECT 1 FROM mutation_events WHERE seq = ?", (journal["seq"],)).fetchone())`.
       - If `state == "PRE_COMMIT"`:
         - If not `db_has_seq`:
           - Crash occurred before SQLite commit. Discard scratch staging folder `if staged_cand and staged_cand.exists(): shutil.rmtree(staged_cand, ignore_errors=True)`. Unlink journal.
         - Else:
           - Crash occurred immediately after SQLite commit before state transition. Treat as `COMMITTED_PRE_SWAP`.
       - If `state == "COMMITTED_PRE_SWAP"` or (`state == "PRE_COMMIT"` and `db_has_seq`):
         - If `staged_cand` and `staged_cand.exists()` and `compute_directory_manifest_hash(staged_cand) == journal["sha256_after"]`:
           - If `bak_cand and bak_cand.exists()`: `shutil.rmtree(bak_cand, ignore_errors=True)` (purge any colliding stale backup from prior crash).
           - If `current_dir.exists()` and `bak_cand`: `os.replace(current_dir, bak_cand)`.
           - `os.replace(staged_cand, current_dir)`.
           - If `bak_cand and bak_cand.exists()`: `shutil.rmtree(bak_cand, ignore_errors=True)`.
         - Else if not `current_dir.exists()` or `compute_directory_manifest_hash(current_dir) != journal["sha256_after"]`:
           - If journal had no staging_dir (non-filesystem mutation): manifest check passes if live manifest matches expected `sha256_after`.
           - Otherwise, retain journal and raise `ReconciliationFailedError("Promotion recovery failed: staging directory corrupted or missing")`.
         - Ensure anchor file is written from `anchor_data`:
           - `temp_a = anchor_dir / f".a_{uuid4().hex}.tmp"`
           - `temp_a.write_text(json.dumps(anchor_data, indent=2), encoding="utf-8")`
           - `os.replace(temp_a, anchor_file)`
       - If `state == "SWAPPED"`:
         - Swap already succeeded before crash. If `bak_cand and bak_cand.exists()`: `shutil.rmtree(bak_cand, ignore_errors=True)`.
         - If `anchor_data` and not `anchor_file.exists()`:
           - `temp_a = anchor_dir / f".a_{uuid4().hex}.tmp"`
           - `temp_a.write_text(json.dumps(anchor_data, indent=2), encoding="utf-8")`
           - `os.replace(temp_a, anchor_file)`
       - **Strict Fail-Closed Journal Deletion Guard:**
         - Assert `current_dir.exists()` and `compute_directory_manifest_hash(current_dir) == journal["sha256_after"]`.
         - Assert `anchor_file.exists()`.
         - Only after verified manifest hash and anchor equality: `journal_file.unlink()`.
         - If verification fails: retain journal and raise `ReconciliationFailedError("Refusing to delete promotion journal: post-recovery state verification failed")`.
     - Query all `mutation_events` rows for `ledger_id` ordered by `seq ASC`.
     - If no events exist:
       - If `current_dir.exists()`: assert `compute_directory_manifest_hash(current_dir) == GENESIS_MANIFEST_HASH`.
     - If events exist:
       - Let $M_{	ext{latest}}$ be the last event in sequence for this ledger.
       - Let $H_{	ext{live}} = 	ext{compute\_directory\_manifest\_hash}(current\_dir)$.
       - If $H_{	ext{live}} == M_{	ext{latest}}.	ext{sha256\_after}$:
         - Filesystem is clean. Remove leftover `staging_*` or `current_bak_*` folders.
       - If $H_{	ext{live}} != M_{	ext{latest}}.	ext{sha256\_after}$:
         - Sequentially re-emit plaintext manifests from the payloads of all tenant events $M_1 \dots M_{	ext{latest}}$ into a fresh `staging_recovery/` directory, verifying each step.
         - Atomically swap `staging_recovery/` to `current/`.
         - Assert `compute_directory_manifest_hash(current_dir) == M_{	ext{latest}}.	ext{sha256\_after}`.
         - Prune temporary directories.

* **Authority Cryptographic Signature & External Trust Anchor Protocol:**
  - **Canonical Signature Digest Specification:**
    ```python
    def compute_anchor_signature_digest(
        seq: int,
        mutation_id: str,
        ledger_id: str,
        ts_utc: str,
        mutation_hash: str,
        prev_mutation_hash: str,
        manifest_hash: str,
        projection_hash: str,
    ) -> str:
        """Compute the canonical SHA-256 digest string for signing and verifying audit authority signatures."""
        raw = f"{seq}:{mutation_id}:{ledger_id}:{ts_utc}:{mutation_hash}:{prev_mutation_hash}:{manifest_hash}:{projection_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    ```
  - **Signing Authority Envelope:**
    - Each mutation event is cryptographically signed using an Authority Signing Key (`HMAC-SHA256` secret or `Ed25519` private key) configured via environment/keystore (`IRONLEDGER_SIGNING_KEY`).
    - `sign_digest = compute_anchor_signature_digest(seq, mutation_id, ledger_id, ts_utc, mutation_hash, prev_mutation_hash, sha256_after, projection_hash_after)`
    - `authority_signature = sign_authority_payload(sign_digest, authority_key)` (hex-encoded string). Stored in `mutation_events.authority_signature`.
  - **External Out-of-Band Trust Anchor File (`.ironledger/anchors/<ledger_id>.anchor.json`):**
    - Stored outside the SQLite database at `beancount_root / ".ironledger" / "anchors" / f"{ledger_id}.anchor.json"`.
    - Updated atomically on every committed mutation:
      ```json
      {
        "anchor_version": 1,
        "ledger_id": "corp_main",
        "seq": 42,
        "mutation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "mutation_hash": "a1b2c3...",
        "prev_mutation_hash": "f0e1d2...",
        "manifest_hash": "e3b0c4...",
        "projection_hash": "1e3b03...",
        "authority_signature": "d4e5f6...",
        "anchored_at_utc": "2026-09-10T12:00:00.000000Z"
      }
      ```
    - Protects the ledger against offline SQLite database tampering/rewrite: if an attacker modifies past events and recalculates internal SHA-256 hashes, they cannot forge the authority signature without the private key, and the forged head will diverge from the external trust anchor file.

* **Deterministic Replay Engine Algorithm & Interleaved Multi-Tenant Semantics:**
  1. Resolve `target_sequence`: If `target_timestamp` is provided, select `MAX(seq)` where `ts_utc <= target_timestamp` ordered strictly by `seq ASC`.
  2. Query live database max sequence $S_{	ext{max}} = 	ext{SELECT MAX(seq) FROM mutation\_events}$. If `target_sequence >` $S_{	ext{max}}$, raise `ReplayBoundaryError`.
  3. **Phase 1: Global Contiguous Sequence, Merkle Chain & Cryptographic Signature Verification (Global $1 \dots \text{target\_seq}$):**
     - **Mandatory External Trust Anchor Corroboration (Fail-Closed):**
       - Query tenant's latest committed event $M_{\text{latest}}$ from database.
       - If no events exist ($S_{\text{max}} = 0$): assert no live state mutations exist.
       - If events exist ($S_{\text{max}} \ge 1$):
         - Read external anchor file `.ironledger/anchors/<ledger_id>.anchor.json`. If missing, unreadable, or invalid JSON, fail closed with `MissingAnchorCommitmentError`.
         - Parse anchor commitment and assert:
           - `anchor.seq == M_{\text{latest}}.seq`
           - `anchor.mutation_id == M_{\text{latest}}.mutation_id`
           - `anchor.mutation_hash == M_{\text{latest}}.mutation_hash`
           - `anchor.manifest_hash == M_{\text{latest}}.sha256_after`
           - `anchor.projection_hash == payload_{\text{latest}}.projection_hash_after`
           - `anchor.authority_signature == M_{\text{latest}}.authority_signature`
           - Let `expected_anchor_digest = compute_anchor_signature_digest(anchor.seq, anchor.mutation_id, anchor.ledger_id, anchor.anchored_at_utc, anchor.mutation_hash, anchor.prev_mutation_hash, anchor.manifest_hash, anchor.projection_hash)`.
           - `verify_authority_signature(anchor.authority_signature, expected_anchor_digest, public_key) == True`
         - If any assertion fails, immediately abort with `AuditTamperDetectedError("External trust anchor diverges from database state: potential offline tampering detected")`.**
     - Query joined rows from `mutation_events` and `mutation_payloads` ordered by `seq ASC`.
     - Assert global contiguous `seq` sequence $1, 2, \dots, N$ across all tenants with zero gaps.
     - Assert timestamps `ts_utc` are strictly non-decreasing monotonic.
     - For each row:
       - Validate `payload_sha256 == sha256(payload_json)`.
       - Reconstruct exact `canonical_dict` from event + payload fields.
       - Recompute canonical `mutation_hash = sha256(json(canonical_dict))` and assert equality with `event.mutation_hash`.
       - Assert `event.prev_mutation_hash` matches prior event's `mutation_hash` (or $0^{64}$ for `seq = 1`).
  4. **Phase 2: Tenant-Scoped Dual-Fingerprint Replay (Projection + Filesystem):**
     - Spin up an in-memory SQLite projection database (`:memory:`), load schema `0001` through `0011`.
     - Create an ephemeral temporary directory for Beancount plaintext manifest playback.
     - Assert initial in-memory `compute_projection_hash(mem_conn, target_ledger_id) == GENESIS_PROJECTION_HASH`.
     - Assert initial ephemeral manifest `compute_directory_manifest_hash(temp_manifest_dir) == GENESIS_MANIFEST_HASH`.
     - Stream the validated events from `seq = 1` to `target_seq`:
       - If `event.ledger_id == target_ledger_id`:
         - Validate in-memory `compute_projection_hash(mem_conn, target_ledger_id) == payload.projection_hash_before`.
         - Execute `dispatch_event_mutation(mem_conn, target_ledger_id, payload.event_type, json.loads(payload.payload_json))`.
         - Validate resulting in-memory `compute_projection_hash(mem_conn, target_ledger_id) == payload.projection_hash_after`.
         - If event has filesystem emissions (`COMPILE_LEDGER` or `PRICE_DIRECTIVE`):
           - Render Beancount plaintext directives into ephemeral directory using `render_compiled_ledger_manifest` / `render_price_directive_manifest`.
           - Validate resulting ephemeral manifest hash equals `event.sha256_after`.
       - If `event.ledger_id != target_ledger_id`:
         - Interleaved event belongs to another tenant. Skip projection and filesystem mutations (tenant isolation invariant guarantees non-target events produce zero state changes for `target_ledger_id`).
  5. Return verified in-memory projection database and point-in-time trial balance.

---

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
* **Bearer Token Lifecycle & Verification Protocol:**
  - Token Generation:
    ```python
    raw_token = f"il_cap_{secrets.token_hex(32)}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    ```
  - Authorization Verification (`PolicyEnforcer.authorize(raw_token, required_scope, target_ledger_id)`):
    1. Parse token: Check that `raw_token.startswith("il_cap_")` and `len(raw_token) == 71`. If invalid, raise `UnauthorizedError("Malformed bearer token")`.
    2. Compute SHA-256 hash: `computed_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()`.
    3. Look up token in `capability_tokens` table by `token_hash = computed_hash`. If row not found, raise `UnauthorizedError("Invalid capability token")`.
    4. Constant-time comparison: `hmac.compare_digest(row["token_hash"], computed_hash)`.
    5. Check revocation: If `row["revoked_at"]` is not NULL, raise `UnauthorizedError("Capability token has been revoked")`.
    6. Check expiration: If `row["expires_at"]` is not NULL and `row["expires_at"] <= current_utc_iso`, raise `UnauthorizedError("Capability token has expired")`.
    7. Check tenant scope:
       - If `row["is_global"] == 1`: assert `row["role"] == "ADMIN"` and `row["ledger_id"] IS NULL`. Grants access across all ledgers.
       - If `row["is_global"] == 0`: assert `row["ledger_id"] == target_ledger_id`. If they differ, raise `UnauthorizedError(f"Token scoped to ledger '{row['ledger_id']}' cannot access '{target_ledger_id}'")`.
    8. Check role ceilings & capabilities:
       - Parse `granted_scopes = json.loads(row["capabilities_json"])`.
       - Assert `set(granted_scopes).issubset(ROLE_CEILINGS[row["role"]])`.
       - Verify `required_scope in granted_scopes` or `"*"` in granted_scopes. If not, raise `UnauthorizedError(f"Token lacks required scope: {required_scope}")`.
* **Centralized Policy Enforcement:** Invoked across CLI commands, MCP tools, and web endpoints. Unauthenticated requests or requests with invalid tokens fail closed with HTTP 401 Unauthorized / `UnauthorizedError`.

---

### Task 8.6: Acceptance Regression Suite & Phase 8 Exit Evidence
* **Location:** `tests/test_valuation.py`, `tests/test_lineage.py`, `tests/test_multi_ledger.py`, `tests/test_replay.py`, `tests/test_capabilities.py`, `tests/test_phase8_exit_contract.py`
* **Static Analysis Import & Zero-Float AST Guard:**
  - AST scanner in `tests/test_phase8_exit_contract.py` implements a symbol-tracking AST visitor checking all Python source files in `src/ironledger/**/*.py`:
    - Tracks alias bindings across `import x as y`, `from x import y as z`.
    - Flags direct and aliased imports of `beancount` or submodules `beancount.*`.
    - Flags direct and aliased invocations of `importlib.import_module`, `__import__`, or `builtins.__import__` targeting `beancount`.
    - Flags dynamic `getattr(mod, "import_module")("beancount")`.
    - Flags float division operator `ast.Div` (`/`) in `valuation/` and manifest rendering modules (`formatting.py`, `engine.py`, `manifests.py`, `replay/engine.py`).
    - AST scanner test includes positive and negative test fixtures verifying scanner detection fidelity.
* **Exit Evidence Artifact:** `docs/meta/phases/ironledger-phase-8-evidence.md`.

---

## 5. Verification & Test Plan

1. **Valuation Suite (`tests/test_valuation.py`):**
   - Verify integer rational price conversion with 0 floating-point drift across mixed decimal precisions (USD 2-dec, BTC 8-dec, AAPL 4-dec).
   - Verify exact Banker's half-even rounding for positive, negative, tie, and carry cases across all scales including `precision_scale == 0`.
   - Verify strict integer type assertion rejection on bool, float, and non-integer inputs.
   - Verify bounded preceding price resolution, stale price rejection, identity same-currency conversion, and inverse quote resolution.
   - Verify Beancount price directive string template output with zero runtime Beancount imports and pure integer Banker's rounding.
2. **Lineage Suite (`tests/test_lineage.py`):**
   - Verify bi-directional recursive CTE DAG traversals within tenant boundaries (posting $\to$ evidence hash, and evidence hash $\to$ postings).
   - Verify self-edge rejection and unbounded cycle prevention rejection and transactional atomicity on edge registration.
3. **Multi-Ledger Suite (`tests/test_multi_ledger.py`):**
   - Verify migration execution `0001` through `0011` with forward-only integrity, `schema_migrations` checksum verification, and table rebuild safety.
   - Verify complete isolation of staging queues, lineage nodes, review rules, and concurrent compilation locks across multiple `ledger_id`s.
   - Verify composite primary and foreign key constraints reject cross-tenant record linking at the SQLite database layer with `PRAGMA foreign_keys = ON;`.
   - Verify multi-entity consolidated balance aggregation.
4. **Replay Suite (`tests/test_replay.py`):**
   - Verify genesis state anchor verification (`GENESIS_MANIFEST_HASH` and `GENESIS_PROJECTION_HASH`), global sequence contiguity, Merkle chain verification, and dual-fingerprint payload replay into ephemeral in-memory database and manifest directory validating `projection_hash_before`/`after` and `sha256_before`/`after`.
   - Verify outbox crash-recovery startup reconciliation from partial promotions and missing directories.
   - Verify multi-tenant interleaved events replay with strict tenant isolation.
   - Verify zero side-effects on live database files.
5. **RBAC Suite (`tests/test_capabilities.py`):**
   - Verify token creation with issuance-time ceiling checks, constant-time hash verification, role ceiling enforcement, expiration/revocation gating, and global vs tenant-scoped validation across CLI, MCP, and HTTP endpoints.
6. **Phase 8 Exit Contract (`tests/test_phase8_exit_contract.py`):**
   - Run end-to-end integration scenario combining multi-asset pricing, lineage tracing, multi-tenant isolation, replay, and RBAC enforcement.
   - Run full symbol-tracking AST scanner and zero-float AST visitor across `src/ironledger/**/*.py`.
