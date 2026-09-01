-- IronLedger Phase 1 core schema.
--
-- Primary evidence, staging, ledger-index, audit, and compile-run tables.
-- All tables are STRICT. Beancount plus retained source evidence is the
-- accounting authority; these tables are an index and a workflow record, never
-- a second mutable ledger.
--
-- Deletion rules:
--   * Nothing cascades into source_documents or source_records. References to
--     evidence use ON DELETE RESTRICT so a delete of referenced evidence fails.
--   * ledger_postings belong to their ledger_entry (an index row, not evidence)
--     and cascade with it. Their link back to source_records is RESTRICT.
--
-- Timestamp columns hold ISO-8601 UTC strings with an explicit trailing Z. The
-- GLOB CHECKs here reject the obvious wrong shapes; the full rejection test
-- suite is Phase 1 task 3.

-- ---------------------------------------------------------------------------
-- Evidence (append-only through normal workflows; never cascaded into)
-- ---------------------------------------------------------------------------

CREATE TABLE source_documents (
    source_document_id   TEXT PRIMARY KEY,          -- content-addressed id
    mime_type            TEXT NOT NULL,
    encoding             TEXT NOT NULL,
    provenance           TEXT NOT NULL,             -- institution/account/channel description
    acquisition_time_utc TEXT NOT NULL CHECK (acquisition_time_utc GLOB '????-??-??T??:??:??*Z'),
    content_sha256       TEXT NOT NULL CHECK (length(content_sha256) = 64),
    raw_payload_ref      TEXT NOT NULL,             -- path under evidence/source_documents/
    created_at_utc       TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (content_sha256)
) STRICT;

