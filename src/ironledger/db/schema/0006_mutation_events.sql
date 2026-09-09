-- IronLedger Phase 5 / Meta-Ledger: append-only ledger mutation events.

CREATE TABLE mutation_events (
    seq                 INTEGER PRIMARY KEY,
    mutation_id         TEXT NOT NULL,
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
    UNIQUE (mutation_hash)
) STRICT;

CREATE INDEX idx_mutation_events_session ON mutation_events (operator_session);
CREATE INDEX idx_mutation_events_action ON mutation_events (action);

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
