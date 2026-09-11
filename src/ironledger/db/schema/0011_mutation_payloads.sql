-- Migration 0011: Mutation Payloads & Point-in-Time Audit Replay

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
    FOREIGN KEY(seq) REFERENCES mutation_events(seq) ON DELETE CASCADE
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
