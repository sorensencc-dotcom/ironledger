-- src/ironledger/db/schema/0004_review_workflow.sql
-- IronLedger Phase 2b: widen staged_transactions.status and add the review workflow.
--
-- The migration runner wraps this file in a single BEGIN/COMMIT and PRAGMA
-- foreign_keys is ignored inside a transaction, so the classic
-- "foreign_keys = OFF" table rebuild is unavailable. Two tables reference
-- staged_transactions.staged_transaction_id: staged_postings (ON DELETE CASCADE)
-- and ledger_entries (ON DELETE RESTRICT). The rebuild parks and restores
-- staged_postings so DROP TABLE cascades into nothing.
--
-- ledger_entries is created by migration 0001 but is only ever populated by the
-- Phase 3 compiler, which does not exist yet. 0004 is recorded before any
-- Phase 3 work runs, so at apply time ledger_entries has zero rows and the
-- implicit DELETE inside DROP TABLE never triggers its ON DELETE RESTRICT.
-- If a future migration reorders this, revisit the DROP below.

CREATE TABLE staged_postings_rebuild_backup AS SELECT * FROM staged_postings;

DELETE FROM staged_postings;

CREATE TABLE staged_transactions_new (
    staged_transaction_id TEXT PRIMARY KEY,
    source_record_id      TEXT NOT NULL
        REFERENCES source_records (source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    status                TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'categorized', 'approved', 'rejected')),
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
    UNIQUE (identity_algo_version, identity_fingerprint)
) STRICT;

INSERT INTO staged_transactions_new (
    staged_transaction_id, source_record_id, status, proposed_date, payee, narration,
    identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc,
    reject_reason, categorized_at_utc
)
SELECT
    staged_transaction_id, source_record_id, status, proposed_date, payee, narration,
    identity_algo_version, identity_method, identity_fingerprint, created_at_utc, decided_at_utc,
    NULL, NULL
FROM staged_transactions;

DROP TABLE staged_transactions;

ALTER TABLE staged_transactions_new RENAME TO staged_transactions;

CREATE INDEX idx_staged_source_record ON staged_transactions (source_record_id);

INSERT INTO staged_postings SELECT * FROM staged_postings_rebuild_backup;

DROP TABLE staged_postings_rebuild_backup;

CREATE TABLE categorization_rules (
    rule_id           TEXT PRIMARY KEY,
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
    UNIQUE (match_type, pattern, importing_account)
) STRICT;

CREATE INDEX idx_categorization_rules_active_priority ON categorization_rules (active, priority);
