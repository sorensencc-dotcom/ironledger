-- src/ironledger/project/schema.sql
-- IronLedger Phase 4: disposable analytics projection. Version 1.

CREATE TABLE projection_meta (
    singleton            INTEGER PRIMARY KEY CHECK (singleton = 1),
    compile_run_id       TEXT NOT NULL,
    ledger_input_hash    TEXT NOT NULL,
    ledger_output_hash   TEXT NOT NULL,
    schema_version       INTEGER NOT NULL CHECK (schema_version = 1),
    built_at_utc         TEXT NOT NULL CHECK (built_at_utc GLOB '????-??-??T??:??:??*Z'),
    beancount_version    TEXT NOT NULL,
    compiler_version     TEXT NOT NULL
) STRICT;

CREATE TABLE proj_accounts (
    account   TEXT PRIMARY KEY,
    currency  TEXT NOT NULL,
    open_date TEXT NOT NULL
) STRICT;

CREATE TABLE proj_entries (
    entry_id               TEXT PRIMARY KEY,
    entry_date             TEXT NOT NULL,
    payee                  TEXT NOT NULL,
    narration              TEXT NOT NULL,
    staged_transaction_id  TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE proj_postings (
    posting_id             TEXT PRIMARY KEY,
    entry_id               TEXT NOT NULL REFERENCES proj_entries (entry_id) ON DELETE CASCADE,
    account                TEXT NOT NULL,
    minor_units            INTEGER NOT NULL,
    currency               TEXT NOT NULL,
    minor_unit_scale       INTEGER NOT NULL,
    source_document_id     TEXT NOT NULL,
    source_record_id       TEXT NOT NULL,
    identity_algo_version  INTEGER NOT NULL,
    identity_method        TEXT NOT NULL
) STRICT;

CREATE TABLE proj_balances (
    account           TEXT NOT NULL,
    currency          TEXT NOT NULL,
    minor_units       INTEGER NOT NULL,
    minor_unit_scale  INTEGER NOT NULL,
    PRIMARY KEY (account, currency)
) STRICT;

CREATE VIRTUAL TABLE proj_fts USING fts5(
    payee,
    narration,
    account,
    posting_text,
    posting_id UNINDEXED,
    tokenize = 'unicode61'
);
