-- Migration 0018: evidence-linked identity. Many source records may attach
-- to one staged event. Proposals wait for operator confirm. Do not widen
-- staged_transactions.status.

CREATE TABLE event_evidence (
    evidence_id            TEXT PRIMARY KEY,
    ledger_id              TEXT NOT NULL DEFAULT 'default'
        REFERENCES ledgers (ledger_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    staged_transaction_id  TEXT NOT NULL
        REFERENCES staged_transactions (staged_transaction_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source_record_id       TEXT NOT NULL
        REFERENCES source_records (source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source_document_id     TEXT NOT NULL
        REFERENCES source_documents (source_document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    role                   TEXT NOT NULL CHECK (role IN ('primary', 'enrichment')),
    description_text       TEXT NOT NULL DEFAULT '',
    created_at_utc         TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (source_record_id),
    UNIQUE (staged_transaction_id, source_document_id)
) STRICT;

CREATE INDEX idx_event_evidence_staged ON event_evidence (ledger_id, staged_transaction_id);
CREATE INDEX idx_event_evidence_document ON event_evidence (ledger_id, source_document_id);

CREATE TABLE attach_proposals (
    proposal_id            TEXT PRIMARY KEY,
    ledger_id              TEXT NOT NULL DEFAULT 'default'
        REFERENCES ledgers (ledger_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source_record_id       TEXT NOT NULL
        REFERENCES source_records (source_record_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source_document_id     TEXT NOT NULL
        REFERENCES source_documents (source_document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    kind                   TEXT NOT NULL CHECK (kind IN ('unique', 'ambiguous', 'near_miss')),
    candidate_staged_ids   TEXT NOT NULL CHECK (json_valid(candidate_staged_ids) = 1 AND json_type(candidate_staged_ids) = 'array'),
    chosen_staged_id       TEXT
        REFERENCES staged_transactions (staged_transaction_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    staged_input_json      TEXT NOT NULL CHECK (json_valid(staged_input_json) = 1),
    status                 TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at_utc         TEXT NOT NULL CHECK (created_at_utc GLOB '????-??-??T??:??:??*Z'),
    decided_at_utc         TEXT CHECK (decided_at_utc IS NULL OR decided_at_utc GLOB '????-??-??T??:??:??*Z'),
    UNIQUE (source_record_id)
) STRICT;

CREATE INDEX idx_attach_proposals_status ON attach_proposals (ledger_id, status);
CREATE INDEX idx_attach_proposals_document ON attach_proposals (ledger_id, source_document_id);
