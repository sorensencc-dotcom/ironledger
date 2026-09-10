-- src/ironledger/db/schema/0007_simplefin_sync.sql
-- Phase 7: SimpleFIN sync support.

ALTER TABLE staged_transactions ADD COLUMN external_id TEXT;

-- Partial unique index: only non-NULL external_ids must be unique.
-- SQLite ALTER TABLE cannot add UNIQUE inline; partial index is idiomatic.
CREATE UNIQUE INDEX idx_staged_transactions_external_id
    ON staged_transactions (external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE simplefin_account_map (
    remote_account_id  TEXT PRIMARY KEY,
    canonical_account  TEXT NOT NULL,
    added_at_utc       TEXT NOT NULL CHECK (added_at_utc GLOB '????-??-??T??:??:??*Z')
) STRICT;

CREATE TRIGGER simplefin_account_map_no_update
BEFORE UPDATE ON simplefin_account_map
BEGIN
    SELECT RAISE(ABORT, 'simplefin_account_map is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER simplefin_account_map_no_delete
BEFORE DELETE ON simplefin_account_map
BEGIN
    SELECT RAISE(ABORT, 'simplefin_account_map is append-only: DELETE is forbidden');
END;