CREATE TABLE source_records (
    source_record_id   TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL
        REFERENCES source_documents (source_document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    record_index       INTEGER NOT NULL CHECK (record_index >= 0),
    canonical_payload  TEXT NOT NULL,
    content_sha256     TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_at_utc     TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (source_document_id, record_index)
) STRICT;

-- ---------------------------------------------------------------------------
-- FITID trust records: schema slot only. Phase 2 populates it. Absent a row
-- for an (institution, account) pair, identity falls back to the SHA-256
-- fingerprint.
-- ---------------------------------------------------------------------------

CREATE TABLE fitid_trust_records (
    institution_id TEXT NOT NULL,
    account_id     TEXT NOT NULL,
    added_at_utc   TEXT NOT NULL CHECK (added_at_utc GLOB '????-??-??T??:??:??*Z'),
    note           TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (institution_id, account_id)
) STRICT;

-- ---------------------------------------------------------------------------
-- Staging: proposed transactions awaiting operator approval
-- ---------------------------------------------------------------------------

CREATE TABLE staged_transactions (
    staged_transaction_id TEXT PRIMARY KEY,
    source_record_id      TEXT NOT NULL
        REFERENCES source_records (source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    status                TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    proposed_date         TEXT NOT NULL CHECK (proposed_date GLOB '????-??-??'),
    payee                 TEXT NOT NULL DEFAULT '',
    narration             TEXT NOT NULL DEFAULT '',
    identity_algo_version INTEGER NOT NULL CHECK (identity_algo_version >= 1),
    identity_method       TEXT NOT NULL CHECK (identity_method IN ('fitid', 'sha256_fallback')),
    identity_fingerprint  TEXT NOT NULL CHECK (length(identity_fingerprint) = 64),
    created_at_utc        TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    decided_at_utc        TEXT CHECK (decided_at_utc IS NULL OR decided_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (identity_algo_version, identity_fingerprint)
) STRICT;

-- ---------------------------------------------------------------------------
-- Compile runs: append-only, monotonic. Written in Phase 3; columns fixed now.
-- ---------------------------------------------------------------------------

CREATE TABLE compile_runs (
    compile_run_id       TEXT PRIMARY KEY,
    beancount_version    TEXT NOT NULL,
    compiler_version     TEXT NOT NULL,
    input_hash           TEXT NOT NULL CHECK (length(input_hash) = 64),
    intended_output_hash TEXT NOT NULL CHECK (length(intended_output_hash) = 64),
    actual_output_hash   TEXT CHECK (actual_output_hash IS NULL OR length(actual_output_hash) = 64),
    status               TEXT NOT NULL
        CHECK (status IN ('started', 'succeeded', 'failed', 'recovered')),
    started_at_utc       TEXT NOT NULL CHECK (started_at_utc GLOB '????-??-??T??:??:??*Z'),
    finished_at_utc      TEXT CHECK (finished_at_utc IS NULL OR finished_at_utc GLOB '????-??-??T??:??:??*Z'),
    recovery_state       TEXT NOT NULL DEFAULT 'none'
) STRICT;

-- ---------------------------------------------------------------------------
-- Ledger index: derived from Beancount, rebuildable, never authoritative
-- ---------------------------------------------------------------------------

CREATE TABLE ledger_entries (
    ledger_entry_id       TEXT PRIMARY KEY,
    staged_transaction_id TEXT NOT NULL
        REFERENCES staged_transactions (staged_transaction_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    compile_run_id        TEXT
        REFERENCES compile_runs (compile_run_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    entry_date            TEXT NOT NULL CHECK (entry_date GLOB '????-??-??'),
    flag                  TEXT NOT NULL DEFAULT '*' CHECK (length(flag) = 1),
    payee                 TEXT NOT NULL DEFAULT '',
    narration             TEXT NOT NULL DEFAULT '',
    created_at_utc        TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z')
) STRICT;

CREATE TABLE ledger_postings (
    ledger_posting_id     TEXT PRIMARY KEY,
    ledger_entry_id       TEXT NOT NULL
        REFERENCES ledger_entries (ledger_entry_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    source_record_id      TEXT NOT NULL
        REFERENCES source_records (source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    account               TEXT NOT NULL CHECK (
        account GLOB 'Assets:*' OR account GLOB 'Liabilities:*' OR account GLOB 'Equity:*'
        OR account GLOB 'Income:*' OR account GLOB 'Expenses:*'
    ),
    minor_units           INTEGER NOT NULL,
    currency              TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
    minor_unit_scale      INTEGER NOT NULL CHECK (minor_unit_scale >= 0),
    identity_algo_version INTEGER NOT NULL CHECK (identity_algo_version >= 1),
    identity_method       TEXT NOT NULL CHECK (identity_method IN ('fitid', 'sha256_fallback')),
    identity_fingerprint  TEXT NOT NULL CHECK (length(identity_fingerprint) = 64),
    created_at_utc        TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z')
) STRICT;

-- ---------------------------------------------------------------------------
-- Audit stream: append-only, monotonic seq, hash chained. Enforcement of the
-- chain and append-only triggers is Phase 1 task 5.
-- ---------------------------------------------------------------------------

CREATE TABLE audit_events (
    seq                INTEGER PRIMARY KEY,          -- explicit monotonic allocation, not AUTOINCREMENT
    ts_utc             TEXT NOT NULL CHECK (ts_utc GLOB '????-??-??T??:??:??*Z'),
    actor              TEXT NOT NULL,
    action             TEXT NOT NULL,
    target             TEXT NOT NULL,
    result             TEXT NOT NULL CHECK (result IN ('ok', 'denied', 'error')),
    projection_version TEXT,
    compile_run_id     TEXT
        REFERENCES compile_runs (compile_run_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    input_hash         TEXT CHECK (input_hash IS NULL OR length(input_hash) = 64),
    output_hash        TEXT CHECK (output_hash IS NULL OR length(output_hash) = 64),
    prev_event_hash    TEXT NOT NULL CHECK (length(prev_event_hash) = 64),
    event_hash         TEXT NOT NULL CHECK (length(event_hash) = 64),
    CHECK (seq >= 1),
    UNIQUE (event_hash)
) STRICT;

CREATE INDEX idx_source_records_document ON source_records (source_document_id);
CREATE INDEX idx_staged_source_record ON staged_transactions (source_record_id);
CREATE INDEX idx_ledger_entries_staged ON ledger_entries (staged_transaction_id);
CREATE INDEX idx_ledger_postings_entry ON ledger_postings (ledger_entry_id);
CREATE INDEX idx_ledger_postings_source ON ledger_postings (source_record_id);
CREATE INDEX idx_ledger_postings_account ON ledger_postings (account);
