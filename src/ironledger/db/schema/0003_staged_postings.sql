-- IronLedger Phase 2a: proposed postings for staged transactions.
--
-- A staged transaction header (0001) carries no amount. Phase 2a proposes two
-- postings per staged transaction: an `imported` leg that names the account the
-- file was imported for, and a `contra` leg whose account is NULL until Phase 2b
-- categorization sets it. The two minor_units values sum to zero for the
-- currency, so a same-currency balance check passes before categorization.
--
-- Deletion rules:
--   * Proposed postings are a workflow record, not evidence. They cascade with
--     their staged_transactions header.
--   * Their link back to source_records is RESTRICT: evidence is never deleted
--     out from under a posting.

CREATE TABLE staged_postings (
    staged_posting_id     TEXT PRIMARY KEY,
    staged_transaction_id TEXT NOT NULL
        REFERENCES staged_transactions (staged_transaction_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    source_record_id      TEXT NOT NULL
        REFERENCES source_records (source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
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
    UNIQUE (staged_transaction_id, posting_index)
) STRICT;

CREATE INDEX idx_staged_postings_transaction ON staged_postings (staged_transaction_id);
CREATE INDEX idx_staged_postings_source ON staged_postings (source_record_id);
