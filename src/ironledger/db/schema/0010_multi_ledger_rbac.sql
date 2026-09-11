-- Migration 0010: Multi-Ledger Topology, Isolated Staging Queues & RBAC

-- Alter existing ledgers table created in 0008 to add root_account and storage_root
ALTER TABLE ledgers ADD COLUMN root_account TEXT NOT NULL DEFAULT 'Assets';
ALTER TABLE ledgers ADD COLUMN storage_root TEXT NOT NULL DEFAULT '';

UPDATE ledgers SET storage_root = 'default' WHERE ledger_id = 'default' AND storage_root = '';

-- Alter legacy tables to add tenant isolation ledger_id
ALTER TABLE source_documents ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT;
ALTER TABLE source_records ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT;
ALTER TABLE staged_transactions ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT;
ALTER TABLE staged_postings ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT;
ALTER TABLE categorization_rules ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE;
ALTER TABLE compile_runs ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE CASCADE;
ALTER TABLE mutation_events ADD COLUMN ledger_id TEXT NOT NULL DEFAULT 'default' REFERENCES ledgers(ledger_id) ON DELETE RESTRICT;

CREATE TABLE IF NOT EXISTS ledger_accounts (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    id INTEGER NOT NULL,
    parent_id INTEGER,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    PRIMARY KEY (ledger_id, id),
    FOREIGN KEY (ledger_id, parent_id) REFERENCES ledger_accounts (ledger_id, id) ON DELETE CASCADE ON UPDATE CASCADE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_ledger_accounts_parent ON ledger_accounts (ledger_id, parent_id);

CREATE TABLE IF NOT EXISTS tenant_staging_operations (
    op_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    operation_json TEXT NOT NULL CHECK(json_valid(operation_json) = 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processed', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_tenant_staging_lookup ON tenant_staging_operations(ledger_id, status, op_id);

CREATE TABLE IF NOT EXISTS ledger_balances (
    ledger_id TEXT NOT NULL REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    account TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL CHECK(length(currency) >= 1 AND length(currency) <= 12 AND currency NOT GLOB '*[^A-Z0-9_.-]*'),
    scale INTEGER NOT NULL DEFAULT 2 CHECK(scale >= 0 AND scale <= 18),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY (ledger_id, account, currency)
) STRICT;

CREATE TABLE IF NOT EXISTS capability_tokens (
    token_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    ledger_id TEXT REFERENCES ledgers(ledger_id) ON DELETE CASCADE,
    is_global INTEGER NOT NULL DEFAULT 0 CHECK(is_global IN (0, 1)),
    role TEXT NOT NULL CHECK(role IN ('READER', 'OPERATOR', 'COMPILER', 'ADMIN')),
    capabilities_json TEXT NOT NULL CHECK(json_valid(capabilities_json) = 1 AND json_type(capabilities_json) = 'array'),
    expires_at TEXT CHECK(expires_at IS NULL OR (expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND expires_at NOT GLOB '*[^0-9T:.-Z]*')),
    revoked_at TEXT CHECK(revoked_at IS NULL OR (revoked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND revoked_at NOT GLOB '*[^0-9T:.-Z]*')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CHECK((is_global = 1 AND role = 'ADMIN' AND ledger_id IS NULL) OR (is_global = 0 AND role IN ('READER', 'OPERATOR', 'COMPILER', 'ADMIN') AND ledger_id IS NOT NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_token_hash_lookup ON capability_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_source_records_doc ON source_records (ledger_id, source_document_id);
CREATE INDEX IF NOT EXISTS idx_staged_source_record ON staged_transactions (ledger_id, source_record_id);
CREATE INDEX IF NOT EXISTS idx_staged_tx_ledger ON staged_transactions (ledger_id, status);
CREATE INDEX IF NOT EXISTS idx_staged_postings_transaction ON staged_postings (ledger_id, staged_transaction_id);
CREATE INDEX IF NOT EXISTS idx_staged_postings_source ON staged_postings (ledger_id, source_record_id);
CREATE INDEX IF NOT EXISTS idx_categorization_rules_active_priority ON categorization_rules (ledger_id, active, priority);
CREATE INDEX IF NOT EXISTS idx_mutation_events_ledger ON mutation_events (ledger_id, seq);
CREATE INDEX IF NOT EXISTS idx_compile_runs_lookup ON compile_runs (ledger_id, compile_run_id);
